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
        if b == "scipy":
            return b
        if b in {"pcl", "pclpy", "python_pcl"}:
            raise ValueError(f"Backend {b!r} requested but not implemented. Only 'scipy' is available.")
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


def _resolve_scalar_name(op_cfg: dict[str, Any]) -> str:
    return str(op_cfg.get("scalar") or op_cfg.get("field") or op_cfg.get("input_scalar") or "").strip()

def _require_scalar(df: pd.DataFrame, scalar: str, op_name: str) -> str:
    if not scalar:
        raise ValueError(f"{op_name} requires one of scalar/field/input_scalar")
    if scalar not in df.columns:
        raise ValueError(f"{op_name} scalar {scalar!r} not present. Available columns: {list(df.columns)}")
    return scalar

def _scalar_range_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> pd.DataFrame:
    field = _require_scalar(df, _resolve_scalar_name(op_cfg), "scalar_range_filter")
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
    size_m = float(
        op_cfg.get(
            "voxel_size_m",
            op_cfg.get("voxel_size", op_cfg.get("leaf_size", 0.05)),
        )
    )

    if size_m <= 0:
        raise ValueError(f"voxel size must be > 0; got {size_m}")

    if len(df) == 0:
        return 0

    # pipeline_core stores X/Y/Z in millimeters.
    # voxel_size_m is meters, so convert coordinates to meters.
    xyz_m = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False) / 1000.0

    idx = np.floor(xyz_m / size_m).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])


def _bilateral_scalar_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    field = _require_scalar(df, _resolve_scalar_name(op_cfg), "bilateral_scalar_filter")

    # Config values are in meters / scalar units.
    sigma_s = float(op_cfg.get("sigma_spatial", op_cfg.get("spatial_sigma_m", 0.03)))
    sigma_r = float(op_cfg.get("sigma_range", op_cfg.get("scalar_sigma", 2.5)))

    # PCL-style default: radius search at 2 * spatial sigma.
    radius = float(op_cfg.get("radius", op_cfg.get("radius_m", sigma_s * 2.0)))

    # PCL bilateral itself does not expose min/max neighbors, so default to no cap.
    min_neighbors = int(op_cfg.get("min_neighbors", 1))
    max_neighbors = int(op_cfg.get("max_neighbors", 0))  # 0 = no cap

    if sigma_s <= 0:
        raise ValueError(f"spatial sigma must be > 0; got {sigma_s}")
    if sigma_r <= 0:
        raise ValueError(f"scalar sigma must be > 0; got {sigma_r}")
    if radius <= 0:
        raise ValueError(f"radius must be > 0; got {radius}")

    if len(df) == 0:
        return df.copy(), field

    # pipeline_core stores X/Y/Z in millimeters.
    # Bilateral config uses meters, so convert coordinates to meters here.
    xyz_m = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False) / 1000.0
    vals = df[field].to_numpy(dtype=float, copy=False)

    tree = cKDTree(xyz_m)
    out_vals = vals.copy()

    spatial_denom = max(2.0 * sigma_s * sigma_s, 1e-12)
    scalar_denom = max(2.0 * sigma_r * sigma_r, 1e-12)

    for i, p in enumerate(xyz_m):
        nbr_idx = tree.query_ball_point(p, r=radius)

        if len(nbr_idx) < min_neighbors:
            continue

        nbr_idx = np.asarray(nbr_idx, dtype=int)

        # Optional cap, only if explicitly requested.
        if max_neighbors > 0 and nbr_idx.size > max_neighbors:
            d2_all = np.sum((xyz_m[nbr_idx] - p) ** 2, axis=1)
            keep_order = np.argsort(d2_all, kind="mergesort")[:max_neighbors]
            nbr_idx = nbr_idx[keep_order]

        d2 = np.sum((xyz_m[nbr_idx] - p) ** 2, axis=1)
        spatial_w = np.exp(-d2 / spatial_denom)

        scalar_d2 = (vals[nbr_idx] - vals[i]) ** 2
        scalar_w = np.exp(-scalar_d2 / scalar_denom)

        weights = spatial_w * scalar_w
        weight_sum = float(np.sum(weights))

        if weight_sum > 0:
            out_vals[i] = float(np.sum(weights * vals[nbr_idx]) / weight_sum)

    replace_scalar = bool(op_cfg.get("replace_scalar", True))
    output_scalar = op_cfg.get("output_scalar")

    out = df.copy()

    if output_scalar and not replace_scalar:
        used = str(output_scalar)
        out[used] = out_vals
    else:
        used = field
        out[field] = out_vals

    return out, used


def apply_pointcloud_ops(target, ops_config, *, default_backend=None, context=None):
    try:
        from .analysis_target import AnalysisTarget
    except ImportError:
        from analysis_target import AnalysisTarget

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
        "available_scalar_columns_before": [c for c in df.columns if c not in {"X","Y","Z"}],
        "points_before_ops": int(len(df)),
        "points_after_each_op": [],
        "points_after_ops": None,
        "backend_used": [],
        "operation_order": [],
        "scalar_fields_used": [],
    }
    traits = {}

    for op_cfg in ops:
        op_name = op_cfg.get("op", op_cfg.get("name", ""))
        op = str(op_name).strip().lower()
        if op_cfg.get("enabled", True) is False:
            continue
        if op not in _SUPPORTED_OPS:
            raise ValueError(f"Unsupported pointcloud op '{op}'")
        backend = resolver.resolve(op_cfg, legacy_backend=legacy_backend)
        diagnostics["operation_order"].append(op)
        diagnostics["backend_used"].append({"op": op, "backend": backend})

        if op == "scalar_range_filter":
            scalar = _resolve_scalar_name(op_cfg)
            diagnostics["scalar_fields_used"].append({"op": op, "scalar": scalar})
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
            scalar = _resolve_scalar_name(op_cfg)
            df, actual_scalar = _bilateral_scalar_filter(df, op_cfg)
            diagnostics["scalar_fields_used"].append({"op": op, "scalar": scalar, "output_scalar": actual_scalar})

        diagnostics["points_after_each_op"].append({"op": op, "points": int(len(df))})

    diagnostics["points_after_ops"] = int(len(df))
    diagnostics["available_scalar_columns_after"] = [c for c in df.columns if c not in {"X","Y","Z"}]
    if target_obj is None:
        return df, traits, diagnostics
    target_obj.current_points = df
    target_obj.traits.update(traits)
    target_obj.diagnostics["pointcloud_ops"] = diagnostics
    target_obj.op_history.extend(diagnostics["backend_used"])
    return target_obj
