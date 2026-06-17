from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
try:
    from .topology.stand_count import topology_stand_count
except ImportError:
    from topology.stand_count import topology_stand_count
try:
    from scipy.spatial import ConvexHull, QhullError
except Exception:
    ConvexHull = None
    QhullError = Exception


def _resolve_backend(op_cfg: dict[str, Any], default_backend: str = "scipy") -> str:
    backend = op_cfg.get("backend") or default_backend
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

def op_enabled(cfg, name: str) -> bool:
    for op in getattr(cfg, "pointcloud_ops", []) or []:
        op_name = str(op.get("name", op.get("op", ""))).strip().lower()
        if op_name == name and op.get("enabled", True) is not False:
            return True
    return False

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

# The whole-cloud persistence pass only feeds the *_whole diagnostics.
    # When sides are split we get our actual counts from the per-side passes,
    # so the whole pass is redundant work. Skip it only when explicitly told
    # to, so default behavior (and the *_whole diagnostic keys) is unchanged.
    skip_whole = split_sides and bool(op_cfg.get("skip_whole_when_split", False)) \
        and not bool(op_cfg.get("write_topology_objects", False))

    if skip_whole:
        topo_count_whole, pers_whole, topo_raw_whole = float("nan"), [], float("nan")
    else:
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


def _voxel_count(df: pd.DataFrame, op_cfg: dict[str, Any]) -> int:
    if op_cfg.get("voxel_size_m") is not None:
        size_m = float(op_cfg["voxel_size_m"])
    elif op_cfg.get("voxel_size") is not None:
        size_m = float(op_cfg["voxel_size"]) / 1000.0
    else:
        size_m = float(op_cfg.get("leaf_size", 0.05))

    if size_m <= 0:
        raise ValueError(f"voxel size must be > 0; got {size_m}")

    if len(df) == 0:
        return 0

    # pipeline_core stores X/Y/Z in millimeters; public voxel_size_m is meters.
    # Legacy voxel_size follows raw point units, so it was converted above.
    xyz_m = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False) / 1000.0

    idx = np.floor(xyz_m / size_m).astype(np.int64)
    return int(np.unique(idx, axis=0).shape[0])

def _sor_filter(df: pd.DataFrame, op_cfg) -> pd.DataFrame:
    mean_k = int(op_cfg.get("mean_k", op_cfg.get("nb_neighbors", 5)))
    std_mul = float(op_cfg.get("stddev_mul_thresh", op_cfg.get("std_ratio", 2.0)))

    if len(df) <= 2 or mean_k < 1:
        return df.copy()

    xyz = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)

    finite = np.isfinite(xyz).all(axis=1)
    if not finite.all():
        work = df.loc[finite].copy()
        if len(work) <= 2:
            return work
        xyz = work[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False)
    else:
        work = df

    k = min(mean_k + 1, len(work))

    tree = cKDTree(xyz, balanced_tree=False, compact_nodes=False)
    dist, _ = tree.query(xyz, k=k, workers=-1)

    knn = dist[:, 1:] if dist.ndim > 1 else dist.reshape(-1, 1)
    mean_dist = np.mean(knn, axis=1)

    threshold = float(np.mean(mean_dist)) + std_mul * float(np.std(mean_dist))
    keep = mean_dist <= threshold

    return work.loc[keep].copy()


def _bilateral_scalar_filter(df: pd.DataFrame, op_cfg):
    field = _require_scalar(
        df,
        _resolve_scalar_name(op_cfg),
        "bilateral_scalar_filter",
    )

    sigma_s = float(op_cfg.get("sigma_spatial", op_cfg.get("spatial_sigma_m", 0.03)))
    sigma_r = float(op_cfg.get("sigma_range", op_cfg.get("scalar_sigma", 2.5)))
    radius = float(op_cfg.get("radius", op_cfg.get("radius_m", sigma_s * 2.0)))
    min_neighbors = int(op_cfg.get("min_neighbors", 1))
    max_neighbors = int(op_cfg.get("max_neighbors", 0))

    if sigma_s <= 0 or sigma_r <= 0 or radius <= 0:
        raise ValueError("bilateral_scalar_filter sigmas and radius must be > 0")

    if len(df) == 0:
        return df.copy(), field

    xyz_m = df[["X", "Y", "Z"]].to_numpy(dtype=float, copy=False) / 1000.0
    vals = df[field].to_numpy(dtype=float, copy=False)

    finite = np.isfinite(xyz_m).all(axis=1) & np.isfinite(vals)
    if not finite.all():
        out = df.copy()
        used = str(op_cfg.get("output_scalar") or field)

        if bool(op_cfg.get("replace_scalar", True)):
            used = field
            out[field] = vals
        else:
            out[used] = vals

        work_idx = np.where(finite)[0]
        if work_idx.size == 0:
            return out, used

        xyz_work = xyz_m[work_idx]
        vals_work = vals[work_idx]
    else:
        out = df.copy()
        work_idx = np.arange(len(df))
        xyz_work = xyz_m
        vals_work = vals

    tree = cKDTree(xyz_work, balanced_tree=False, compact_nodes=False)
    all_nbrs = tree.query_ball_point(xyz_work, r=radius, workers=-1)

    out_vals_work = vals_work.copy()

    spatial_denom = max(2.0 * sigma_s * sigma_s, 1e-12)
    scalar_denom = max(2.0 * sigma_r * sigma_r, 1e-12)

    for i, nbr_idx in enumerate(all_nbrs):
        if len(nbr_idx) < min_neighbors:
            continue

        nbr_idx = np.asarray(nbr_idx, dtype=int)

        if max_neighbors > 0 and nbr_idx.size > max_neighbors:
            d2_all = np.sum((xyz_work[nbr_idx] - xyz_work[i]) ** 2, axis=1)
            keep_order = np.argsort(d2_all, kind="mergesort")[:max_neighbors]
            nbr_idx = nbr_idx[keep_order]

        d2 = np.sum((xyz_work[nbr_idx] - xyz_work[i]) ** 2, axis=1)

        spatial_w = np.exp(-d2 / spatial_denom)
        scalar_w = np.exp(-((vals_work[nbr_idx] - vals_work[i]) ** 2) / scalar_denom)

        weights = spatial_w * scalar_w
        wsum = float(np.sum(weights))

        if wsum > 0:
            out_vals_work[i] = float(np.sum(weights * vals_work[nbr_idx]) / wsum)

    replace_scalar = bool(op_cfg.get("replace_scalar", True))
    output_scalar = op_cfg.get("output_scalar")

    full_out_vals = vals.copy()
    full_out_vals[work_idx] = out_vals_work

    if output_scalar and not replace_scalar:
        used = str(output_scalar)
        out[used] = full_out_vals
    else:
        used = field
        out[field] = full_out_vals

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
    backend_default = default_backend or (
        context.get("pcl_backend_name") if isinstance(context, dict) else None
    ) or "scipy"

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
        backend = _resolve_backend(op_cfg, backend_default)
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
            slice_traits, slice_diag = _compute_slice_structure_traits(
                df,
                slice_height_m=float(op_cfg.get("slice_height_m", 0.05)),
                height_axis=str(op_cfg.get("height_axis", "Y")),
                spread_axis=str(op_cfg.get("spread_axis", "X")),
                length_axis=str(op_cfg.get("length_axis", "Z")),
                percentile_height=float(op_cfg.get("percentile_height", 50.0)),
                min_points_per_slice=int(op_cfg.get("min_points_per_slice", 5)),
                clump_grid_m=float(op_cfg.get("clump_grid_m", 0.05)),
                clump_connectivity=int(op_cfg.get("clump_connectivity", 8)),
            )
            traits.update(slice_traits)
            diagnostics.setdefault("slice_structure_trait", []).append(slice_diag)

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

def _axis_name_to_col(axis: str) -> str:
    axis = str(axis).strip().upper()
    if axis not in ("X", "Y", "Z"):
        raise ValueError(f"axis must be one of X, Y, Z; got {axis!r}")
    return axis


def _convex_hull_area_2d(points_2d: np.ndarray) -> float:
    """
    Return 2D convex hull area.

    In scipy ConvexHull, `.volume` is area for 2D hulls.
    Input points are expected to be in metres, so output is square metres.
    """
    if points_2d.shape[0] < 3:
        return 0.0

    if ConvexHull is None:
        return float("nan")

    pts = np.unique(points_2d.astype(float), axis=0)
    if pts.shape[0] < 3:
        return 0.0

    try:
        hull = ConvexHull(pts)
        return float(hull.volume)
    except QhullError:
        return 0.0
    except Exception:
        return float("nan")


def _footprint_diameter_2d(points_2d: np.ndarray) -> float:
    """
    Return the maximum 2D distance between points in a height slice.

    This is the X/Z footprint diameter when spread_axis=X and length_axis=Z.
    It uses hull vertices when possible because the maximum distance must
    occur on the convex hull.

    Input points are expected to be in metres, so output is metres.
    """
    if points_2d.shape[0] < 2:
        return float("nan")

    pts = np.unique(points_2d.astype(float), axis=0)
    if pts.shape[0] < 2:
        return float("nan")

    if ConvexHull is not None and pts.shape[0] >= 3:
        try:
            hull = ConvexHull(pts)
            pts = pts[hull.vertices]
        except Exception:
            # Collinear/degenerate points can still have a useful diameter.
            pass

    diff = pts[:, None, :] - pts[None, :, :]
    d2 = np.sum(diff * diff, axis=2)
    max_d2 = float(np.nanmax(d2))

    if not np.isfinite(max_d2):
        return float("nan")

    return float(np.sqrt(max_d2))


def _largest_grid_component_mask(
    a: np.ndarray,
    b: np.ndarray,
    *,
    grid_m: float,
    connectivity: int = 8,
) -> tuple[np.ndarray, int]:
    """
    Return point mask and occupied-cell count for the largest 2D grid clump.

    a/b are footprint coordinates in metres, usually X/Z.
    """
    n = int(a.size)
    if n == 0:
        return np.zeros((0,), dtype=bool), 0

    grid_m = float(grid_m)
    if not np.isfinite(grid_m) or grid_m <= 0:
        raise ValueError(f"clump_grid_m must be > 0, got {grid_m}")

    ia = np.floor(a / grid_m).astype(np.int64)
    ib = np.floor(b / grid_m).astype(np.int64)

    cells = np.column_stack([ia, ib])
    unique_cells, inverse = np.unique(cells, axis=0, return_inverse=True)

    n_cells = int(unique_cells.shape[0])
    if n_cells == 0:
        return np.zeros((n,), dtype=bool), 0

    cell_to_idx = {
        (int(unique_cells[i, 0]), int(unique_cells[i, 1])): i
        for i in range(n_cells)
    }

    point_counts = np.bincount(inverse, minlength=n_cells)

    if int(connectivity) == 4:
        offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    else:
        offsets = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        ]

    visited = np.zeros(n_cells, dtype=bool)
    best_component: list[int] = []
    best_score = -1

    for seed in range(n_cells):
        if visited[seed]:
            continue

        stack = [seed]
        visited[seed] = True
        comp: list[int] = []

        while stack:
            ci = stack.pop()
            comp.append(ci)

            ca = int(unique_cells[ci, 0])
            cb = int(unique_cells[ci, 1])

            for da, db in offsets:
                ni = cell_to_idx.get((ca + da, cb + db))
                if ni is None or visited[ni]:
                    continue
                visited[ni] = True
                stack.append(ni)

        score = int(point_counts[comp].sum())
        if score > best_score:
            best_score = score
            best_component = comp

    if not best_component:
        return np.zeros((n,), dtype=bool), 0

    best_component_arr = np.asarray(best_component, dtype=np.int64)
    point_mask = np.isin(inverse, best_component_arr)
    return point_mask, int(best_component_arr.size)


def _largest_closed_clump_cells_and_points(
    a: np.ndarray,
    b: np.ndarray,
    *,
    grid_m: float,
    connectivity: int = 8,
    close_cells: int = 1,
    fill_holes: bool = True,
) -> tuple[int, np.ndarray]:
    """
    Find largest connected occupied-cell clump in 2D, then close/fill that
    clump and return:

      closed_cell_count, point_mask_for_original_largest_clump

    a/b are footprint coordinates in metres, usually X/Z.

    Important:
    - Connectivity is used to decide what cells belong to the same observed clump.
    - Closing/filling is applied only after the largest clump is selected.
    - This does not close the whole slice, so separate neighbor plants are less
      likely to get bridged into the target.
    """
    n = int(a.size)
    if n == 0:
        return 0, np.zeros((0,), dtype=bool)

    grid_m = float(grid_m)
    if not np.isfinite(grid_m) or grid_m <= 0:
        raise ValueError(f"clump_grid_m must be > 0, got {grid_m}")

    ia = np.floor(a / grid_m).astype(np.int64)
    ib = np.floor(b / grid_m).astype(np.int64)

    cells = np.column_stack([ia, ib])
    unique_cells, inverse = np.unique(cells, axis=0, return_inverse=True)

    n_cells = int(unique_cells.shape[0])
    if n_cells == 0:
        return 0, np.zeros((n,), dtype=bool)

    cell_to_idx = {
        (int(unique_cells[i, 0]), int(unique_cells[i, 1])): i
        for i in range(n_cells)
    }

    point_counts = np.bincount(inverse, minlength=n_cells)

    if int(connectivity) == 4:
        offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    else:
        offsets = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        ]

    visited = np.zeros(n_cells, dtype=bool)
    best_component: list[int] = []
    best_score = -1

    for seed in range(n_cells):
        if visited[seed]:
            continue

        stack = [seed]
        visited[seed] = True
        comp: list[int] = []

        while stack:
            ci = stack.pop()
            comp.append(ci)

            ca = int(unique_cells[ci, 0])
            cb = int(unique_cells[ci, 1])

            for da, db in offsets:
                ni = cell_to_idx.get((ca + da, cb + db))
                if ni is None or visited[ni]:
                    continue
                visited[ni] = True
                stack.append(ni)

        # Largest clump means most original points, not widest footprint.
        score = int(point_counts[comp].sum())
        if score > best_score:
            best_score = score
            best_component = comp

    if not best_component:
        return 0, np.zeros((n,), dtype=bool)

    best_component_arr = np.asarray(best_component, dtype=np.int64)
    point_mask = np.isin(inverse, best_component_arr)

    # Build a small binary image around only the largest clump.
    best_cells = unique_cells[best_component_arr]
    min_a = int(np.min(best_cells[:, 0]))
    max_a = int(np.max(best_cells[:, 0]))
    min_b = int(np.min(best_cells[:, 1]))
    max_b = int(np.max(best_cells[:, 1]))

    # Padding gives closing room to operate without clipping at the edge.
    close_cells = max(int(close_cells), 0)
    pad = max(close_cells + 2, 2)

    shape_a = (max_a - min_a + 1) + 2 * pad
    shape_b = (max_b - min_b + 1) + 2 * pad

    img = np.zeros((shape_a, shape_b), dtype=bool)
    aa = best_cells[:, 0] - min_a + pad
    bb = best_cells[:, 1] - min_b + pad
    img[aa, bb] = True

    closed = img

    if close_cells > 0:
        try:
            from scipy import ndimage

            structure = np.ones(
                (2 * close_cells + 1, 2 * close_cells + 1),
                dtype=bool,
            )
            closed = ndimage.binary_closing(closed, structure=structure)

            if fill_holes:
                closed = ndimage.binary_fill_holes(closed)
        except Exception:
            # If scipy.ndimage is unavailable for some reason, fall back to
            # occupied cells only rather than crashing the whole pipeline.
            closed = img
    elif fill_holes:
        try:
            from scipy import ndimage
            closed = ndimage.binary_fill_holes(closed)
        except Exception:
            closed = img

    closed_cell_count = int(np.count_nonzero(closed))
    return closed_cell_count, point_mask


def _compute_slice_structure_traits(
    points_df,
    *,
    slice_height_m: float = 0.05,
    height_axis: str = "Y",
    spread_axis: str = "X",
    length_axis: str = "Z",
    percentile_height: float = 50.0,
    min_points_per_slice: int = 5,
    clump_grid_m: float = 0.05,
    clump_connectivity: int = 8,
    clump_close_cells: int = 1,
    clump_fill_holes: bool = True,
) -> tuple[dict, dict]:
    """
    Compute target-level closed-clump slice volume from the current point cloud.

    Assumes AnalysisTarget.current_points / df stores X/Y/Z in millimetres.

    Public output names are intentionally unchanged:
      - stacked_hull_volume_m3:
          now means closed largest-clump slice volume.
      - max_spread_m:
          largest 2D footprint diameter of the observed largest clump in any slice.
      - spread_at_50_m:
          2D footprint diameter of the observed largest clump near target-relative
          percentile_height. Still experimental.

    Algorithm:
      For each height slice:
        1. Grid X/Z footprint into clump_grid_m cells.
        2. Find connected occupied-cell clumps.
        3. Keep largest observed clump.
        4. Apply binary closing/fill only to that clump.
        5. Count closed cells and multiply by cell area and slice thickness.
    """
    h_col = _axis_name_to_col(height_axis)
    s_col = _axis_name_to_col(spread_axis)
    l_col = _axis_name_to_col(length_axis)

    for col in (h_col, s_col, l_col):
        if col not in points_df.columns:
            raise ValueError(f"slice_structure_trait requires column {col!r}")

    slice_height_m = float(slice_height_m)
    if slice_height_m <= 0:
        raise ValueError(f"slice_height_m must be > 0, got {slice_height_m}")

    clump_grid_m = float(clump_grid_m)
    if clump_grid_m <= 0:
        raise ValueError(f"clump_grid_m must be > 0, got {clump_grid_m}")

    percentile_height = float(percentile_height)
    if not (0.0 <= percentile_height <= 100.0):
        raise ValueError(
            f"percentile_height must be between 0 and 100, got {percentile_height}"
        )

    min_points_per_slice = int(min_points_per_slice)
    if min_points_per_slice < 1:
        min_points_per_slice = 1

    clump_connectivity = 4 if int(clump_connectivity) == 4 else 8
    clump_close_cells = max(int(clump_close_cells), 0)
    clump_fill_holes = bool(clump_fill_holes)

    # Convert once: pipeline stores coordinates in mm; this op works in metres.
    xyz_m = points_df[[s_col, h_col, l_col]].to_numpy(dtype=float, copy=True) / 1000.0

    spread = xyz_m[:, 0]
    height = xyz_m[:, 1]
    length = xyz_m[:, 2]

    valid = np.isfinite(spread) & np.isfinite(height) & np.isfinite(length)
    spread = spread[valid]
    height = height[valid]
    length = length[valid]

    traits = {
        "stacked_hull_volume_m3": float("nan"),
        "max_spread_m": float("nan"),
        "spread_at_50_m": float("nan"),
    }

    diagnostics = {
        "n_points_input": int(points_df.shape[0]),
        "n_points_valid": int(height.size),
        "slice_height_m": float(slice_height_m),
        "clump_grid_m": float(clump_grid_m),
        "clump_connectivity": int(clump_connectivity),
        "clump_close_cells": int(clump_close_cells),
        "clump_fill_holes": bool(clump_fill_holes),
        "height_axis": h_col,
        "spread_axis": s_col,
        "length_axis": l_col,
        "volume_metric": "closed_largest_connected_clump_grid_volume",
        "spread_metric": "observed_largest_clump_2d_footprint_diameter",
        "percentile_height": float(percentile_height),
        "min_points_per_slice": int(min_points_per_slice),
        "n_slices": 0,
        "n_slices_used_for_volume": 0,
        "n_slices_used_for_spread": 0,
        "n_slices_skipped_min_points": 0,
        "target_height_min_m": float("nan"),
        "target_height_max_m": float("nan"),
        "target_height_range_m": float("nan"),
        "percentile_height_center_m": float("nan"),
        "spread_at_percentile_n_points": 0,
    }

    if height.size == 0:
        return traits, diagnostics

    h_min = float(np.nanmin(height))
    h_max = float(np.nanmax(height))
    h_range = h_max - h_min

    diagnostics["target_height_min_m"] = h_min
    diagnostics["target_height_max_m"] = h_max
    diagnostics["target_height_range_m"] = h_range

    if not np.isfinite(h_range) or h_range <= 0:
        return traits, diagnostics

    n_slices = int(np.ceil(h_range / slice_height_m))
    diagnostics["n_slices"] = n_slices

    total_volume = 0.0
    max_spread = float("nan")
    n_volume_slices = 0
    n_spread_slices = 0
    n_slices_skipped_min_points = 0

    for i in range(n_slices):
        lo = h_min + i * slice_height_m
        hi = min(lo + slice_height_m, h_max)

        if i == n_slices - 1:
            m = (height >= lo) & (height <= hi)
        else:
            m = (height >= lo) & (height < hi)

        n = int(np.sum(m))
        if n == 0:
            continue

        if n < min_points_per_slice:
            n_slices_skipped_min_points += 1
            continue

        slice_spread = spread[m]
        slice_length = length[m]

        closed_cells, keep_mask = _largest_closed_clump_cells_and_points(
            slice_spread,
            slice_length,
            grid_m=clump_grid_m,
            connectivity=clump_connectivity,
            close_cells=clump_close_cells,
            fill_holes=clump_fill_holes,
        )

        if closed_cells <= 0 or not np.any(keep_mask):
            continue

        thickness_m = max(float(hi - lo), 0.0)
        total_volume += float(closed_cells) * (clump_grid_m ** 2) * thickness_m
        n_volume_slices += 1

        # Spread uses observed largest clump points, not the closed/fill mask.
        clump_pts_2d = np.column_stack([slice_spread[keep_mask], slice_length[keep_mask]])
        if clump_pts_2d.shape[0] >= 2:
            diameter_m = _footprint_diameter_2d(clump_pts_2d)
            if np.isfinite(diameter_m):
                max_spread = (
                    diameter_m
                    if not np.isfinite(max_spread)
                    else max(max_spread, diameter_m)
                )
                n_spread_slices += 1

    # Target-relative percentile height.
    frac = percentile_height / 100.0
    h_center = h_min + frac * h_range
    diagnostics["percentile_height_center_m"] = float(h_center)

    half_slice = slice_height_m / 2.0
    p_mask = (height >= h_center - half_slice) & (height <= h_center + half_slice)
    n_p = int(np.sum(p_mask))
    diagnostics["spread_at_percentile_n_points"] = n_p

    if n_p >= min_points_per_slice:
        p_spread = spread[p_mask]
        p_length = length[p_mask]
        _, p_keep_mask = _largest_closed_clump_cells_and_points(
            p_spread,
            p_length,
            grid_m=clump_grid_m,
            connectivity=clump_connectivity,
            close_cells=clump_close_cells,
            fill_holes=clump_fill_holes,
        )
        if np.any(p_keep_mask):
            p_pts_2d = np.column_stack([p_spread[p_keep_mask], p_length[p_keep_mask]])
            spread_at_p = _footprint_diameter_2d(p_pts_2d)
        else:
            spread_at_p = float("nan")
    else:
        spread_at_p = float("nan")

    traits["stacked_hull_volume_m3"] = float(total_volume) if n_volume_slices > 0 else float("nan")
    traits["max_spread_m"] = float(max_spread)
    traits["spread_at_50_m"] = float(spread_at_p)

    diagnostics["n_slices_used_for_volume"] = int(n_volume_slices)
    diagnostics["n_slices_used_for_spread"] = int(n_spread_slices)
    diagnostics["n_slices_skipped_min_points"] = int(n_slices_skipped_min_points)

    return traits, diagnostics
