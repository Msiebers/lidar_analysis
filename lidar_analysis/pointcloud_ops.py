from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


@dataclass
class _BackendResolver:
    default_backend: str = "scipy"

    def resolve(self, op_cfg: dict[str, Any], legacy_backend: str | None = None) -> str:
        backend = op_cfg.get("backend") or legacy_backend or self.default_backend
        b = str(backend).strip().lower()
        if b in {"scipy", "pcl", "pclpy", "python_pcl"}:
            return b
        raise ValueError(f"Unsupported pointcloud backend '{backend}' for op={op_cfg.get('op')}")


_SUPPORTED_OPS = {
    "scalar_range_filter",
    "sor_filter",
    "voxel_volume",
    "voxel_grid",
    "voxel_count",
    "bilateral_scalar_filter",
}


def _as_df(points_df: pd.DataFrame | np.ndarray) -> pd.DataFrame:
    if isinstance(points_df, pd.DataFrame):
        return points_df.copy()
    arr = np.asarray(points_df)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError("points must be an NxM table with at least X,Y,Z columns")
    cols = ["X", "Y", "Z", "RSSI"] + [f"scalar_{i}" for i in range(max(0, arr.shape[1] - 4))]
    return pd.DataFrame(arr, columns=cols[: arr.shape[1]])


def _scalar_range_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> pd.DataFrame:
    field = op_cfg.get("field") or op_cfg.get("scalar") or "RSSI"
    if field not in df.columns:
        raise ValueError(f"scalar_range_filter field '{field}' not present")
    m = pd.Series(True, index=df.index)
    if op_cfg.get("min") is not None:
        m &= df[field] >= float(op_cfg["min"])
    if op_cfg.get("max") is not None:
        m &= df[field] <= float(op_cfg["max"])
    return df.loc[m].copy()


def _sor_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> pd.DataFrame:
    mean_k = int(op_cfg.get("mean_k", op_cfg.get("nb_neighbors", 5)))
    std_mul = float(op_cfg.get("stddev_mul_thresh", op_cfg.get("std_ratio", 2.0)))
    if len(df) <= 2 or mean_k < 1:
        return df.copy()
    xyz = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)
    k = min(mean_k + 1, len(df))
    dist, _ = cKDTree(xyz).query(xyz, k=k)
    # exclude self at [:,0]
    knn = dist[:, 1:] if dist.ndim > 1 else dist.reshape(-1, 1)
    mean_dist = np.mean(knn, axis=1)
    md_mean = float(np.mean(mean_dist))
    md_std = float(np.std(mean_dist))
    threshold = md_mean + std_mul * md_std
    keep = mean_dist <= threshold
    return df.loc[keep].copy()


def _voxel_count(df: pd.DataFrame, op_cfg: dict[str, Any]) -> int:
    size = float(op_cfg.get("voxel_size", op_cfg.get("leaf_size", op_cfg.get("voxel_size_m", 0.05))))
    if size <= 0 or len(df) == 0:
        return 0
    xyz = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)
    idx = np.floor(xyz / size).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])


def _bilateral_scalar_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> pd.DataFrame:
    # TODO: if pcl/pclpy backend is enabled in environment, map this to PCL bilateral on intensity.
    field = op_cfg.get("field") or op_cfg.get("scalar") or "RSSI"
    if field not in df.columns:
        raise ValueError(f"bilateral_scalar_filter field '{field}' not present")
    sigma_s = float(op_cfg.get("sigma_spatial", 0.03))
    sigma_r = float(op_cfg.get("sigma_range", 2.5))
    radius = float(op_cfg.get("radius", sigma_s * 2.0))
    xyz = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)
    vals = df[field].to_numpy(dtype=float, copy=False)
    if len(df) == 0:
        return df.copy()
    tree = cKDTree(xyz)
    out_vals = vals.copy()
    for i, p in enumerate(xyz):
        nbr_idx = tree.query_ball_point(p, r=radius)
        if not nbr_idx:
            continue
        nbr_idx = np.asarray(nbr_idx, dtype=int)
        d2 = np.sum((xyz[nbr_idx] - p) ** 2, axis=1)
        ds = np.exp(-d2 / max(2.0 * sigma_s * sigma_s, 1e-12))
        dr = np.exp(-((vals[nbr_idx] - vals[i]) ** 2) / max(2.0 * sigma_r * sigma_r, 1e-12))
        w = ds * dr
        wsum = float(np.sum(w))
        if wsum > 0:
            out_vals[i] = float(np.sum(w * vals[nbr_idx]) / wsum)
    out = df.copy()
    out[field] = out_vals
    return out


def apply_pointcloud_ops(target, ops_config, *, default_backend=None, context=None):
    from .analysis_target import AnalysisTarget

    if isinstance(target, AnalysisTarget):
        df = _as_df(target.current_points)
        target_obj = target
    else:
        # backward compatibility for internal helpers/tests
        df = _as_df(target)
        target_obj = None
    ops = ops_config or []
    resolver = _BackendResolver(default_backend=default_backend or "scipy")
    legacy_backend = None
    if isinstance(context, dict):
        legacy_backend = context.get("pcl_backend_name")

    diagnostics = {
        "points_before_ops": int(len(df)),
        "points_after_each_op": [],
        "points_after_ops": None,
        "backend_used": [],
        "operation_order": [],
        "scalar_fields_used": [],
    }
    traits = {}

    for op_cfg in ops:
        op = str(op_cfg.get("op", "")).strip().lower()
        if op not in _SUPPORTED_OPS:
            raise ValueError(f"Unsupported pointcloud op '{op}'")
        backend = resolver.resolve(op_cfg, legacy_backend=legacy_backend)
        diagnostics["operation_order"].append(op)
        diagnostics["backend_used"].append({"op": op, "backend": backend})

        if op == "scalar_range_filter":
            diagnostics["scalar_fields_used"].append(op_cfg.get("field") or op_cfg.get("scalar") or "RSSI")
            df = _scalar_range_filter(df, op_cfg)
        elif op == "sor_filter":
            df = _sor_filter(df, op_cfg)
        elif op in {"voxel_volume", "voxel_grid", "voxel_count"}:
            voxel_count = _voxel_count(df, op_cfg)
            traits["voxel_count"] = voxel_count
            diagnostics["voxel_count"] = voxel_count
            if bool(op_cfg.get("replace_with_centroids", False)):
                # behavior-preserving default: do not replace cloud unless explicitly requested.
                pass
        elif op == "bilateral_scalar_filter":
            diagnostics["scalar_fields_used"].append(op_cfg.get("field") or op_cfg.get("scalar") or "RSSI")
            df = _bilateral_scalar_filter(df, op_cfg)

        diagnostics["points_after_each_op"].append({"op": op, "points": int(len(df))})

    diagnostics["points_after_ops"] = int(len(df))
    if target_obj is None:
        return df, traits, diagnostics
    target_obj.current_points = df
    target_obj.traits.update(traits)
    target_obj.diagnostics["pointcloud_ops"] = diagnostics
    target_obj.op_history.extend(diagnostics["backend_used"])
    return target_obj
