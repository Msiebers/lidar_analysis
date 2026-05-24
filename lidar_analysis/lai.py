from __future__ import annotations

import math
from typing import Any
from warnings import warn

import numpy as np
import pandas as pd


_ZENITH_BREAKS_DEG = np.array((0, 15, 30, 45, 60, 75), dtype=float)
_GAP_DISTANCE_M = 30.0


def _legacy_lai_from_distances_zeniths(distances: np.ndarray, zeniths_rad: np.ndarray) -> tuple[float, np.ndarray, int]:
    zenith_breaks = np.deg2rad(_ZENITH_BREAKS_DEG)
    mean_zenith_breaks = ((zenith_breaks[:-1] + zenith_breaks[1:]) / 2)[::-1]
    coefs = np.sin(mean_zenith_breaks) * np.cos(mean_zenith_breaks) * np.diff(zenith_breaks)

    n_scans = int(distances.shape[0])
    gap_matrix = np.empty((n_scans, len(mean_zenith_breaks)), dtype=float)

    zeniths_abs = np.abs(zeniths_rad)
    zen_group_inds: list[np.ndarray] = []
    for j in range(len(zenith_breaks) - 1):
        mask = (zeniths_abs >= zenith_breaks[j]) & (zeniths_abs < zenith_breaks[j + 1])
        zen_group_inds.append(np.flatnonzero(mask))

    for i in range(n_scans):
        scan = np.asarray(distances[i], dtype=float)
        is_gap = scan > _GAP_DISTANCE_M
        for zen_ind, group in enumerate(zen_group_inds):
            if group.size == 0:
                gap_matrix[i, zen_ind] = np.nan
            else:
                gap_matrix[i, zen_ind] = float(np.nanmean(is_gap[group].astype(float)))

    gap_fraction = np.nanmean(gap_matrix, axis=0)
    zero_inds = np.logical_or(gap_fraction == 0, np.isnan(gap_fraction))
    corrected_zero_gaps = int(np.count_nonzero(zero_inds))
    if np.all(zero_inds):
        return float("inf"), gap_fraction, corrected_zero_gaps

    if np.any(zero_inds):
        valid = ~zero_inds
        if np.any(valid):
            warn("Correcting LAI.")
            mean_thing = -np.nanmean(np.log(gap_fraction[valid]) * np.cos(mean_zenith_breaks)[valid])
            gap_fraction[zero_inds] = np.exp(-mean_thing / np.cos(mean_zenith_breaks)[zero_inds])
        else:
            return float("inf"), gap_fraction, corrected_zero_gaps

    temp = -np.log(gap_fraction) * coefs
    return float(2 * np.nansum(temp)), gap_fraction, corrected_zero_gaps


def compute_lai_traits(df: pd.DataFrame) -> dict[str, Any]:
    # Legacy behavior path: use phi as zenith-like angle for now.
    if "range_m" in df.columns:
        ranges_m = df["range_m"].to_numpy(dtype=float, copy=False)
    elif "dist_mm" in df.columns:
        ranges_m = df["dist_mm"].to_numpy(dtype=float, copy=False) / 1000.0
    else:
        ranges_m = np.full((len(df),), np.nan, dtype=float)

    if "phi" in df.columns:
        zeniths_rad = np.abs(df["phi"].to_numpy(dtype=float, copy=False))
    elif "theta" in df.columns:
        theta_deg = np.rad2deg(df["theta"].to_numpy(dtype=float, copy=False))
        zenith_deg = np.abs(180.0 - theta_deg)
        zeniths_rad = np.deg2rad(zenith_deg)
    else:
        zeniths_rad = np.full((len(df),), np.nan, dtype=float)

    valid = np.isfinite(ranges_m) & np.isfinite(zeniths_rad) & (ranges_m > 0)
    ranges_m = ranges_m[valid]
    zeniths_rad = zeniths_rad[valid]

    traits = {
        "lai": float("nan"),
        "lai_gap_fraction_ring_1": float("nan"),
        "lai_gap_fraction_ring_2": float("nan"),
        "lai_gap_fraction_ring_3": float("nan"),
        "lai_gap_fraction_ring_4": float("nan"),
        "lai_gap_fraction_ring_5": float("nan"),
        "lai_n_scans": int(0),
        "lai_n_rays": int(len(df)),
        "lai_n_valid_rings": int(0),
        "lai_corrected_zero_gaps": int(0),
    }
    if ranges_m.size == 0:
        return traits

    distances = ranges_m[None, :]
    lai_val, gap_fraction, corrected_zero_gaps = _legacy_lai_from_distances_zeniths(distances, zeniths_rad)
    traits["lai"] = float(lai_val)
    traits["lai_n_scans"] = int(distances.shape[0])
    traits["lai_n_rays"] = int(ranges_m.size)
    traits["lai_n_valid_rings"] = int(np.count_nonzero(np.isfinite(gap_fraction)))
    traits["lai_corrected_zero_gaps"] = int(corrected_zero_gaps)
    for i in range(min(5, gap_fraction.size)):
        traits[f"lai_gap_fraction_ring_{i+1}"] = float(gap_fraction[i])
    return traits

