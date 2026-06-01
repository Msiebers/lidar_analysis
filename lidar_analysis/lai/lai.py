from __future__ import annotations

import math
from typing import Any

import numpy as np

from .fad import (
    EVEN_ZENITH_BREAKS_RAD,
    UNEVEN_ZENITH_BREAKS_RAD,
    legacy_lai,
)

_LAI_GAP_FRACTION_RINGS = 5


def _empty_lai_traits(
    *,
    gap_distance_m: float,
    angle_column: str | None = None,
    distance_column: str | None = None,
    n_missing_range: int = 0,
    n_missing_angle: int = 0,
) -> dict[str, Any]:
    traits: dict[str, Any] = {
        "lai_even": float("nan"),
        "lai_uneven": float("nan"),
        "lai_n_scans": 0,
        "lai_n_angles": 0,
        "lai_n_rays": 0,
        "lai_gap_distance_m": float(gap_distance_m),
        "lai_even_corrected_zero_gap_bins": False,
        "lai_uneven_corrected_zero_gap_bins": False,
        "lai_angle_column_used": angle_column,
        "lai_distance_column_used": distance_column,
        "lai_n_missing_range": int(n_missing_range),
        "lai_n_missing_angle": int(n_missing_angle),
    }
    for prefix in ("lai_even", "lai_uneven"):
        for ring_i in range(1, _LAI_GAP_FRACTION_RINGS + 1):
            traits[f"{prefix}_gap_fraction_ring_{ring_i}"] = float("nan")
    return traits


def _flatten_lai_pair(
    pair: dict[str, Any],
    *,
    gap_distance_m: float,
    n_rays: int,
    angle_column: str | None = None,
    distance_column: str | None = None,
    n_missing_range: int = 0,
    n_missing_angle: int = 0,
) -> dict[str, Any]:
    traits = _empty_lai_traits(
        gap_distance_m=gap_distance_m,
        angle_column=angle_column,
        distance_column=distance_column,
        n_missing_range=n_missing_range,
        n_missing_angle=n_missing_angle,
    )
    traits.update({
        "lai_even": float(pair.get("lai_even", float("nan"))),
        "lai_uneven": float(pair.get("lai_uneven", float("nan"))),
        "lai_n_scans": int(pair.get("lai_n_scans", 0) or 0),
        "lai_n_angles": int(pair.get("lai_n_angles", 0) or 0),
        "lai_n_rays": int(n_rays),
        "lai_gap_distance_m": float(pair.get("lai_gap_distance_m", gap_distance_m)),
        "lai_even_corrected_zero_gap_bins": bool(pair.get("lai_even_corrected_zero_gap_bins", False)),
        "lai_uneven_corrected_zero_gap_bins": bool(pair.get("lai_uneven_corrected_zero_gap_bins", False)),
    })

    for prefix in ("lai_even", "lai_uneven"):
        vals = np.asarray(pair.get(f"{prefix}_gap_fraction", []), dtype=float).ravel()
        for ring_i in range(1, _LAI_GAP_FRACTION_RINGS + 1):
            traits[f"{prefix}_gap_fraction_ring_{ring_i}"] = (
                float(vals[ring_i - 1]) if ring_i <= vals.size else float("nan")
            )

    return traits


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

    distances = np.asarray(lidar_data["distances"], dtype=float)
    zeniths = np.asarray(lidar_data["zeniths"], dtype=float)
    pair = compute_legacy_lai_pair(
        distances_m=distances,
        zeniths_rad=zeniths,
        gap_distance_m=gap_distance_m,
    )
    return _flatten_lai_pair(
        pair,
        gap_distance_m=gap_distance_m,
        n_rays=int(distances.size),
    )


def compute_lai_trait_from_target(target: Any, *, gap_distance_m: float = 30.0) -> dict[str, Any]:
    """
    Compute legacy LAI traits from the target's initially split ray rows.

    The current pipeline stores the split plot/plant rows in AnalysisTarget.raw_points
    before pointcloud filters mutate current_points, so this wrapper uses raw_points
    to keep LAI aligned to the target Z interval without losing rows to later filters.
    """
    points = getattr(target, "raw_points", None)
    if points is None or len(points) == 0:
        return _empty_lai_traits(gap_distance_m=gap_distance_m)

    if "range_m" in points.columns:
        distance_column = "range_m"
        distances_m = points["range_m"].to_numpy(dtype=float, copy=False)
    elif "dist_mm" in points.columns:
        distance_column = "dist_mm"
        distances_m = points["dist_mm"].to_numpy(dtype=float, copy=False) / 1000.0
    else:
        return _empty_lai_traits(gap_distance_m=gap_distance_m)

    if "theta" not in points.columns:
        return _empty_lai_traits(
            gap_distance_m=gap_distance_m,
            distance_column=distance_column,
            n_missing_angle=len(points),
        )

    angle_column = "theta_sky_half"
    theta = points["theta"].to_numpy(dtype=float, copy=False)

    # Legacy comparison LAI sky-facing sector for the cart-mounted SICK.
    #
    # Physical cap orientation:
    #   theta =   0 deg  -> down / ground
    #   theta = +90 deg  -> side / horizon
    #   theta = -90 deg  -> side / horizon
    #   theta = +/-180   -> up / sky
    #
    # Therefore legacy zenith-from-sky is:
    #   theta = +/-180 deg -> zenith = 0 deg
    #   theta = +/-90 deg  -> zenith = 90 deg
    #
    # We exclude the downward half near theta = 0.
    # This is still legacy comparison LAI, not world-zenith-corrected geometry.
    finite_theta = theta[np.isfinite(theta)]
    if finite_theta.size and np.nanmax(np.abs(finite_theta)) > (2.0 * math.pi + 1e-6):
        theta = np.deg2rad(theta)

    # Normalize theta to [-pi, pi].
    theta = ((theta + math.pi) % (2.0 * math.pi)) - math.pi

    # Distance from the sky/up direction at +/-pi.
    zeniths_rad = math.pi - np.abs(theta)

    # Keep only the sky-facing half: zenith 0..90 degrees.
    theta_sector = (zeniths_rad >= 0.0) & (zeniths_rad <= 0.5 * math.pi)

    range_ok = np.isfinite(distances_m)
    angle_ok = np.isfinite(zeniths_rad)
    valid = range_ok & angle_ok & theta_sector
    n_missing_range = int((~range_ok).sum())
    n_missing_angle = int((~angle_ok).sum())

    if not np.any(valid):
        return _empty_lai_traits(
            gap_distance_m=gap_distance_m,
            angle_column=angle_column,
            distance_column=distance_column,
            n_missing_range=n_missing_range,
            n_missing_angle=n_missing_angle,
        )

    distances_scan = distances_m[valid].copy()

    # SICK raw CSVs appear to encode no-return / no-hit beams as distance 0.
    # The legacy LAI algorithm expects gaps to be distances > gap_distance_m.
    # Convert zero-distance sky-sector rays to a legacy gap sentinel so the
    # old gap-fraction calculation can see them as canopy escapes.
    zero_distance_as_gap = distances_scan <= 0.0
    distances_scan[zero_distance_as_gap] = gap_distance_m + 1.0
    distances_scan = distances_scan[None, :]

    zeniths_scan = zeniths_rad[valid]
    pair = compute_legacy_lai_pair(
        distances_m=distances_scan,
        zeniths_rad=zeniths_scan,
        gap_distance_m=gap_distance_m,
    )
    return _flatten_lai_pair(
        pair,
        gap_distance_m=gap_distance_m,
        n_rays=int(valid.sum()),
        angle_column=angle_column,
        distance_column=distance_column,
        n_missing_range=n_missing_range,
        n_missing_angle=n_missing_angle,
    )
