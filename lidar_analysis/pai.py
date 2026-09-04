from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar

try:
    from .fad import Box3D, _normalize_directions, box_is_valid, make_layer_edges, ray_box_intersection
except ImportError:
    from fad import Box3D, _normalize_directions, box_is_valid, make_layer_edges, ray_box_intersection


def _classify_rays(origins_m, directions_m, ranges_m, raw_hit_mask, box, tolerance_m=1e-4):
    origins = np.asarray(origins_m, dtype=float)
    directions, valid_direction = _normalize_directions(directions_m)
    ranges = np.asarray(ranges_m, dtype=float)
    raw_hits = np.asarray(raw_hit_mask, dtype=bool)
    if origins.ndim != 2 or origins.shape[1] != 3 or directions.shape != origins.shape:
        raise ValueError("origins_m and directions_m must have matching n x 3 shapes")
    if ranges.shape != (len(origins),) or raw_hits.shape != (len(origins),):
        raise ValueError("ranges_m and raw_hit_mask must match the ray count")

    result = _classify_normalized_rays(origins, directions, ranges, raw_hits, box, tolerance_m)
    intersects, observed, hit, gap, prehit, chord = result
    intersects &= valid_direction
    observed &= valid_direction
    hit &= valid_direction
    gap &= valid_direction
    prehit &= valid_direction
    return directions, intersects, observed, hit, gap, prehit, chord


def _classify_normalized_rays(origins, directions_unit, ranges, raw_hits, box, tolerance_m=1e-4):
    t_enter, t_exit, intersects = ray_box_intersection(
        origins_m=origins, directions_unit=directions_unit, box=box
    )
    entry = np.maximum(t_enter, 0.0)
    has_return = raw_hits & np.isfinite(ranges) & (ranges > 0.0)
    prehit = intersects & has_return & (ranges < entry - tolerance_m)
    observed = intersects & ~prehit
    hit = observed & has_return & (ranges <= t_exit + tolerance_m)
    gap = observed & ~hit
    chord = np.clip(t_exit - entry, 0.0, None)
    observed &= chord > 1e-9
    hit &= observed
    gap &= observed
    return intersects, observed, hit, gap, prehit, chord


def _fit_transmission(chords: np.ndarray, gaps: np.ndarray, g_value: float):
    chords = np.asarray(chords, dtype=float)
    gaps = np.asarray(gaps, dtype=bool)
    if chords.size == 0:
        return np.nan, np.nan, False, False
    if np.all(gaps):
        return 0.0, 0.0, True, False
    if not np.any(gaps):
        return np.nan, np.nan, False, True

    def nll(mu):
        eta = float(g_value) * float(mu) * chords
        return float(np.sum(eta[gaps]) - np.sum(np.log(-np.expm1(-eta[~gaps]))))

    result = minimize_scalar(nll, bounds=(0.0, 1e4), method="bounded")
    return float(result.x), float(-result.fun), bool(result.success), False


def layer_path_matrix(origins_m, directions_m, box: Box3D, layer_edges_y_m):
    origins = np.asarray(origins_m, dtype=float)
    directions, valid = _normalize_directions(directions_m)
    edges = np.asarray(layer_edges_y_m, dtype=float)
    columns = []
    for bottom, top in zip(edges[:-1], edges[1:]):
        layer = Box3D(box.x_min, box.x_max, float(bottom), float(top), box.z_min, box.z_max)
        enter, exit_, intersects = ray_box_intersection(
            origins_m=origins, directions_unit=directions, box=layer
        )
        columns.append(np.where(intersects & valid, np.clip(exit_ - np.maximum(enter, 0.0), 0.0, None), 0.0))
    return np.column_stack(columns) if columns else np.empty((len(origins), 0))


def compute_pai_traits(
    *, origins_m, directions_m, ranges_m, raw_hit_mask, box: Box3D,
    g_function: str = "spherical", g_value: float = 0.5,
    layer_thickness_m: float | None = 0.1, include_layer_columns: bool = True,
    run_conditional_profile: bool = False,
    run_joint_profile: bool = False,
    diagnostic: bool = False,
) -> dict[str, Any]:
    if str(g_function).strip().lower() != "spherical":
        raise ValueError("PAI currently supports only pai_g_function='spherical'")
    g_value = float(g_value)
    if not np.isfinite(g_value) or not np.isclose(g_value, 0.5, rtol=1e-12, atol=1e-12):
        raise ValueError("pai_g_function='spherical' requires pai_g_value=0.5")

    n_total = len(np.asarray(origins_m))
    height = box.y_max - box.y_min
    base = {
        "pai_pad_m2_m3": np.nan, "pai_m2_m2": np.nan,
        "pai_whole_box_pad_m2_m3": np.nan, "pai_whole_box_m2_m2": np.nan,
        "pai_gap_fraction": np.nan, "pai_hit_fraction": np.nan,
        "pai_n_rays_total": n_total, "pai_n_rays_intersecting_box": 0,
        "pai_n_rays_observed": 0, "pai_n_hits": 0, "pai_n_full_gaps": 0,
        "pai_n_hits_before_box": 0, "pai_reach_fraction": np.nan,
        "pai_mean_chord_m": np.nan, "pai_median_chord_m": np.nan,
        "pai_total_geometric_chord_m": 0.0, "pai_log_likelihood": np.nan,
        "pai_converged": False, "pai_saturated": False,
        "pai_g_function": "spherical", "pai_g_value": g_value,
        "pai_x_min_m": box.x_min, "pai_x_max_m": box.x_max,
        "pai_y_min_m": box.y_min, "pai_y_max_m": box.y_max,
        "pai_z_min_m": box.z_min, "pai_z_max_m": box.z_max,
        "pai_box_height_m": box.y_max - box.y_min,
        "pai_box_width_m": box.x_max - box.x_min,
        "pai_box_length_m": box.z_max - box.z_min,
        "pai_height_m": height, "pai_layer_thickness_m": layer_thickness_m,
        "pai_n_layers": 0,
        "pai_profile_converged": False, "pai_profile_identifiable": False,
        "pai_profile_rank": 0, "pai_profile_n_layers": 0,
        "pai_profile_condition_number": np.nan,
        "pai_profile_min_singular_value": np.nan,
        "pai_profile_n_observed": 0, "pai_from_layers_m2_m2": np.nan,
        "pai_profile_vs_whole_difference": np.nan,
    }
    if run_conditional_profile:
        base["pai_conditional_from_layers_m2_m2"] = np.nan
        base["pai_conditional_profile_complete"] = False
    if not box_is_valid(box):
        return base

    directions, intersects, observed, hits, gaps, prehit, chord = _classify_rays(
        origins_m, directions_m, ranges_m, raw_hit_mask, box
    )
    obs_chord = chord[observed]
    obs_gaps = gaps[observed]
    n_intersecting = int(intersects.sum())
    n_observed = int(observed.sum())
    n_gaps = int(obs_gaps.sum())
    n_hits = n_observed - n_gaps
    mu, log_likelihood, converged, saturated = _fit_transmission(obs_chord, obs_gaps, g_value)
    base.update({
        "pai_pad_m2_m3": mu,
        "pai_m2_m2": mu * height if np.isfinite(mu) and not run_conditional_profile else np.nan,
        "pai_whole_box_pad_m2_m3": mu,
        "pai_whole_box_m2_m2": mu * height if np.isfinite(mu) else np.nan,
        "pai_gap_fraction": n_gaps / n_observed if n_observed else np.nan,
        "pai_hit_fraction": n_hits / n_observed if n_observed else np.nan,
        "pai_n_rays_intersecting_box": n_intersecting, "pai_n_rays_observed": n_observed,
        "pai_n_hits": n_hits, "pai_n_full_gaps": n_gaps,
        "pai_n_hits_before_box": int(prehit.sum()),
        "pai_reach_fraction": n_observed / n_intersecting if n_intersecting else np.nan,
        "pai_mean_chord_m": float(np.mean(obs_chord)) if n_observed else np.nan,
        "pai_median_chord_m": float(np.median(obs_chord)) if n_observed else np.nan,
        "pai_total_geometric_chord_m": float(np.sum(obs_chord)),
        "pai_log_likelihood": log_likelihood, "pai_converged": converged,
        "pai_saturated": saturated,
    })

    if layer_thickness_m is None:
        if run_conditional_profile:
            raise ValueError("Layer-integrated PAI requires pai_layer_thickness_m")
        return base
    edges = make_layer_edges(y_min_m=box.y_min, y_max_m=box.y_max, layer_thickness_m=layer_thickness_m)
    base["pai_n_layers"] = len(edges) - 1
    if n_observed == 0 and not (run_conditional_profile or run_joint_profile):
        return base
    if run_joint_profile:
        matrix = layer_path_matrix(np.asarray(origins_m)[observed], directions[observed], box, edges)
        rank = int(np.linalg.matrix_rank(matrix))
        n_layers = matrix.shape[1]
        singular_values = np.linalg.svd(matrix, compute_uv=False)
        max_sv = float(singular_values[0]) if singular_values.size else np.nan
        min_sv = float(singular_values[-1]) if singular_values.size and rank == n_layers else 0.0
        condition_number = max_sv / min_sv if min_sv > 0.0 else np.inf
        identifiable = rank == n_layers and n_hits > 0 and n_gaps > 0
        base.update({"pai_profile_rank": rank, "pai_profile_n_layers": n_layers,
                     "pai_profile_condition_number": condition_number,
                     "pai_profile_min_singular_value": min_sv,
                     "pai_profile_n_observed": n_observed, "pai_profile_identifiable": identifiable})
        layer_mu = np.full(n_layers, np.nan)
        if identifiable:
            def profile_nll(values):
                eta = g_value * (matrix @ values)
                return float(np.sum(eta[obs_gaps]) - np.sum(np.log(-np.expm1(-eta[~obs_gaps]))))
            fit = minimize(profile_nll, np.full(n_layers, max(mu, 1e-3)), bounds=[(0.0, None)] * n_layers, method="L-BFGS-B")
            if fit.success and np.all(np.isfinite(fit.x)):
                layer_mu = fit.x
                base["pai_profile_converged"] = True
                total = float(np.sum(layer_mu * np.diff(edges)))
                base["pai_from_layers_m2_m2"] = total
                base["pai_profile_vs_whole_difference"] = total - base["pai_whole_box_m2_m2"]

        if include_layer_columns:
            for i, (bottom, top) in enumerate(zip(edges[:-1], edges[1:])):
                label = f"{round(bottom * 100):03d}_{round(top * 100):03d}"
                paths = matrix[:, i]
                base[f"pai_layer_{label}_bottom_m"] = float(bottom)
                base[f"pai_layer_{label}_top_m"] = float(top)
                base[f"pai_layer_{label}_pad_m2_m3"] = float(layer_mu[i])
                base[f"pai_layer_{label}_pai_m2_m2"] = float(layer_mu[i] * (top - bottom))
                base[f"pai_layer_{label}_mean_path_m"] = float(np.mean(paths[paths > 0])) if np.any(paths > 0) else 0.0
                base[f"pai_layer_{label}_total_path_m"] = float(np.sum(paths))
                base[f"pai_layer_{label}_n_rays_with_path"] = int(np.sum(paths > 0))

    if run_conditional_profile:
        candidate = intersects
        candidate_origins = np.asarray(origins_m, dtype=float)[candidate]
        candidate_directions = directions[candidate]
        candidate_ranges = np.asarray(ranges_m, dtype=float)[candidate]
        candidate_raw_hits = np.asarray(raw_hit_mask, dtype=bool)[candidate]
        conditional_pai = []
        layer_rows = []
        for bottom, top in zip(edges[:-1], edges[1:]):
            label = f"{round(bottom * 100):03d}_{round(top * 100):03d}"
            layer = Box3D(box.x_min, box.x_max, float(bottom), float(top), box.z_min, box.z_max)
            layer_intersects, layer_observed, layer_hits, layer_gaps, layer_censored, layer_chord = _classify_normalized_rays(
                candidate_origins, candidate_directions, candidate_ranges, candidate_raw_hits, layer
            )
            observed_chord = layer_chord[layer_observed]
            observed_gaps = layer_gaps[layer_observed]
            pad, _, converged, saturated = _fit_transmission(observed_chord, observed_gaps, g_value)
            layer_pai = pad * (top - bottom) if np.isfinite(pad) else np.nan
            if np.isfinite(layer_pai) and not np.isclose(layer_pai, pad * (top - bottom)):
                raise AssertionError("Layer PAI must equal PAD times layer thickness")
            conditional_pai.append(layer_pai)
            n_observed_layer = int(layer_observed.sum())
            n_gaps_layer = int(layer_gaps.sum())
            if include_layer_columns or diagnostic:
                layer_rows.append({
                    "layer_bottom_m": float(bottom), "layer_top_m": float(top),
                    "layer_mid_m": float((bottom + top) / 2.0),
                    "layer_thickness_m": float(top - bottom),
                    "pad_layer_m2_m3": pad, "pai_layer_m2_m2": layer_pai,
                    "n_rays_intersecting": int(layer_intersects.sum()),
                    "n_rays_observed": n_observed_layer,
                    "n_hits": int(layer_hits.sum()), "n_gap_rays": n_gaps_layer,
                    "n_rays_rejected_before_layer": int(layer_censored.sum()),
                    "gap_fraction": n_gaps_layer / n_observed_layer if n_observed_layer else np.nan,
                    "converged": converged, "all_hits": saturated,
                })
            if include_layer_columns:
                base[f"pai_layer_{label}_conditional_pad_m2_m3"] = pad
                base[f"pai_layer_{label}_conditional_pai_m2_m2"] = layer_pai
                base[f"pai_layer_{label}_conditional_n_intersecting"] = int(layer_intersects.sum())
                base[f"pai_layer_{label}_conditional_n_observed"] = n_observed_layer
                base[f"pai_layer_{label}_conditional_n_hits"] = int(layer_hits.sum())
                base[f"pai_layer_{label}_conditional_n_gaps"] = n_gaps_layer
                base[f"pai_layer_{label}_conditional_n_censored"] = int(layer_censored.sum())
                base[f"pai_layer_{label}_conditional_gap_fraction"] = n_gaps_layer / n_observed_layer if n_observed_layer else np.nan
                base[f"pai_layer_{label}_conditional_converged"] = converged
                base[f"pai_layer_{label}_conditional_saturated"] = saturated
        values = np.asarray(conditional_pai)
        complete = bool(values.size and np.all(np.isfinite(values)))
        integrated = float(np.sum(values)) if complete else np.nan
        if complete and not np.isclose(integrated, np.sum(values)):
            raise AssertionError("Total PAI must equal the sum of layer PAI")
        base["pai_conditional_profile_complete"] = complete
        base["pai_conditional_from_layers_m2_m2"] = integrated
        base["pai_m2_m2"] = integrated
        if layer_rows:
            base["_pai_layers"] = layer_rows
    return base
