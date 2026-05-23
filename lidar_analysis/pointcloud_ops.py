from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .topology import topology_stand_count


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
    "height_range_filter",
    "topology_trait",
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
    size = float(op_cfg.get("voxel_size", op_cfg.get("leaf_size", op_cfg.get("voxel_size_m", 0.05))))
    if size <= 0 or len(df) == 0:
        return 0
    xyz = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)
    idx = np.floor(xyz / size).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])


def _bilateral_scalar_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    field = _require_scalar(df, _resolve_scalar_name(op_cfg), "bilateral_scalar_filter")
    sigma_s = float(op_cfg.get("sigma_spatial", op_cfg.get("spatial_sigma_m", 0.03)))
    sigma_r = float(op_cfg.get("sigma_range", op_cfg.get("scalar_sigma", 2.5)))
    radius = float(op_cfg.get("radius", op_cfg.get("radius_m", sigma_s * 2.0)))
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
    replace_scalar = bool(op_cfg.get("replace_scalar", True))
    output_scalar = op_cfg.get("output_scalar")
    out = df.copy()
    if output_scalar and (not replace_scalar):
        out[str(output_scalar)] = out_vals
        used = str(output_scalar)
    else:
        out[field] = out_vals
        used = field
    return out, used




def _axis_col(axis: str) -> str:
    a = str(axis or "Y").strip().upper()
    if a not in {"X","Y","Z"}:
        raise ValueError(f"height_range_filter axis must be X/Y/Z; got {axis!r}")
    return a

def _height_range_filter(df: pd.DataFrame, op_cfg: dict[str, Any], context: dict[str, Any] | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    axis = _axis_col(op_cfg.get("axis", "Y"))
    min_m = op_cfg.get("min_m")
    max_m = op_cfg.get("max_m")
    if min_m is None and op_cfg.get("min_u") is not None:
        dim_units = str((context or {}).get("dim_units", "m")).lower()
        scale = 1000.0 if dim_units == "m" else 304.8
        min_mm = float(op_cfg.get("min_u")) * scale
    else:
        min_mm = None if min_m is None else float(min_m) * 1000.0
    if max_m is None and op_cfg.get("max_u") is not None:
        dim_units = str((context or {}).get("dim_units", "m")).lower()
        scale = 1000.0 if dim_units == "m" else 304.8
        max_mm = float(op_cfg.get("max_u")) * scale
    else:
        max_mm = None if max_m is None else float(max_m) * 1000.0

    mask = pd.Series(True, index=df.index)
    if min_mm is not None:
        mask &= df[axis] >= min_mm
    if max_mm is not None:
        mask &= df[axis] <= max_mm
    out = df.loc[mask].copy()
    diag = {"axis": axis, "min_m": min_m, "max_m": max_m, "points_before": int(len(df)), "points_after": int(len(out))}
    return out, diag

def _topology_input_xyz_m(df: pd.DataFrame) -> tuple[np.ndarray, str, str | None]:
    x_m = df["X"].to_numpy(dtype=float, copy=False) / 1000.0
    y_m = df["Y"].to_numpy(dtype=float, copy=False) / 1000.0
    for zcol in ("travel_z_m", "scan_position_m", "encoder_z_m"):
        if zcol in df.columns:
            z_m = df[zcol].to_numpy(dtype=float, copy=False)
            return np.column_stack([x_m, y_m, z_m]), zcol, None
    z_m = df["Z"].to_numpy(dtype=float, copy=False) / 1000.0
    return np.column_stack([x_m, y_m, z_m]), "reconstructed_Z", "topology_trait used reconstructed Z fallback (no travel_z_m/scan_position_m/encoder_z_m column found)"


def _topology_trait(df: pd.DataFrame, op_cfg: dict[str, Any], target_obj) -> tuple[dict[str, Any], dict[str, Any]]:
    split = bool(op_cfg.get("split_sides_for_single_plot", False))
    min_persistence = float(op_cfg.get("min_persistence", 0.35))
    xyz_m, z_source, warn = _topology_input_xyz_m(df)

    topo_whole = topology_stand_count(xyz_m, min_persistence=min_persistence)["count"] if len(df) else 0.0
    out = {"topo_count": float(topo_whole), "topo_count_whole": float(topo_whole), "topo_count_left": float("nan"), "topo_count_right": float("nan")}

    is_whole_plot = str(getattr(target_obj, "target_type", "")).lower() == "plot" and getattr(target_obj, "row", None) is None
    side_split_applied = bool(split and is_whole_plot)
    if side_split_applied:
        left = df[df["X"] >= 0]
        right = df[df["X"] < 0]
        if len(left):
            out["topo_count_left"] = float(topology_stand_count(_topology_input_xyz_m(left)[0], min_persistence=min_persistence)["count"])
        else:
            out["topo_count_left"] = 0.0
        if len(right):
            out["topo_count_right"] = float(topology_stand_count(_topology_input_xyz_m(right)[0], min_persistence=min_persistence)["count"])
        else:
            out["topo_count_right"] = 0.0

    diag = {
        "topology_input_points": int(len(df)),
        "topology_z_source": z_source,
        "topology_side_split_applied": side_split_applied,
        "topology_results": dict(out),
    }
    if warn:
        diag["warning"] = warn
    return out, diag
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
        elif op == "height_range_filter":
            df, hdiag = _height_range_filter(df, op_cfg, context if isinstance(context, dict) else None)
            diagnostics.setdefault("op_diagnostics", []).append({"op": op, **hdiag})
        elif op == "topology_trait":
            if target_obj is None:
                raise ValueError("topology_trait requires AnalysisTarget input")
            topo, tdiag = _topology_trait(df, op_cfg, target_obj)
            traits.update(topo)
            diagnostics.setdefault("op_diagnostics", []).append({"op": op, **tdiag})
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
