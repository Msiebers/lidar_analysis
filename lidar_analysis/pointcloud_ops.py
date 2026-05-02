from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
import tempfile
import csv
from typing import Any

import numpy as np

_FT_TO_M = 0.3048


def _unit_to_mm(value_u: float, dim_units: str) -> float:
    meters = float(value_u) if str(dim_units).lower() == "m" else float(value_u) * _FT_TO_M
    return meters * 1000.0


def apply_pointcloud_ops(data: np.ndarray, cfg) -> np.ndarray:
    ops = getattr(cfg, "pointcloud_ops", None) or []
    pcl_backend = getattr(cfg, "pcl_backend", None) or {}
    if bool(pcl_backend.get("enabled", False)) and any(bool(op.get("enabled", True)) and str(op.get("backend", "python")).lower() == "pcl" for op in ops if isinstance(op, dict)):
        return _apply_pointcloud_ops_pcl(data, cfg, ops, pcl_backend)

    out = np.array(data, copy=True)
    for op in ops:
        if not isinstance(op, dict):
            continue
        name = str(op.get("name", "")).strip().lower()
        enabled = bool(op.get("enabled", True))
        if not enabled:
            continue
        before_n = int(out.shape[0])
        if name == "bilateral_scalar":
            out = _op_bilateral_scalar(out, cfg, op)
        elif name == "":
            continue
        else:
            raise ValueError(f"Unknown pointcloud operation: {name!r}")
        print(f"[PC_OP] name={name} before_points={before_n} after_points={int(out.shape[0])}")
    return out


def run_pcl_batch_on_csvs(csv_paths: list[str], cfg) -> list[str]:
    ops = getattr(cfg, "pointcloud_ops", None) or []
    pcl_backend = getattr(cfg, "pcl_backend", None) or {}
    if not bool(pcl_backend.get("enabled", False)):
        return []
    enabled_pcl_ops = [op for op in ops if isinstance(op, dict) and bool(op.get("enabled", True)) and str(op.get("backend", "python")).lower() == "pcl"]
    if not enabled_pcl_ops or not csv_paths:
        return []

    exe = pcl_backend.get("executable") or "pcl_pointcloud_ops_batch"
    exe_path = shutil.which(exe) if not os.path.isabs(str(exe)) else str(exe)
    if not exe_path or not os.path.exists(exe_path):
        if bool(pcl_backend.get("fail_if_missing", True)):
            raise RuntimeError("PCL backend executable not found. Build with: cmake -S cpp_ops -B cpp_ops/build && cmake --build cpp_ops/build -j")
        return []

    work_dir = pcl_backend.get("work_dir") or tempfile.mkdtemp(prefix="pcl_ops_batch_")
    os.makedirs(work_dir, exist_ok=True)
    ops_json_path = os.path.join(work_dir, "ops.json")
    manifest = os.path.join(work_dir, "manifest.csv")
    import json
    with open(ops_json_path, "w", encoding="utf-8") as jf:
        json.dump({"ops": enabled_pcl_ops}, jf)

    out_paths: list[str] = []
    with open(manifest, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_id", "input_csv", "output_csv", "ops_config_path"])
        for i, p in enumerate(csv_paths):
            in_p = os.path.abspath(p)
            out_dir = os.path.join(os.path.dirname(os.path.dirname(in_p)), "pointclouds_pcl")
            os.makedirs(out_dir, exist_ok=True)
            out_p = os.path.join(out_dir, os.path.basename(in_p))
            w.writerow([f"target_{i}", in_p, out_p, os.path.abspath(ops_json_path)])
            out_paths.append(out_p)

    proc = subprocess.run([exe_path, manifest], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"PCL backend failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    if not bool(pcl_backend.get("keep_intermediate", True)) and "pcl_ops_batch_" in os.path.basename(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    return out_paths


def _apply_pointcloud_ops_pcl(data: np.ndarray, cfg, ops, pcl_backend: dict[str, Any]) -> np.ndarray:
    exe = pcl_backend.get("executable") or "pcl_pointcloud_ops_batch"
    exe_path = shutil.which(exe) if not os.path.isabs(str(exe)) else str(exe)
    if not exe_path or not os.path.exists(exe_path):
        if bool(pcl_backend.get("fail_if_missing", True)):
            raise RuntimeError(
                "PCL backend executable not found. Build with: cmake -S cpp_ops -B cpp_ops/build && cmake --build cpp_ops/build -j"
            )
        print("[pointcloud_ops][WARN] PCL backend missing; skipping ops.")
        return data

    work_dir = pcl_backend.get("work_dir") or tempfile.mkdtemp(prefix="pcl_ops_")
    os.makedirs(work_dir, exist_ok=True)
    out_root = os.path.join(work_dir, "pointclouds_pcl")
    os.makedirs(out_root, exist_ok=True)
    in_csv = os.path.join(work_dir, "input.csv")
    out_csv = os.path.join(out_root, "output.csv")
    manifest = os.path.join(work_dir, "manifest.csv")
    ops_json_path = os.path.join(work_dir, "ops.json")

    cols = ["X", "Y", "Z", "RSSI"]
    if data.shape[1] >= 5:
        cols.append("rssi_norm")
    if data.shape[1] >= 6:
        cols.append("rssi_bilateral")
    with open(in_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in data[:, : len(cols)]:
            w.writerow(r.tolist())
    with open(manifest, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_id", "input_csv", "output_csv", "ops_config_path"])
        import json
        with open(ops_json_path, "w", encoding="utf-8") as jf:
            json.dump({"ops": ops}, jf)
        w.writerow(["target_0", in_csv, out_csv, ops_json_path])

    proc = subprocess.run([exe_path, manifest], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"PCL backend failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    out_rows = []
    with open(out_csv, "r", newline="") as f:
        rdr = csv.DictReader(f)
        out_cols = rdr.fieldnames or []
        for row in rdr:
            out_rows.append([float(row[c]) if row[c] != "" else np.nan for c in out_cols])
    out = np.asarray(out_rows, dtype=np.float32)
    if not bool(pcl_backend.get("keep_intermediate", True)) and "pcl_ops_" in os.path.basename(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    return out


def _op_bilateral_scalar(data: np.ndarray, cfg, op: dict[str, Any]) -> np.ndarray:
    try:
        from scipy.spatial import cKDTree
    except Exception as e:
        raise RuntimeError("bilateral_scalar requires scipy.spatial.cKDTree") from e

    scalar = str(op.get("scalar", "rssi_norm")).strip().lower()
    output_scalar = str(op.get("output_scalar", "rssi_bilateral")).strip().lower()
    spatial_sigma_mm = _unit_to_mm(float(op.get("spatial_sigma_u", 0.05)), cfg.dim_units)
    radius_u = op.get("radius_u", None)
    if radius_u is None:
        radius_mm = 3.0 * spatial_sigma_mm
    else:
        radius_mm = _unit_to_mm(float(radius_u), cfg.dim_units)
    scalar_sigma = float(op.get("scalar_sigma", 0.20))
    min_neighbors = int(op.get("min_neighbors", 3))
    max_neighbors = int(op.get("max_neighbors", 64))
    max_points = op.get("max_points", None)
    if max_points is not None and data.shape[0] > int(max_points):
        raise RuntimeError(
            f"bilateral_scalar cloud has {data.shape[0]} points which exceeds max_points={int(max_points)}"
        )
    if data.shape[0] > 500_000:
        print(
            f"[pointcloud_ops][WARN] bilateral_scalar on {data.shape[0]} points may be slow; "
            "consider smaller radius_u or max_neighbors."
        )
    print(
        f"[pointcloud_ops] bilateral_scalar radius_mm={radius_mm:.3f} spatial_sigma_mm={spatial_sigma_mm:.3f} "
        f"scalar_sigma={scalar_sigma} min_neighbors={min_neighbors} max_neighbors={max_neighbors}"
    )

    scalar_map = {"rssi": 3, "rssi_norm": 4, "rssi_bilateral": 5}
    if scalar not in scalar_map:
        raise ValueError(f"bilateral_scalar unknown scalar={scalar!r}")
    src_col = scalar_map[scalar]
    if data.shape[1] <= src_col:
        raise ValueError(f"bilateral_scalar missing source scalar column {scalar!r}")

    if output_scalar != "rssi_bilateral":
        raise ValueError("Only output_scalar='rssi_bilateral' is supported in this checkpoint")
    dst_col = 5
    if data.shape[1] <= dst_col:
        data = np.column_stack([data, np.full((data.shape[0], 1), np.nan, dtype=np.float32)])

    xyz = data[:, :3].astype(np.float64, copy=False)
    s = data[:, src_col].astype(np.float64, copy=False)
    out_s = data[:, dst_col].astype(np.float64, copy=True)
    tree = cKDTree(xyz)

    last_log = time.time()
    for i in range(data.shape[0]):
        si = s[i]
        if not np.isfinite(si):
            out_s[i] = si
            continue
        idx = tree.query_ball_point(xyz[i], r=radius_mm)
        if len(idx) > max_neighbors:
            dsel = np.linalg.norm(xyz[np.asarray(idx, dtype=np.int64)] - xyz[i], axis=1)
            take = np.argsort(dsel)[:max_neighbors]
            idx = list(np.asarray(idx, dtype=np.int64)[take])
        if len(idx) < min_neighbors:
            out_s[i] = si
            continue
        idx = np.array(idx, dtype=np.int64)
        sj = s[idx]
        valid = np.isfinite(sj)
        if int(np.sum(valid)) < min_neighbors:
            out_s[i] = si
            continue
        idx = idx[valid]
        sj = sj[valid]
        d = np.linalg.norm(xyz[idx] - xyz[i], axis=1)
        sw = np.exp(-0.5 * (d / max(spatial_sigma_mm, 1e-9)) ** 2)
        rw = np.exp(-0.5 * (((si - sj) / max(scalar_sigma, 1e-9)) ** 2))
        w = sw * rw
        denom = np.sum(w)
        out_s[i] = float(np.sum(w * sj) / denom) if denom > 0 else si
        if (i + 1) % 100_000 == 0 or (time.time() - last_log) > 3.0:
            print(f"[pointcloud_ops] bilateral_scalar {i + 1}/{data.shape[0]} points")
            last_log = time.time()

    data[:, dst_col] = out_s.astype(np.float32)
    return data
