from __future__ import annotations

import math
from typing import Any

import numpy as np

_FT_TO_M = 0.3048


def _unit_to_mm(value_u: float, dim_units: str) -> float:
    meters = float(value_u) if str(dim_units).lower() == "m" else float(value_u) * _FT_TO_M
    return meters * 1000.0


def apply_pointcloud_ops(data: np.ndarray, cfg) -> np.ndarray:
    ops = getattr(cfg, "pointcloud_ops", None) or []
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


def _op_bilateral_scalar(data: np.ndarray, cfg, op: dict[str, Any]) -> np.ndarray:
    try:
        from scipy.spatial import cKDTree
    except Exception as e:
        raise RuntimeError("bilateral_scalar requires scipy.spatial.cKDTree") from e

    scalar = str(op.get("scalar", "rssi_norm")).strip().lower()
    output_scalar = str(op.get("output_scalar", "rssi_bilateral")).strip().lower()
    spatial_sigma_mm = _unit_to_mm(float(op.get("spatial_sigma_u", 0.05)), cfg.dim_units)
    radius_mm = _unit_to_mm(float(op.get("radius_u", 0.15)), cfg.dim_units)
    scalar_sigma = float(op.get("scalar_sigma", 0.20))
    min_neighbors = int(op.get("min_neighbors", 3))

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

    for i in range(data.shape[0]):
        si = s[i]
        if not np.isfinite(si):
            out_s[i] = si
            continue
        idx = tree.query_ball_point(xyz[i], r=radius_mm)
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

    data[:, dst_col] = out_s.astype(np.float32)
    return data
