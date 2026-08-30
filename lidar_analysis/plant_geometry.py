from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from scipy import ndimage


_TRAIT_KEYS = (
    "plant_height_m",
    "plant_height_p90_m",
    "plant_height_p95_m",
    "plant_height_p98_m",
    "plant_height_uncertainty_m",
    "footprint_area_m2",
    "profile_area_xy_m2",
    "profile_area_zy_m2",
    "profile_area_median_m2",
    "profile_area_min_m2",
    "profile_area_max_m2",
    "canopy_envelope_volume_m3",
    "canopy_occupied_volume_m3",
    "geometry_confidence",
    "geometry_qc_status",
)


def empty_plant_geometry_traits(status: str = "fail") -> dict[str, Any]:
    traits: dict[str, Any] = {key: float("nan") for key in _TRAIT_KEYS}
    traits["geometry_confidence"] = 0.0
    traits["geometry_qc_status"] = str(status)
    return traits


def _positive_float(cfg: dict[str, Any], key: str, default: float) -> float:
    value = float(cfg.get(key, default))
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"plant_geometry_trait {key} must be > 0; got {value!r}")
    return value


def _unit_grid(values: np.ndarray, grid_m: float) -> np.ndarray:
    return np.floor(values / grid_m).astype(np.int64)


def _projection_area(
    a: np.ndarray,
    b: np.ndarray,
    *,
    grid_m: float,
    close_cells: int = 0,
) -> float:
    if a.size == 0:
        return float("nan")

    cells = np.unique(np.column_stack([_unit_grid(a, grid_m), _unit_grid(b, grid_m)]), axis=0)
    if cells.size == 0:
        return float("nan")
    if close_cells <= 0 or cells.shape[0] < 3:
        return float(cells.shape[0]) * (grid_m ** 2)

    mins = cells.min(axis=0)
    shifted = cells - mins
    shape = tuple((shifted.max(axis=0) + 1).tolist())
    image = np.zeros(shape, dtype=bool)
    image[shifted[:, 0], shifted[:, 1]] = True
    structure = np.ones((2 * close_cells + 1, 2 * close_cells + 1), dtype=bool)
    # Padding prevents scipy's false border from eroding cells that happen to
    # lie on the projection's bounding box.
    padded = np.pad(image, close_cells, mode="constant", constant_values=False)
    closed = ndimage.binary_closing(padded, structure=structure)
    return float(np.count_nonzero(closed)) * (grid_m ** 2)


def _component_from_cells(
    cells: np.ndarray,
    point_inverse: np.ndarray,
    point_counts: np.ndarray,
    *,
    center_x_m: float,
    center_z_m: float,
    grid_m: float,
    connectivity: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Select the supported footprint component nearest the inferred crown."""
    if cells.size == 0:
        return np.zeros((point_inverse.size,), dtype=bool), np.empty((0, 2), dtype=np.int64), 0

    mins = cells.min(axis=0)
    shifted = cells - mins
    shape = tuple((shifted.max(axis=0) + 1).tolist())
    image = np.zeros(shape, dtype=bool)
    image[shifted[:, 0], shifted[:, 1]] = True
    structure = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    labels, n_labels = ndimage.label(image, structure=structure)

    center_ix = int(np.floor(center_x_m / grid_m))
    center_iz = int(np.floor(center_z_m / grid_m))
    cell_labels = labels[shifted[:, 0], shifted[:, 1]]
    best_label = 0
    best_key: tuple[float, int] | None = None

    for label_id in range(1, n_labels + 1):
        cell_ids = np.where(cell_labels == label_id)[0]
        absolute = cells[cell_ids]
        support = int(point_counts[cell_ids].sum())
        dist_cells = np.sqrt(
            (absolute[:, 0] - center_ix) ** 2 + (absolute[:, 1] - center_iz) ** 2
        )
        nearest_m = float(np.min(dist_cells)) * grid_m
        # The target crown must win over a much denser neighbouring plant.
        # Support only breaks ties between components equally close to the
        # inferred/configured center.
        key = (-nearest_m, support)
        if best_key is None or key > best_key:
            best_key = key
            best_label = label_id

    chosen_cell_mask = cell_labels == best_label
    chosen_cells = cells[chosen_cell_mask]
    chosen_cell_ids = np.where(chosen_cell_mask)[0]
    point_mask = np.isin(point_inverse, chosen_cell_ids)
    return point_mask, chosen_cells, int(best_label)


def _infer_crown_center(
    x_m: np.ndarray,
    z_m: np.ndarray,
    height_m: np.ndarray,
    cfg: dict[str, Any],
    grid_m: float,
) -> tuple[float, float, str]:
    if cfg.get("center_x_m") is not None and cfg.get("center_z_m") is not None:
        return float(cfg["center_x_m"]), float(cfg["center_z_m"]), "configured"

    high_quantile = float(cfg.get("crown_seed_height_quantile", 0.85))
    if not 0.0 <= high_quantile <= 1.0:
        raise ValueError("plant_geometry_trait crown_seed_height_quantile must be between 0 and 1")
    threshold = float(np.quantile(height_m, high_quantile))
    high = height_m >= threshold
    if int(np.sum(high)) < 3:
        high = np.ones_like(height_m, dtype=bool)

    _, inverse, counts = np.unique(
        np.column_stack([_unit_grid(x_m[high], grid_m), _unit_grid(z_m[high], grid_m)]),
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    best_cell_id = int(np.argmax(counts))
    high_indices = np.where(high)[0]
    crown_indices = high_indices[inverse == best_cell_id]
    return (
        float(np.median(x_m[crown_indices])),
        float(np.median(z_m[crown_indices])),
        "high_point_density",
    )


def _estimate_background_ceiling(
    x_m: np.ndarray,
    z_m: np.ndarray,
    height_m: np.ndarray,
    *,
    center_x_m: float,
    center_z_m: float,
    grid_m: float,
    cfg: dict[str, Any],
) -> tuple[float, int, str]:
    configured = cfg.get("background_ceiling_m", cfg.get("clover_ceiling_m"))
    if configured is not None:
        return max(float(configured), 0.0), 0, "configured"

    inner = float(cfg.get("background_inner_radius_m", 0.18))
    outer = float(cfg.get("background_outer_radius_m", 0.34))
    if inner < 0.0 or outer <= inner:
        raise ValueError(
            "plant_geometry_trait background radii must satisfy "
            "0 <= background_inner_radius_m < background_outer_radius_m"
        )

    radius = np.hypot(x_m - center_x_m, z_m - center_z_m)
    background = (radius >= inner) & (radius <= outer) & (height_m >= 0.0)
    if int(np.sum(background)) < 5:
        fallback = float(np.quantile(height_m[height_m >= 0.0], 0.35))
        return max(fallback, 0.0), 0, "global_height_fallback"

    cells = np.column_stack([
        _unit_grid(x_m[background], grid_m),
        _unit_grid(z_m[background], grid_m),
    ])
    _, inverse = np.unique(cells, axis=0, return_inverse=True)
    bg_height = height_m[background]
    cell_quantile = float(cfg.get("background_cell_height_quantile", 0.90))
    ceiling_quantile = float(cfg.get("background_ceiling_quantile", 0.50))
    if not 0.0 <= cell_quantile <= 1.0 or not 0.0 <= ceiling_quantile <= 1.0:
        raise ValueError("plant_geometry_trait background quantiles must be between 0 and 1")

    cell_tops = np.asarray([
        np.quantile(bg_height[inverse == cell_id], cell_quantile)
        for cell_id in range(int(inverse.max()) + 1)
    ])
    ceiling = float(np.quantile(cell_tops, ceiling_quantile))
    return max(ceiling, 0.0), int(cell_tops.size), "background_annulus"


def _slice_envelope_volume(
    x_m: np.ndarray,
    z_m: np.ndarray,
    height_m: np.ndarray,
    *,
    footprint_grid_m: float,
    slice_height_m: float,
    min_points_per_slice: int,
    close_cells: int,
) -> tuple[float, int]:
    if height_m.size == 0:
        return float("nan"), 0

    slice_ids = np.floor(np.maximum(height_m, 0.0) / slice_height_m).astype(np.int64)
    total = 0.0
    used = 0
    for slice_id in np.unique(slice_ids):
        mask = slice_ids == slice_id
        if int(np.sum(mask)) < min_points_per_slice:
            continue
        area = _projection_area(
            x_m[mask],
            z_m[mask],
            grid_m=footprint_grid_m,
            close_cells=close_cells,
        )
        if np.isfinite(area) and area > 0.0:
            total += area * slice_height_m
            used += 1
    return (float(total) if used else float("nan")), used


def _occupied_volume(
    x_m: np.ndarray,
    z_m: np.ndarray,
    height_m: np.ndarray,
    *,
    voxel_size_m: float,
) -> tuple[float, int]:
    if height_m.size == 0:
        return float("nan"), 0
    cells = np.column_stack([
        _unit_grid(x_m, voxel_size_m),
        _unit_grid(height_m, voxel_size_m),
        _unit_grid(z_m, voxel_size_m),
    ])
    count = int(np.unique(cells, axis=0).shape[0])
    return float(count) * (voxel_size_m ** 3), count


def _profile_areas(
    x_m: np.ndarray,
    z_m: np.ndarray,
    height_m: np.ndarray,
    *,
    grid_m: float,
    close_cells: int,
    angles_deg: Iterable[float],
) -> tuple[float, float, float, float, float, list[dict[str, float]]]:
    xy = _projection_area(x_m, height_m, grid_m=grid_m, close_cells=close_cells)
    zy = _projection_area(z_m, height_m, grid_m=grid_m, close_cells=close_cells)
    per_angle: list[dict[str, float]] = []
    for angle_deg in angles_deg:
        angle = np.deg2rad(float(angle_deg))
        horizontal = x_m * np.cos(angle) + z_m * np.sin(angle)
        area = _projection_area(horizontal, height_m, grid_m=grid_m, close_cells=close_cells)
        if np.isfinite(area):
            per_angle.append({"angle_deg": float(angle_deg), "area_m2": float(area)})
    if not per_angle:
        return xy, zy, float("nan"), float("nan"), float("nan"), per_angle
    values = np.asarray([entry["area_m2"] for entry in per_angle], dtype=float)
    return xy, zy, float(np.median(values)), float(np.min(values)), float(np.max(values)), per_angle


def compute_plant_geometry_traits(
    points_df: pd.DataFrame,
    op_cfg: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Estimate crown-connected meadow-fescue geometry from an AnalysisTarget.

    Coordinates and ``height_agl`` are expected in the pipeline's internal
    millimetre units. The operation is deliberately conservative: it retains
    the input cloud, emits independent experimental traits, and records enough
    diagnostics to reject sparse, boundary-clipped, or poorly separated plots.
    """
    cfg = dict(op_cfg or {})
    context = dict(context or {})
    required = {"X", "Y", "Z"}
    missing = sorted(required.difference(points_df.columns))
    if missing:
        raise ValueError(f"plant_geometry_trait missing required column(s): {missing}")

    diagnostics: dict[str, Any] = {
        "algorithm": "crown_connected_projection_v1",
        "experimental": True,
        "input_points": int(len(points_df)),
        "selected_points": 0,
        "qc_flags": [],
    }
    if points_df.empty:
        diagnostics["qc_flags"] = ["empty_target"]
        return empty_plant_geometry_traits(), diagnostics

    x_m = pd.to_numeric(points_df["X"], errors="coerce").to_numpy(dtype=float) / 1000.0
    y_m = pd.to_numeric(points_df["Y"], errors="coerce").to_numpy(dtype=float) / 1000.0
    z_m = pd.to_numeric(points_df["Z"], errors="coerce").to_numpy(dtype=float) / 1000.0
    if "height_agl" in points_df.columns:
        height_m = pd.to_numeric(points_df["height_agl"], errors="coerce").to_numpy(dtype=float) / 1000.0
        diagnostics["height_source"] = "height_agl"
    else:
        ground_q = float(cfg.get("fallback_ground_quantile", 0.05))
        if not 0.0 <= ground_q <= 1.0:
            raise ValueError("plant_geometry_trait fallback_ground_quantile must be between 0 and 1")
        finite_y = y_m[np.isfinite(y_m)]
        ground_m = float(np.quantile(finite_y, ground_q)) if finite_y.size else float("nan")
        height_m = y_m - ground_m
        diagnostics["height_source"] = "target_y_quantile_fallback"
        diagnostics["fallback_ground_y_m"] = ground_m

    finite = np.isfinite(x_m) & np.isfinite(z_m) & np.isfinite(height_m)
    nonnegative = height_m >= float(cfg.get("minimum_geometry_height_m", 0.02))
    valid = finite & nonnegative
    x_m = x_m[valid]
    z_m = z_m[valid]
    height_m = height_m[valid]
    diagnostics["valid_points"] = int(height_m.size)
    if height_m.size < int(cfg.get("minimum_target_points", 20)):
        diagnostics["qc_flags"] = ["insufficient_target_points"]
        return empty_plant_geometry_traits(), diagnostics

    footprint_grid_m = _positive_float(cfg, "footprint_grid_m", 0.025)
    profile_grid_m = _positive_float(cfg, "profile_grid_m", footprint_grid_m)
    voxel_size_m = _positive_float(cfg, "voxel_size_m", footprint_grid_m)
    slice_height_m = _positive_float(cfg, "slice_height_m", footprint_grid_m)
    max_radius_m = _positive_float(cfg, "maximum_crown_radius_m", 0.36)
    center_x_m, center_z_m, center_source = _infer_crown_center(
        x_m, z_m, height_m, cfg, footprint_grid_m
    )
    diagnostics.update({
        "crown_center_x_m": center_x_m,
        "crown_center_z_m": center_z_m,
        "crown_center_source": center_source,
        "footprint_grid_m": footprint_grid_m,
        "profile_grid_m": profile_grid_m,
        "voxel_size_m": voxel_size_m,
        "slice_height_m": slice_height_m,
        "maximum_crown_radius_m": max_radius_m,
    })

    radius = np.hypot(x_m - center_x_m, z_m - center_z_m)
    roi = radius <= max_radius_m
    x_roi = x_m[roi]
    z_roi = z_m[roi]
    h_roi = height_m[roi]
    diagnostics["roi_points"] = int(h_roi.size)
    if h_roi.size < int(cfg.get("minimum_target_points", 20)):
        diagnostics["qc_flags"] = ["insufficient_points_in_crown_roi"]
        return empty_plant_geometry_traits(), diagnostics

    background_ceiling_m, background_cells, background_source = _estimate_background_ceiling(
        x_m,
        z_m,
        height_m,
        center_x_m=center_x_m,
        center_z_m=center_z_m,
        grid_m=footprint_grid_m,
        cfg=cfg,
    )
    margin_m = float(cfg.get("background_margin_m", 0.04))
    if not np.isfinite(margin_m) or margin_m < 0.0:
        raise ValueError("plant_geometry_trait background_margin_m must be >= 0")
    diagnostics.update({
        "background_ceiling_m": background_ceiling_m,
        "background_cell_count": background_cells,
        "background_source": background_source,
        "background_margin_m": margin_m,
    })

    footprint_cells, inverse, counts = np.unique(
        np.column_stack([_unit_grid(x_roi, footprint_grid_m), _unit_grid(z_roi, footprint_grid_m)]),
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    top_quantile = float(cfg.get("cell_top_quantile", 0.95))
    if not 0.0 <= top_quantile <= 1.0:
        raise ValueError("plant_geometry_trait cell_top_quantile must be between 0 and 1")
    tops = np.asarray([
        np.quantile(h_roi[inverse == cell_id], top_quantile)
        for cell_id in range(footprint_cells.shape[0])
    ])
    minimum_cell_points = max(int(cfg.get("minimum_points_per_footprint_cell", 2)), 1)
    candidate_cell_mask = (tops >= background_ceiling_m + margin_m) & (counts >= minimum_cell_points)
    candidate_cells = footprint_cells[candidate_cell_mask]
    if candidate_cells.size == 0:
        diagnostics["qc_flags"] = ["no_cells_above_background"]
        return empty_plant_geometry_traits(), diagnostics

    candidate_id_by_all = np.full(footprint_cells.shape[0], -1, dtype=np.int64)
    candidate_id_by_all[np.where(candidate_cell_mask)[0]] = np.arange(candidate_cells.shape[0])
    point_candidate_inverse = candidate_id_by_all[inverse]
    candidate_points = point_candidate_inverse >= 0
    candidate_inverse = point_candidate_inverse[candidate_points]
    candidate_counts = np.bincount(candidate_inverse, minlength=candidate_cells.shape[0])
    connectivity = int(cfg.get("footprint_connectivity", 8))
    if connectivity not in (4, 8):
        raise ValueError("plant_geometry_trait footprint_connectivity must be 4 or 8")
    selected_candidate_points, selected_cells, _ = _component_from_cells(
        candidate_cells,
        candidate_inverse,
        candidate_counts,
        center_x_m=center_x_m,
        center_z_m=center_z_m,
        grid_m=footprint_grid_m,
        connectivity=connectivity,
    )

    selected_roi_mask = np.zeros(h_roi.size, dtype=bool)
    selected_roi_mask[np.where(candidate_points)[0][selected_candidate_points]] = True
    selected_cell_set = {tuple(cell) for cell in selected_cells.tolist()}
    all_cell_membership = np.asarray([
        tuple(cell) in selected_cell_set for cell in footprint_cells[inverse]
    ])
    core_radius_m = float(cfg.get("crown_core_radius_m", 0.12))
    outer_point_margin_m = float(cfg.get("outer_point_margin_m", 0.01))
    if not np.isfinite(core_radius_m) or core_radius_m < 0.0:
        raise ValueError("plant_geometry_trait crown_core_radius_m must be >= 0")
    if not np.isfinite(outer_point_margin_m) or outer_point_margin_m < 0.0:
        raise ValueError("plant_geometry_trait outer_point_margin_m must be >= 0")
    outer_floor_m = background_ceiling_m + outer_point_margin_m
    selected_roi_mask = all_cell_membership & (
        (h_roi >= outer_floor_m)
        | (np.hypot(x_roi - center_x_m, z_roi - center_z_m) <= core_radius_m)
    )
    selected_x = x_roi[selected_roi_mask]
    selected_z = z_roi[selected_roi_mask]
    selected_h = h_roi[selected_roi_mask]
    diagnostics["selected_points"] = int(selected_h.size)
    diagnostics["selected_footprint_cells"] = int(selected_cells.shape[0])
    diagnostics["outer_point_floor_m"] = outer_floor_m

    minimum_selected = int(cfg.get("minimum_selected_points", 20))
    if selected_h.size < minimum_selected:
        diagnostics["qc_flags"] = ["insufficient_selected_plant_points"]
        return empty_plant_geometry_traits(), diagnostics

    cell_top_values = tops[candidate_cell_mask]
    chosen_cell_mask = np.asarray([tuple(cell) in selected_cell_set for cell in candidate_cells])
    chosen_tops = cell_top_values[chosen_cell_mask]
    h90, h95, h98 = [float(np.quantile(chosen_tops, q)) for q in (0.90, 0.95, 0.98)]
    primary_height_q = float(cfg.get("height_quantile", 0.95))
    if not 0.0 <= primary_height_q <= 1.0:
        raise ValueError("plant_geometry_trait height_quantile must be between 0 and 1")
    plant_height = float(np.quantile(chosen_tops, primary_height_q))
    height_uncertainty = float((h98 - h90) / 2.0)

    footprint_area = float(selected_cells.shape[0]) * (footprint_grid_m ** 2)
    angles = cfg.get("projection_angles_deg", [0.0, 45.0, 90.0, 135.0])
    if not isinstance(angles, (list, tuple)) or not angles:
        raise ValueError("plant_geometry_trait projection_angles_deg must be a non-empty list")
    profile_close_cells = max(int(cfg.get("profile_close_cells", 0)), 0)
    xy_area, zy_area, median_area, min_area, max_area, per_angle = _profile_areas(
        selected_x,
        selected_z,
        selected_h,
        grid_m=profile_grid_m,
        close_cells=profile_close_cells,
        angles_deg=angles,
    )
    envelope_volume, used_slices = _slice_envelope_volume(
        selected_x,
        selected_z,
        selected_h,
        footprint_grid_m=footprint_grid_m,
        slice_height_m=slice_height_m,
        min_points_per_slice=max(int(cfg.get("minimum_points_per_slice", 3)), 1),
        close_cells=max(int(cfg.get("slice_close_cells", 0)), 0),
    )
    occupied_volume, occupied_voxels = _occupied_volume(
        selected_x,
        selected_z,
        selected_h,
        voxel_size_m=voxel_size_m,
    )

    selected_radius = np.hypot(selected_x - center_x_m, selected_z - center_z_m)
    radial_boundary_fraction = float(np.mean(selected_radius >= (max_radius_m - footprint_grid_m)))
    z_boundary_fraction = 0.0
    z_min_m = context.get("target_z_min_m")
    z_max_m = context.get("target_z_max_m")
    if z_min_m is not None and z_max_m is not None:
        near_z = (selected_z <= float(z_min_m) + footprint_grid_m) | (
            selected_z >= float(z_max_m) - footprint_grid_m
        )
        z_boundary_fraction = float(np.mean(near_z))
    boundary_fraction = max(radial_boundary_fraction, z_boundary_fraction)

    flags: list[str] = []
    confidence = 1.0
    weak_background = background_source not in {"background_annulus", "configured"} or (
        background_source == "background_annulus" and background_cells < 5
    )
    if weak_background:
        flags.append("weak_background_estimate")
        confidence -= 0.25
    if selected_h.size < 100:
        flags.append("sparse_plant_support")
        confidence -= 0.20
    if chosen_tops.size < 8:
        flags.append("few_supported_height_cells")
        confidence -= 0.15
    if boundary_fraction > 0.05:
        flags.append("plant_touches_target_boundary")
        confidence -= min(0.35, boundary_fraction)
    confidence = float(np.clip(confidence, 0.0, 1.0))
    qc_status = "pass" if confidence >= 0.75 else "review" if confidence >= 0.45 else "fail"

    diagnostics.update({
        "height_cell_count": int(chosen_tops.size),
        "height_quantile": primary_height_q,
        "profile_areas_by_angle": per_angle,
        "volume_slices_used": int(used_slices),
        "occupied_voxel_count": int(occupied_voxels),
        "radial_boundary_fraction": radial_boundary_fraction,
        "z_boundary_fraction": z_boundary_fraction,
        "boundary_contact_fraction": boundary_fraction,
        "qc_flags": flags,
        "geometry_confidence": confidence,
        "geometry_qc_status": qc_status,
    })
    traits = {
        "plant_height_m": plant_height,
        "plant_height_p90_m": h90,
        "plant_height_p95_m": h95,
        "plant_height_p98_m": h98,
        "plant_height_uncertainty_m": height_uncertainty,
        "footprint_area_m2": footprint_area,
        "profile_area_xy_m2": xy_area,
        "profile_area_zy_m2": zy_area,
        "profile_area_median_m2": median_area,
        "profile_area_min_m2": min_area,
        "profile_area_max_m2": max_area,
        "canopy_envelope_volume_m3": envelope_volume,
        "canopy_occupied_volume_m3": occupied_volume,
        "geometry_confidence": confidence,
        "geometry_qc_status": qc_status,
    }
    return traits, diagnostics
