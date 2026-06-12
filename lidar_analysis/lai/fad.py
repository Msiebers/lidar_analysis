from __future__ import annotations

from dataclasses import dataclass
import math
import warnings

import numpy as np


EVEN_ZENITH_BREAKS_RAD = np.array((0, 15, 30, 45, 60, 75), dtype=float) / 180.0 * math.pi
UNEVEN_ZENITH_BREAKS_RAD = np.array((0, 13, 28, 43, 58, 75), dtype=float) / 180.0 * math.pi


@dataclass(frozen=True)
class LaiResult:
    lai: float
    gap_fraction: np.ndarray
    zenith_bin_centers_rad: np.ndarray
    zenith_breaks_rad: np.ndarray
    n_scans: int
    n_angles: int
    corrected_zero_gap_bins: bool


def compute_gap_fraction_by_zenith(
    *,
    distances_m: np.ndarray,
    zeniths_rad: np.ndarray,
    zenith_breaks_rad: np.ndarray,
    gap_distance_m: float = 30.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Legacy gap-fraction calculation.

    distances_m:
        2D array, shape n_scans x n_angles, in meters.

    zeniths_rad:
        1D array, shape n_angles, in radians.
        0 means vertical/up after legacy conversion.

    zenith_breaks_rad:
        Bin breaks in radians.

    gap_distance_m:
        Distances greater than this are treated as gaps.
        Legacy value was 30 m.
    """
    distances_m = np.asarray(distances_m, dtype=float)
    zeniths_rad = np.asarray(zeniths_rad, dtype=float)
    zenith_breaks_rad = np.asarray(zenith_breaks_rad, dtype=float)

    if distances_m.ndim != 2:
        raise ValueError("distances_m must be a 2D array: n_scans x n_angles")

    n_scans, n_angles = distances_m.shape

    if zeniths_rad.ndim != 1:
        raise ValueError("zeniths_rad must be a 1D array")

    if len(zeniths_rad) != n_angles:
        raise ValueError(
            f"zeniths_rad length ({len(zeniths_rad)}) must match distances_m angle dimension ({n_angles})"
        )

    if n_scans == 0:
        return np.full(len(zenith_breaks_rad) - 1, np.nan), zenith_breaks_rad

    abs_zeniths = np.abs(zeniths_rad)
    gap_matrix = np.full((n_scans, len(zenith_breaks_rad) - 1), np.nan, dtype=float)

    zenith_group_indices: list[np.ndarray] = []
    for j in range(len(zenith_breaks_rad) - 1):
        lo = zenith_breaks_rad[j]
        hi = zenith_breaks_rad[j + 1]
        idx = np.flatnonzero((abs_zeniths >= lo) & (abs_zeniths < hi))
        zenith_group_indices.append(idx)

    for scan_i in range(n_scans):
        is_gap = distances_m[scan_i, :] > gap_distance_m

        for zen_i, idx in enumerate(zenith_group_indices):
            if len(idx) == 0:
                gap_matrix[scan_i, zen_i] = np.nan
            else:
                gap_matrix[scan_i, zen_i] = np.sum(is_gap[idx]) / len(idx)

    gap_fraction = np.nanmean(gap_matrix, axis=0)
    return gap_fraction, zenith_breaks_rad


def legacy_lai_from_gap_fraction(
    *,
    gap_fraction: np.ndarray,
    zenith_breaks_rad: np.ndarray,
    correct_zero_gap_bins: bool = True,
) -> tuple[float, np.ndarray, np.ndarray, bool]:
    """
    Legacy LAI integration from binned gap fraction.

    This follows the uploaded old code:
        coefs = sin(theta) * cos(theta) * diff(zenith_breaks)
        lai = 2 * sum(-log(gap_fraction) * coefs)

    For zero/NaN gap bins, the old code estimated replacement gap fractions
    from the usable bins rather than letting the whole calculation become inf.
    """
    gap_fraction = np.asarray(gap_fraction, dtype=float).copy()
    zenith_breaks_rad = np.asarray(zenith_breaks_rad, dtype=float)

    # Legacy code used reversed bin centers.
    zenith_centers = ((zenith_breaks_rad[:-1] + zenith_breaks_rad[1:]) / 2.0)[::-1]
    coefs = np.sin(zenith_centers) * np.cos(zenith_centers) * np.diff(zenith_breaks_rad)

    bad = (gap_fraction == 0) | np.isnan(gap_fraction)

    if np.all(bad):
        return float("inf"), gap_fraction, zenith_centers, False

    corrected = False

    if np.any(bad):
        if not correct_zero_gap_bins:
            return float("inf"), gap_fraction, zenith_centers, False

        warnings.warn("Correcting LAI zero/NaN gap-fraction bins.", RuntimeWarning)

        usable = ~bad
        mean_thing = -np.mean(np.log(gap_fraction[usable]) * np.cos(zenith_centers[usable]))
        gap_fraction[bad] = np.exp(-mean_thing / np.cos(zenith_centers[bad]))
        corrected = True

    temp = -np.log(gap_fraction) * coefs
    lai = 2.0 * np.sum(temp)

    return float(lai), gap_fraction, zenith_centers, corrected


def legacy_lai(
    *,
    distances_m: np.ndarray,
    zeniths_rad: np.ndarray,
    zenith_breaks_rad: np.ndarray,
    gap_distance_m: float = 30.0,
    correct_zero_gap_bins: bool = True,
) -> LaiResult:
    """
    Full legacy LAI calculation.

    This is intentionally independent of AnalysisTarget for now.
    The pipeline wrapper should prepare distances_m and zeniths_rad, then call this.
    """
    distances_m = np.asarray(distances_m, dtype=float)

    if distances_m.ndim != 2:
        raise ValueError("distances_m must be a 2D array")

    n_scans, n_angles = distances_m.shape

    if n_scans == 0:
        return LaiResult(
            lai=float("nan"),
            gap_fraction=np.array([], dtype=float),
            zenith_bin_centers_rad=np.array([], dtype=float),
            zenith_breaks_rad=np.asarray(zenith_breaks_rad, dtype=float),
            n_scans=0,
            n_angles=n_angles,
            corrected_zero_gap_bins=False,
        )

    gap_fraction, breaks = compute_gap_fraction_by_zenith(
        distances_m=distances_m,
        zeniths_rad=zeniths_rad,
        zenith_breaks_rad=zenith_breaks_rad,
        gap_distance_m=gap_distance_m,
    )

    lai, corrected_gap_fraction, centers, corrected = legacy_lai_from_gap_fraction(
        gap_fraction=gap_fraction,
        zenith_breaks_rad=breaks,
        correct_zero_gap_bins=correct_zero_gap_bins,
    )

    return LaiResult(
        lai=lai,
        gap_fraction=corrected_gap_fraction,
        zenith_bin_centers_rad=centers,
        zenith_breaks_rad=breaks,
        n_scans=n_scans,
        n_angles=n_angles,
        corrected_zero_gap_bins=corrected,
    )