#!/usr/bin/env python3
"""Diagnose IMU/side/ground stages for the local scan_001/scan_002 pair."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.central_runner import build_config, read_calibration_from_cart_config
from lidar_analysis.mark_splitting import build_mark_segments, marker_buffer_mm
from lidar_analysis.pipeline_core import (
    apply_global_filters,
    choose_fusion_method,
    load_files_from_paths,
    reconstruct_world_points,
)
from lidar_analysis.pointcloud_ops import add_local_ground_height, apply_pointcloud_ops


DEFAULT_SOURCE = ROOT / "local_debug_data/standcount_pair/source"
PERCENTILES = (1, 5, 25, 50, 75, 95, 99)
PHYSICAL_PLOT = {
    "001": {"left": "row_1", "right": "middle_row"},
    "002": {"left": "middle_row", "right": "row_3"},
}


def _side(x: np.ndarray) -> np.ndarray:
    return np.where(x >= 0.0, "left", "right")


def _summary(scan: str, case: str, stage: str, xyz: np.ndarray, *, window="all", extra=None):
    rows = []
    if xyz.size == 0:
        return rows
    for side in ("left", "right"):
        values = xyz[_side(xyz[:, 0]) == side]
        row = {
            "scan": scan,
            "case": case,
            "stage": stage,
            "side": side,
            "window": window,
            "physical_plot": PHYSICAL_PLOT[scan][side],
            "n": len(values),
        }
        if len(values) == 0:
            rows.append(row)
            continue
        for col, axis in zip(("x", "y", "z"), range(3)):
            v = values[:, axis] / 1000.0
            row.update({f"{col}_min": np.nanmin(v), f"{col}_max": np.nanmax(v)})
            row.update({f"{col}_p{p:02d}": np.nanpercentile(v, p) for p in PERCENTILES})
        if extra:
            row.update(extra(side, values))
        rows.append(row)
    return rows


def _write_view(path: Path, df: pd.DataFrame, max_points: int, rng: np.random.Generator):
    if len(df) > max_points:
        df = df.iloc[np.sort(rng.choice(len(df), max_points, replace=False))]
    out = df.copy()
    out[["X", "Y", "Z"]] /= 1000.0
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def _angles(fused: np.ndarray, cfg) -> dict[str, float]:
    roll, pitch = fused[:, 6], fused[:, 7]
    if cfg.imu_zero_mode == "dense_median":
        from lidar_analysis.pipeline_core import dense_median
        rz = dense_median(roll, cfg.imu_zero_fraction)
        pz = dense_median(pitch, cfg.imu_zero_fraction)
    else:
        rz = pz = 0.0
    applied_r = (roll - rz) * cfg.roll_sign
    applied_p = (pitch - pz) * cfg.pitch_sign
    return {
        "roll_raw_min_deg": float(np.nanmin(roll)), "roll_raw_max_deg": float(np.nanmax(roll)),
        "pitch_raw_min_deg": float(np.nanmin(pitch)), "pitch_raw_max_deg": float(np.nanmax(pitch)),
        "roll_zero_deg": rz, "pitch_zero_deg": pz,
        "roll_applied_min_deg": float(np.nanmin(applied_r)), "roll_applied_max_deg": float(np.nanmax(applied_r)),
        "pitch_applied_min_deg": float(np.nanmin(applied_p)), "pitch_applied_max_deg": float(np.nanmax(applied_p)),
    }


def _windows(source: Path, scan_base: str, cfg, calib, zmax: float):
    marker = source / cfg.markers_dirname / f"{scan_base}_marker.csv"
    return build_mark_segments(
        marker, step_mm=calib["step_mm"], lidar_wheel_offset_mm=calib["lidar_wheel_offset_mm"],
        z_buffer_mm=marker_buffer_mm(cfg.mark_z_buffer_u, cfg.dim_units),
        target_type=cfg.mark_target_type, free_marks_as=cfg.free_marks_as, zmax_clip=zmax,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--max-view-points", type=int, default=50_000)
    args = ap.parse_args()
    source = args.source.resolve()
    out_dir = source.parent / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)

    document = yaml.safe_load((source / "experiment_config.yaml").read_text())
    analysis = document["analysis"]
    calib = read_calibration_from_cart_config(source / "cart_config.yaml")
    base_cfg = build_config(analysis, force=False, cart_id=calib["cart_id"], data_dir=source)
    width_mm = base_cfg.row_width_u * 1000.0
    x_min_mm = base_cfg.x_min_u * 1000.0
    min_radius_mm = base_cfg.min_radius_u * 1000.0
    rng = np.random.default_rng(42)
    summaries, retention = [], []

    scans = sorted(source.glob("scan_00[12]*_lidar.csv"))
    for lidar_path in scans:
        scan_base = lidar_path.name.removesuffix("_lidar.csv")
        scan = scan_base.split("_", 2)[1]
        pico_path = source / f"{scan_base}_pico.csv"
        lidar, pico = load_files_from_paths(lidar_path, pico_path)
        valid_raw = np.isfinite(lidar[:, 3]) & (lidar[:, 3] > 0)
        retention.append({"scan": scan, "case": "input", "stage": "raw_decoded", "n": len(lidar), "n_valid_range": int(valid_raw.sum())})
        fused = choose_fusion_method(base_cfg, lidar, pico)
        retention.append({"scan": scan, "case": "input", "stage": "time_fusion", "n": len(fused), "retained_pct": 100 * len(fused) / len(lidar)})
        angle_stats = _angles(fused, base_cfg)

        cases = [("imu_off", False, 1.0, -1.0)] + [
            (f"roll_{r:+.0f}_pitch_{p:+.0f}", True, r, p)
            for r in (1.0, -1.0) for p in (-1.0, 1.0)
        ]
        primary_cache = None
        for case, use_imu, roll_sign, pitch_sign in cases:
            cfg = copy.copy(base_cfg)
            cfg.use_imu, cfg.roll_sign, cfg.pitch_sign = use_imu, roll_sign, pitch_sign
            data, keep = reconstruct_world_points(
                fused, cfg, calib["step_mm"], calib["lidar_height_mm"],
                calib["roll_offset_deg"], calib["pitch_offset_deg"], min_radius_mm=min_radius_mm,
            )
            summaries += _summary(scan, case, "cartesian", data, extra=lambda _s, _v: angle_stats)
            before_masks = len(data)
            data, keep = apply_global_filters(scan_base, data, keep, width_mm, x_min_mm, None, min_radius_mm, cfg)
            summaries += _summary(scan, case, "global_masks_pre_split", data)
            retention.append({"scan": scan, "case": case, "stage": "global_masks", "n": len(data), "retained_pct": 100 * len(data) / before_masks})

            segments = _windows(source, scan_base, cfg, calib, float(np.nanmax(data[:, 2])))
            for window_no, segment in enumerate(segments, 1):
                in_window = (data[:, 2] > segment.min_z) & (data[:, 2] < segment.max_z)
                window_data = data[in_window]
                summaries += _summary(scan, case, "immediately_before_split", window_data, window=window_no)
                for side in ("left", "right"):
                    side_mask = window_data[:, 0] >= 0 if side == "left" else window_data[:, 0] < 0
                    side_data = window_data[side_mask]
                    fixed = side_data[side_data[:, 1] >= 100.0]
                    df = pd.DataFrame(side_data, columns=["X", "Y", "Z", "RSSI"])
                    grounded = add_local_ground_height(
                        df, x_bin_size_m=cfg.local_ground_x_bin_m * 1000.0,
                        z_bin_size_m=cfg.local_ground_z_bin_m * 1000.0,
                        ground_quantile=cfg.local_ground_quantile,
                        min_points_per_xz_bin=cfg.local_ground_min_points_per_xz_bin,
                        seed_y_min=None if cfg.local_ground_seed_y_min_m is None else cfg.local_ground_seed_y_min_m * 1000.0,
                        seed_y_max=None if cfg.local_ground_seed_y_max_m is None else cfg.local_ground_seed_y_max_m * 1000.0,
                    )
                    agl = grounded[grounded["height_agl"] >= cfg.min_height_agl_m * 1000.0]
                    for stage, frame in (("immediately_after_split", df), ("fixed_y_filter", pd.DataFrame(fixed, columns=df.columns)), ("local_ground_normalized", grounded), ("height_agl_filter", agl)):
                        xyz = frame[["X", "Y", "Z"]].to_numpy()
                        extra = {"ground_y_median_m": float(frame["ground_Y"].median() / 1000.0), "height_agl_p50_m": float(frame["height_agl"].median() / 1000.0), "height_agl_p95_m": float(frame["height_agl"].quantile(.95) / 1000.0)} if "ground_Y" in frame else {}
                        row = _summary(scan, case, stage, xyz, window=window_no)
                        row = [r for r in row if r["side"] == side]
                        for r in row:
                            r.update(extra)
                            r["rejected_n"] = len(df) - len(frame)
                            r["rejected_pct"] = 100 * (len(df) - len(frame)) / len(df) if len(df) else np.nan
                        summaries += row

                    if case == "roll_+1_pitch_-1":
                        ops = [op for op in cfg.pointcloud_ops if str(op.get("op", op.get("name", ""))).lower() != "height_range_filter"]
                        target = AnalysisTarget.from_points(
                            target_id=f"window_{window_no}_{side}", target_type="plot", scan_id=scan_base,
                            points_df=agl, source_indices=np.arange(len(agl)), side=side,
                        )
                        final_df = apply_pointcloud_ops(target, ops).current_points
                        row = _summary(scan, case, "remaining_enabled_ops", final_df[["X", "Y", "Z"]].to_numpy(), window=window_no)
                        row = [r for r in row if r["side"] == side]
                        for r in row:
                            r["rejected_n"] = len(agl) - len(final_df)
                            r["rejected_pct"] = 100 * (len(agl) - len(final_df)) / len(agl) if len(agl) else np.nan
                        summaries += row

                    if case == "roll_+1_pitch_-1":
                        stem = f"scan_{scan}_window_{window_no:02d}_{side}"
                        _write_view(out_dir / f"{stem}_after_imu.csv", df.assign(side=side), args.max_view_points, rng)
                        _write_view(out_dir / f"{stem}_local_ground.csv", grounded.assign(side=side), args.max_view_points, rng)
                        _write_view(out_dir / f"{stem}_final_agl.csv", agl.assign(side=side), args.max_view_points, rng)
            if case == "imu_off":
                primary_cache = data
            if case == "roll_+1_pitch_-1":
                no_imu = primary_cache
                _write_view(out_dir / f"scan_{scan}_before_imu.csv", pd.DataFrame(no_imu, columns=["X", "Y", "Z", "RSSI"]).assign(side=_side(no_imu[:, 0])), args.max_view_points, rng)

        del lidar, pico, fused

    pd.DataFrame(summaries).to_csv(out_dir / "stage_summary.csv", index=False)
    pd.DataFrame(retention).to_csv(out_dir / "retention_summary.csv", index=False)
    print(f"Wrote {out_dir / 'stage_summary.csv'}")
    print(f"Wrote {out_dir / 'retention_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
