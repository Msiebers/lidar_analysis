from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, cKDTree
try:
    from .topology.stand_count import topology_stand_count
except ImportError:
    from topology.stand_count import topology_stand_count


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
    "slice_structure_trait",
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


def _height_range_filter(df: pd.DataFrame, op_cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    axis = str(op_cfg.get("axis", "Y")).strip().upper() or "Y"
    if axis not in {"X", "Y", "Z"}:
        raise ValueError(f"height_range_filter axis must be one of X/Y/Z; got {axis!r}")

    if axis not in df.columns:
        raise ValueError(f"height_range_filter axis {axis!r} not present. Available columns: {list(df.columns)}")

    min_m = op_cfg.get("min_m")
    max_m = op_cfg.get("max_m")
    min_mm = None if min_m is None else float(min_m) * 1000.0
    max_mm = None if max_m is None else float(max_m) * 1000.0

    m = pd.Series(True, index=df.index)
    if min_mm is not None:
        m &= df[axis] >= min_mm
    if max_mm is not None:
        m &= df[axis] <= max_mm

    out = df.loc[m].copy()
    diag = {
        "axis": axis,
        "min_m": min_m,
        "max_m": max_m,
        "points_before": int(len(df)),
        "points_after": int(len(out)),
    }
    return out, diag


def _topology_trait(df: pd.DataFrame, op_cfg: dict[str, Any], target_obj) -> dict[str, Any]:
    def _extract_count_and_points(res: Any) -> tuple[float, list[Any]]:
        if isinstance(res, dict):
            return float(res.get("count", float("nan"))), list(res.get("points", []) or [])
        if isinstance(res, tuple):
            count = float(res[0]) if len(res) > 0 else float("nan")
            pts = list(res[1]) if len(res) > 1 and res[1] is not None else []
            return count, pts
        return float("nan"), []

    min_persistence = float(op_cfg.get("min_persistence", 0.35))
    split_sides = bool(op_cfg.get("split_sides_for_single_plot", False))
    pos_label = str(op_cfg.get("additional_scan_positive_side_label", "right")).strip().lower() or "right"
    neg_label = str(op_cfg.get("additional_scan_negative_side_label", "left")).strip().lower() or "left"

    z_source = None
    warning = None
    for col in ("travel_z_m", "scan_position_m", "encoder_z_m"):
        if col in df.columns:
            z_source = col
            z_vals_m = df[col].to_numpy(dtype=float, copy=False)
            break
    if z_source is None:
        z_source = "Z_mm_fallback"
        z_vals_m = df["Z"].to_numpy(dtype=float, copy=False) / 1000.0
        warning = "topology_trait used reconstructed Z fallback (Z/1000.0) because no travel/scan-position column was present"

    topo_df = pd.DataFrame({
        "x": df["X"].to_numpy(dtype=float, copy=False) / 1000.0,
        "y": df["Y"].to_numpy(dtype=float, copy=False) / 1000.0,
        "z": z_vals_m,
    })

    z_bin_m = float(op_cfg.get("z_bin_m", 0.05))

    unique_z_before = int(topo_df["z"].nunique()) if "z" in topo_df.columns else int(0)
    unique_z_after = unique_z_before
    if z_bin_m > 0 and "z" in topo_df.columns:
        unique_z_before = int(topo_df["z"].nunique())
        topo_df = topo_df.copy()
        topo_df["z"] = np.floor(topo_df["z"] / z_bin_m) * z_bin_m
        unique_z_after = int(topo_df["z"].nunique())

        print(
            f"[TOPO_DEBUG] target={getattr(target_obj, 'target_id', '<unknown>')} "
            f"z_bin_m={z_bin_m} unique_z_before={unique_z_before} "
            f"unique_z_after={unique_z_after}"
        )

    topo_res_whole = topology_stand_count(topo_df, min_persistence=min_persistence)
    topo_count_whole, pers_whole = _extract_count_and_points(topo_res_whole)
    topo_raw_whole = float(topo_res_whole.get("count_raw", float("nan"))) if isinstance(topo_res_whole, dict) else float("nan")
    traits = {
        "topo_count": float("nan"),
        "topo_count_whole": topo_count_whole,
        "topo_count_left": float("nan"),
        "topo_count_right": float("nan"),
        "topo_left_count": float("nan"),
        "topo_right_count": float("nan"),
        "topo_left_per_m": float("nan"),
        "topo_right_per_m": float("nan"),
        "topo_avg_per_m": float("nan"),
    }
    object_points_xyz: list[tuple[float, float, float]] = []

    side_split_applied = False
    ignore_left = False
    ignore_right = False
    scan_id = str(getattr(target_obj, "scan_id", "") or "")
    row_spec = scan_id.split("_", 1)[0]
    if "&" in row_spec:
        left_row, right_row = [s.strip() for s in row_spec.split("&", 1)]
        ignore_left = left_row == "0"
        ignore_right = right_row == "0"

    if split_sides:
        side_split_applied = True
        pos_df = topo_df.loc[topo_df["x"] >= 0.0]
        neg_df = topo_df.loc[topo_df["x"] < 0.0]

        side_map = {
            pos_label: pos_df,
            neg_label: neg_df,
        }
        if not ignore_left and "left" in side_map:
            left_res = topology_stand_count(side_map["left"], min_persistence=min_persistence)
            left_per_m, left_pts = _extract_count_and_points(left_res)
            left_raw = float(left_res.get("count_raw", float("nan"))) if isinstance(left_res, dict) else float("nan")
            traits["topo_count_left"] = left_per_m
            traits["topo_left_per_m"] = left_per_m
            traits["topo_left_count"] = left_raw
            object_points_xyz.extend([(float(x), 0.0, float(z)) for (x, z) in left_pts])
        if not ignore_right and "right" in side_map:
            right_res = topology_stand_count(side_map["right"], min_persistence=min_persistence)
            right_per_m, right_pts = _extract_count_and_points(right_res)
            right_raw = float(right_res.get("count_raw", float("nan"))) if isinstance(right_res, dict) else float("nan")
            traits["topo_count_right"] = right_per_m
            traits["topo_right_per_m"] = right_per_m
            traits["topo_right_count"] = right_raw
            object_points_xyz.extend([(float(x), 0.0, float(z)) for (x, z) in right_pts])

    side_vals = np.array([traits["topo_count_left"], traits["topo_count_right"]], dtype=float)
    if np.isfinite(side_vals).any():
        traits["topo_count"] = float(np.nanmean(side_vals))
        traits["topo_avg_per_m"] = traits["topo_count"]
    else:
        traits["topo_count"] = float("nan")
        traits["topo_avg_per_m"] = float("nan")

    return {
        "traits": traits,
        "diagnostic": {
            "input_points": int(len(df)),
            "z_source": z_source,
            "side_split_applied": side_split_applied,
            "topology_side_split_applied": side_split_applied,
            "topology_positive_side_label": pos_label,
            "topology_negative_side_label": neg_label,
            "topology_left_count_per_m": traits["topo_count_left"],
            "topology_right_count_per_m": traits["topo_count_right"],
            "topology_left_count": traits["topo_left_count"],
            "topology_right_count": traits["topo_right_count"],
            "topology_left_per_m": traits["topo_left_per_m"],
            "topology_right_per_m": traits["topo_right_per_m"],
            "topology_count_mean_per_m": traits["topo_count"],
            "z_bin_m": z_bin_m,
            "unique_z_before": unique_z_before,
            "unique_z_after": unique_z_after,
            "min_persistence": min_persistence,
            "result": traits,
            "warning": warning,
            "persistence_points_whole": pers_whole,
            "topology_raw_count_whole": topo_raw_whole,
            "topology_object_points_xyz": object_points_xyz,
            "write_topology_objects": bool(op_cfg.get("write_topology_objects", False)),
        },
    }



def _slice_structure_trait(df: pd.DataFrame, op_cfg: dict[str, Any]) -> dict[str, float]:
    if len(df) == 0:
        return {
            "stacked_hull_volume_m3": float("nan"),
            "max_spread_m": float("nan"),
            "spread_at_50_m": float("nan"),
        }

    slice_height_m = float(op_cfg.get("slice_height_m", op_cfg.get("dz_m", 0.05)))
    min_points_per_slice = int(op_cfg.get("min_points_per_slice", 3))
    if slice_height_m <= 0:
        raise ValueError(f"slice_structure_trait slice_height_m must be > 0; got {slice_height_m}")

    xyz_m = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False) / 1000.0
    x_m = xyz_m[:, 0]
    y_m = xyz_m[:, 1]
    z_m = xyz_m[:, 2]

    y0 = float(np.min(y_m))
    y1 = float(np.max(y_m))
    if not np.isfinite(y0) or not np.isfinite(y1):
        return {
            "stacked_hull_volume_m3": float("nan"),
            "max_spread_m": float("nan"),
            "spread_at_50_m": float("nan"),
        }

    n_slices = max(1, int(np.ceil((y1 - y0) / slice_height_m)))
    edges = y0 + np.arange(n_slices + 1, dtype=float) * slice_height_m
    if edges[-1] < y1:
        edges = np.append(edges, y1)

    stacked_hull_volume_m3 = 0.0
    max_spread_m = float("nan")
    spread_at_50_m = float("nan")
    target_y = y0 + 0.5 * (y1 - y0)
    target_dist = float("inf")

    for i in range(len(edges) - 1):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == len(edges) - 2:
            m = (y_m >= lo) & (y_m <= hi)
        else:
            m = (y_m >= lo) & (y_m < hi)
        if int(np.count_nonzero(m)) < min_points_per_slice:
            continue

        footprint = np.column_stack((x_m[m], z_m[m]))
        if footprint.shape[0] < 3:
            continue

        try:
            hull = ConvexHull(footprint)
        except Exception:
            continue

        area_m2 = float(hull.volume)
        thickness_m = hi - lo
        if thickness_m > 0:
            stacked_hull_volume_m3 += area_m2 * thickness_m

        hull_pts = footprint[hull.vertices]
        d = hull_pts[:, None, :] - hull_pts[None, :, :]
        diam = float(np.sqrt(np.sum(d * d, axis=2)).max()) if hull_pts.shape[0] > 1 else 0.0

        if not np.isfinite(max_spread_m) or diam > max_spread_m:
            max_spread_m = diam

        yc = 0.5 * (lo + hi)
        dist = abs(yc - target_y)
        if dist < target_dist:
            target_dist = dist
            spread_at_50_m = diam

    return {
        "stacked_hull_volume_m3": float(stacked_hull_volume_m3),
        "max_spread_m": float(max_spread_m),
        "spread_at_50_m": float(spread_at_50_m),
    }

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
        elif op == "height_range_filter":
            df, hr_diag = _height_range_filter(df, op_cfg)
            diagnostics.setdefault("height_range_filters", []).append(hr_diag)
        elif op == "slice_structure_trait":
            traits.update(_slice_structure_trait(df, op_cfg))
        elif op == "topology_trait":
            if target_obj is None:
                raise ValueError("topology_trait requires an AnalysisTarget")
            topo_cfg = dict(op_cfg)
            if isinstance(context, dict):
                if "additional_scan_positive_side_label" in context and "additional_scan_positive_side_label" not in topo_cfg:
                    topo_cfg["additional_scan_positive_side_label"] = context["additional_scan_positive_side_label"]
                if "additional_scan_negative_side_label" in context and "additional_scan_negative_side_label" not in topo_cfg:
                    topo_cfg["additional_scan_negative_side_label"] = context["additional_scan_negative_side_label"]
            topo_out = _topology_trait(df, topo_cfg, target_obj)
            traits.update(topo_out["traits"])
            diagnostics.setdefault("topology_trait", []).append(topo_out["diagnostic"])

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
