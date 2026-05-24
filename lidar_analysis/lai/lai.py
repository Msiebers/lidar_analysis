from __future__ import annotations

import math
from typing import Any

import numpy as np

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
    """
    Placeholder for the new AnalysisTarget wrapper.

    Do not guess this yet.

    LAI needs ray-level matrix data:
      distances_m: n_scans x n_angles
      zeniths_rad: n_angles

    AnalysisTarget.current_points alone probably is not enough, because it is a filtered
    point cloud, not the original ray matrix with gap/no-return information.

    The next step is to decide how the current pipeline should supply those inputs.
    """
    raise NotImplementedError(
        "LAI needs distances_m and zeniths_rad. Preserve or pass ray-level lidar data before wiring lai_trait."
    )