from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .fad import (
    EVEN_ZENITH_BREAKS_RAD,
    UNEVEN_ZENITH_BREAKS_RAD,
    legacy_lai,
)


def compute_legacy_lai_pair(
    *,
    distances_m: np.ndarray,
    zeniths_rad: np.ndarray,
    gap_distance_m: float = 30.0,
) -> dict[str, Any]:
    """
    Compute both old LAI variants:
      - even zenith bins: 0, 15, 30, 45, 60, 90 degrees
      - uneven zenith bins: 0, 13, 28, 43, 58, 90 degrees

    This is the first-pass legacy behavior.
    """
    even = legacy_lai(
        distances_m=distances_m,
        zeniths_rad=zeniths_rad,
        zenith_breaks_rad=EVEN_ZENITH_BREAKS_RAD,
        gap_distance_m=gap_distance_m,
    )

    uneven = legacy_lai(
        distances_m=distances_m,
        zeniths_rad=zeniths_rad,
        zenith_breaks_rad=UNEVEN_ZENITH_BREAKS_RAD,
        gap_distance_m=gap_distance_m,
    )

    return {
        "lai_even": even.lai,
        "lai_uneven": uneven.lai,
        "lai_even_gap_fraction": even.gap_fraction,
        "lai_uneven_gap_fraction": uneven.gap_fraction,
        "lai_n_scans": even.n_scans,
        "lai_n_angles": even.n_angles,
        "lai_gap_distance_m": gap_distance_m,
        "lai_even_corrected_zero_gap_bins": even.corrected_zero_gap_bins,
        "lai_uneven_corrected_zero_gap_bins": uneven.corrected_zero_gap_bins,
    }


def compute_lai_trait_from_lidar_data(
    lidar_data: dict[str, Any],
    *,
    gap_distance_m: float = 30.0,
) -> dict[str, Any]:
    """
    Pipeline-friendly wrapper for old-style lidar_data dict.

    Expects:
      lidar_data["distances"] -> n_scans x n_angles, meters
      lidar_data["zeniths"]   -> n_angles, radians

    This matches the old uploaded LAI function's input shape.
    """
    if "distances" not in lidar_data:
        raise ValueError("lidar_data missing 'distances'")
    if "zeniths" not in lidar_data:
        raise ValueError("lidar_data missing 'zeniths'")

    return compute_legacy_lai_pair(
        distances_m=np.asarray(lidar_data["distances"], dtype=float),
        zeniths_rad=np.asarray(lidar_data["zeniths"], dtype=float),
        gap_distance_m=gap_distance_m,
    )


def compute_lai_trait_from_target(*args, **kwargs) -> dict[str, Any]:
    raise NotImplementedError("Use compute_lai_trait_from_points_df for pointcloud_ops integration.")


def compute_lai_trait_from_points_df(
    points_df: pd.DataFrame,
    *,
    gap_distance_m: float = 30.0,
) -> dict[str, Any]:
    """
    Legacy LAI trait computed directly from AnalysisTarget.current_points.

    This intentionally preserves the old working behavior:
      - Uses phi as the zenith-like angle source (legacy path converted from phi).
      - Treats the full target table at this op stage as a single scan (1 x N rays).
      - Uses fixed zenith breaks: [0, 15, 30, 45, 60, 75] degrees.
      - Uses fixed gap distance: 30.0 m.
      - Preserves zero-gap correction behavior.
    """
    if points_df is None or len(points_df) == 0:
        return {
            "lai": float("nan"),
            "lai_gap_fraction_ring_1": float("nan"),
            "lai_gap_fraction_ring_2": float("nan"),
            "lai_gap_fraction_ring_3": float("nan"),
            "lai_gap_fraction_ring_4": float("nan"),
            "lai_gap_fraction_ring_5": float("nan"),
            "lai_n_scans": 0,
            "lai_n_rays": 0,
            "lai_n_valid_rings": 0,
            "lai_corrected_zero_gaps": False,
        }

    if "phi" not in points_df.columns:
        raise ValueError("lai_trait requires 'phi' metadata column in current_points")

    if "range_m" in points_df.columns:
        dist_m = points_df["range_m"].to_numpy(dtype=float, copy=False)
    elif "dist_mm" in points_df.columns:
        dist_m = points_df["dist_mm"].to_numpy(dtype=float, copy=False) / 1000.0
    else:
        raise ValueError("lai_trait requires either 'range_m' or 'dist_mm' metadata column")

    phi = points_df["phi"].to_numpy(dtype=float, copy=False)
    # Legacy convention note:
    # historical LAI path derives zenith from phi via (pi/2 - phi), then abs().
    zeniths_rad = np.abs((0.5 * math.pi) - phi)
    distances_m = np.asarray(dist_m, dtype=float)[None, :]

    zenith_breaks_rad = np.array((0, 15, 30, 45, 60, 75), dtype=float) / 180.0 * math.pi
    result = legacy_lai(
        distances_m=distances_m,
        zeniths_rad=zeniths_rad,
        zenith_breaks_rad=zenith_breaks_rad,
        gap_distance_m=gap_distance_m,
        correct_zero_gap_bins=True,
    )

    gap = np.asarray(result.gap_fraction, dtype=float)
    n_valid_rings = int(np.sum(np.isfinite(gap)))
    return {
        "lai": float(result.lai),
        "lai_gap_fraction_ring_1": float(gap[0]) if gap.size > 0 else float("nan"),
        "lai_gap_fraction_ring_2": float(gap[1]) if gap.size > 1 else float("nan"),
        "lai_gap_fraction_ring_3": float(gap[2]) if gap.size > 2 else float("nan"),
        "lai_gap_fraction_ring_4": float(gap[3]) if gap.size > 3 else float("nan"),
        "lai_gap_fraction_ring_5": float(gap[4]) if gap.size > 4 else float("nan"),
        "lai_n_scans": int(result.n_scans),
        "lai_n_rays": int(result.n_angles),
        "lai_n_valid_rings": n_valid_rings,
        "lai_corrected_zero_gaps": bool(result.corrected_zero_gap_bins),
    }
