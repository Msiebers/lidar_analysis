from __future__ import annotations

"""Lightweight LiDAR beam diagnostics for future LAI/FAD ray-attempt accounting.

Future FAD work may classify emitted attempts through canopy boxes into categories
such as attempted, intercepted, passed-through, blocked-before-box, and missed.
This module does not implement those classifications; it only provides compact
beam structure diagnostics to evaluate whether rotation_id × beam_id is feasible.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BeamDiagnosticResult:
    beam_lookup: pd.DataFrame
    beam_id_by_row: np.ndarray
    summary: dict[str, float | int | str | bool]


def compute_beam_diagnostics(
    fused_np: np.ndarray,
    *,
    phi_col: int = 1,
    theta_col: int = 2,
    rounding_decimals: int = 6,
) -> BeamDiagnosticResult:
    if fused_np.ndim != 2 or fused_np.shape[0] == 0:
        empty = pd.DataFrame(columns=["beam_id", "phi", "theta", "count", "phi_rounded", "theta_rounded"])
        return BeamDiagnosticResult(beam_lookup=empty, beam_id_by_row=np.empty((0,), dtype=np.int32), summary={"n_fused_rows": 0})

    phi = fused_np[:, phi_col].astype(np.float64, copy=False)
    theta = fused_np[:, theta_col].astype(np.float64, copy=False)
    valid = np.isfinite(phi) & np.isfinite(theta)

    phi_round = np.round(phi, rounding_decimals)
    theta_round = np.round(theta, rounding_decimals)

    beams = pd.DataFrame({
        "phi": phi,
        "theta": theta,
        "phi_rounded": phi_round,
        "theta_rounded": theta_round,
        "valid": valid,
    })
    valid_rows = beams[beams["valid"]].copy()

    grouped = (
        valid_rows.groupby(["phi_rounded", "theta_rounded"], sort=True, as_index=False)
        .agg(phi=("phi", "median"), theta=("theta", "median"), count=("phi", "size"))
    )
    grouped.insert(0, "beam_id", np.arange(grouped.shape[0], dtype=np.int32))
    grouped = grouped[["beam_id", "phi", "theta", "count", "phi_rounded", "theta_rounded"]]

    merged = beams[["phi_rounded", "theta_rounded", "valid"]].merge(
        grouped[["beam_id", "phi_rounded", "theta_rounded"]],
        on=["phi_rounded", "theta_rounded"],
        how="left",
        sort=False,
    )
    beam_id_by_row = merged["beam_id"].to_numpy(dtype=np.float64)
    beam_id_by_row = np.where(np.isfinite(beam_id_by_row), beam_id_by_row, -1).astype(np.int32)

    counts = grouped["count"].to_numpy(dtype=np.float64) if not grouped.empty else np.array([], dtype=np.float64)
    if counts.size > 0:
        cmin = int(np.min(counts))
        cmax = int(np.max(counts))
        cmean = float(np.mean(counts))
        cmedian = float(np.median(counts))
        stable = bool((cmin > 0) and ((cmax / cmin) <= 1.5))
    else:
        cmin = cmax = 0
        cmean = cmedian = 0.0
        stable = False

    summary: dict[str, float | int | str | bool] = {
        "n_fused_rows": int(fused_np.shape[0]),
        "n_valid_angle_rows": int(valid.sum()),
        "n_unique_beams": int(grouped.shape[0]),
        "n_unique_phi": int(np.unique(phi_round[valid]).size) if np.any(valid) else 0,
        "n_unique_theta": int(np.unique(theta_round[valid]).size) if np.any(valid) else 0,
        "rows_per_beam_min": cmin,
        "rows_per_beam_median": cmedian,
        "rows_per_beam_max": cmax,
        "rows_per_beam_mean": cmean,
        "beam_count_stable": stable,
        "rotation_inference": "uncertain",
        "rotation_note": "No reliable explicit rotation marker found in fused rows; rotation_id withheld.",
    }
    return BeamDiagnosticResult(beam_lookup=grouped, beam_id_by_row=beam_id_by_row, summary=summary)


def write_beam_diagnostics_csv(out_dir: str, scan_base: str, result: BeamDiagnosticResult) -> str:
    out_path = f"{out_dir}/{scan_base}_beam_diagnostics.csv"
    result.beam_lookup.to_csv(out_path, index=False)
    return out_path
