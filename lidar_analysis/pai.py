from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar

try:
    from .fad import Box3D, _prepare_directions, box_is_valid, make_layer_edges, ray_box_intersection
    from .mta import classify_first_events
except ImportError:
    from fad import Box3D, _prepare_directions, box_is_valid, make_layer_edges, ray_box_intersection
    from mta import classify_first_events


def _classify_rays(
    origins_m, directions_m, ranges_m, raw_hit_mask, box,
    explicit_no_return_mask=None, max_observation_range_m=60.0,
    tolerance_m=1e-4, normalize_directions=True,
):
    origins = np.asarray(origins_m, dtype=float)
    ranges = np.asarray(ranges_m, dtype=float)
    raw_hits = np.asarray(raw_hit_mask, dtype=bool)
    no_returns = (
        (~raw_hits & np.isinf(ranges))
        if explicit_no_return_mask is None
        else np.asarray(explicit_no_return_mask, dtype=bool)
    )
    events = classify_first_events(
        origins_m=origins,
        directions_m=directions_m,
        ranges_m=ranges,
        raw_hit_mask=raw_hits,
        explicit_no_return_mask=no_returns,
        box=box,
        max_observation_range_m=max_observation_range_m,
        tolerance_m=tolerance_m,
        normalize_directions=normalize_directions,
    )
    chord = np.clip(events["exit_m"] - events["entry_m"], 0.0, None)
    return (
        events["directions"], events["intersects"], events["observed"],
        events["hit"], events["gap"], events["before"], events["unknown"], chord,
    )


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


def _first_event_layer_paths(
    origins_m: np.ndarray,
    events: dict[str, np.ndarray],
    layer_edges_y_m: np.ndarray,
) -> np.ndarray:
    """Observed path in each height layer, ending at the first return or box exit."""
    origins = np.asarray(origins_m, dtype=float)
    directions = np.asarray(events["directions"], dtype=float)
    edges = np.asarray(layer_edges_y_m, dtype=float)
    observed = np.asarray(events["observed"], dtype=bool)
    entry = np.asarray(events["entry_m"], dtype=float)
    stop = np.minimum(
        entry + np.asarray(events["path_m"], dtype=float),
        np.asarray(events["exit_m"], dtype=float),
    )
    matrix = np.zeros((len(origins), len(edges) - 1), dtype=float)

    vertical = directions[:, 1]
    moving = observed & (np.abs(vertical) > 1e-12)
    for index, (bottom, top) in enumerate(zip(edges[:-1], edges[1:])):
        first = np.full(len(origins), np.inf, dtype=float)
        last = np.full(len(origins), -np.inf, dtype=float)
        first[moving] = np.minimum(
            (bottom - origins[moving, 1]) / vertical[moving],
            (top - origins[moving, 1]) / vertical[moving],
        )
        last[moving] = np.maximum(
            (bottom - origins[moving, 1]) / vertical[moving],
            (top - origins[moving, 1]) / vertical[moving],
        )
        matrix[moving, index] = np.clip(
            np.minimum(last[moving], stop[moving])
            - np.maximum(first[moving], entry[moving]),
            0.0,
            None,
        )

    horizontal = observed & ~moving
    if np.any(horizontal):
        layer_index = np.searchsorted(edges, origins[horizontal, 1], side="right") - 1
        layer_index[np.isclose(origins[horizontal, 1], edges[-1])] = len(edges) - 2
        rows = np.flatnonzero(horizontal)
        valid = (layer_index >= 0) & (layer_index < len(edges) - 1)
        matrix[rows[valid], layer_index[valid]] = np.clip(
            stop[rows[valid]] - entry[rows[valid]], 0.0, None
        )
    return matrix


def compute_z_pai_traits(
    *, origins_m, directions_m, ranges_m, raw_hit_mask, box: Box3D,
    explicit_no_return_mask=None, max_observation_range_m: float | None = 60.0,
    g_function: str = "spherical", g_value: float = 0.5,
    layer_thickness_m: float = 0.1, include_layer_columns: bool = False,
    diagnostic: bool = False, normalize_directions: bool = True,
) -> dict[str, Any]:
    """Finite-box, fixed-G Zhao first-event maximum-likelihood PAI profile."""
    if str(g_function).strip().lower() != "spherical" or not np.isclose(float(g_value), 0.5):
        raise ValueError("Z_PAI requires the spherical G=0.5 assumption")

    n_total = len(np.asarray(origins_m))
    base: dict[str, Any] = {
        "z_pai_m2_m2": np.nan,
        "z_pai_height_m": box.y_max - box.y_min,
        "z_pai_layer_thickness_m": layer_thickness_m,
        "z_pai_n_layers": 0,
        "z_pai_n_supported_layers": 0,
        "z_pai_profile_support_fraction": 0.0,
        "z_pai_profile_complete": False,
        "z_pai_n_rays_total": n_total,
        "z_pai_n_rays_intersecting_box": 0,
        "z_pai_n_rays_observed": 0,
        "z_pai_n_hits": 0,
        "z_pai_n_full_gaps": 0,
        "z_pai_n_hits_before_box": 0,
        "z_pai_n_unknown": 0,
        "z_pai_total_observed_path_m": 0.0,
        "z_pai_log_likelihood": np.nan,
        "z_pai_g_function": "spherical",
        "z_pai_g_value": float(g_value),
    }
    if not box_is_valid(box):
        return base
    if layer_thickness_m is None:
        raise ValueError("Z_PAI requires pai_layer_thickness_m")

    edges = make_layer_edges(
        y_min_m=box.y_min, y_max_m=box.y_max,
        layer_thickness_m=float(layer_thickness_m),
    )
    base["z_pai_n_layers"] = len(edges) - 1
    raw_hits = np.asarray(raw_hit_mask, dtype=bool)
    ranges = np.asarray(ranges_m, dtype=float)
    no_returns = (
        (~raw_hits & np.isinf(ranges))
        if explicit_no_return_mask is None
        else np.asarray(explicit_no_return_mask, dtype=bool)
    )
    events = classify_first_events(
        origins_m=np.asarray(origins_m, dtype=float),
        directions_m=directions_m,
        ranges_m=ranges,
        raw_hit_mask=raw_hits,
        explicit_no_return_mask=no_returns,
        box=box,
        max_observation_range_m=max_observation_range_m,
        normalize_directions=normalize_directions,
    )
    paths = _first_event_layer_paths(np.asarray(origins_m, dtype=float), events, edges)
    observed_path = np.clip(
        np.minimum(events["entry_m"] + events["path_m"], events["exit_m"])
        - events["entry_m"],
        0.0,
        None,
    )
    expected_path = float(np.sum(observed_path[events["observed"]]))
    if not np.isclose(float(np.sum(paths)), expected_path, rtol=1e-9, atol=1e-9):
        raise AssertionError("Z_PAI layer paths must sum to observed first-event path")

    hit_layer = np.full(n_total, -1, dtype=int)
    hit_rows = np.flatnonzero(events["hit"])
    if hit_rows.size:
        stop = np.minimum(events["entry_m"] + events["path_m"], events["exit_m"])
        hit_y = (
            np.asarray(origins_m, dtype=float)[hit_rows, 1]
            + events["directions"][hit_rows, 1] * stop[hit_rows]
        )
        hit_y = np.clip(hit_y, edges[0], edges[-1])
        indices = np.searchsorted(edges, hit_y, side="right") - 1
        indices[np.isclose(hit_y, edges[-1])] = len(edges) - 2
        for edge_index, edge in enumerate(edges[1:-1], start=1):
            boundary = np.isclose(hit_y, edge, rtol=0.0, atol=1e-8)
            indices[boundary & (events["directions"][hit_rows, 1] > 0.0)] = edge_index - 1
        hit_layer[hit_rows] = indices

    thicknesses = np.diff(edges)
    layer_pai = np.full(len(thicknesses), np.nan)
    layer_rows = []
    log_likelihood = 0.0
    for index, (bottom, top, thickness) in enumerate(zip(edges[:-1], edges[1:], thicknesses)):
        exposure = float(np.sum(paths[:, index]))
        hits = int(np.sum(hit_layer == index))
        pad = hits / (float(g_value) * exposure) if exposure > 0.0 else np.nan
        layer_pai[index] = pad * thickness if np.isfinite(pad) else np.nan
        layer_log_likelihood = (
            hits * np.log(float(g_value) * pad) - float(g_value) * pad * exposure
            if hits > 0 and np.isfinite(pad) else 0.0
        )
        log_likelihood += layer_log_likelihood
        if include_layer_columns:
            label = f"{round(bottom * 100):03d}_{round(top * 100):03d}"
            base[f"z_pai_layer_{label}_m2_m2"] = float(layer_pai[index])
        if diagnostic:
            layer_rows.append({
                "layer_bottom_m": float(bottom),
                "layer_top_m": float(top),
                "layer_thickness_m": float(thickness),
                "pad_layer_m2_m3": float(pad),
                "pai_layer_m2_m2": float(layer_pai[index]),
                "n_rays_observed": int(np.sum(paths[:, index] > 0.0)),
                "n_hits": hits,
                "total_observed_path_m": exposure,
                "layer_log_likelihood": float(layer_log_likelihood),
            })

    supported = np.isfinite(layer_pai)
    complete = bool(layer_pai.size and np.all(supported))
    base.update({
        "z_pai_m2_m2": float(np.sum(layer_pai)) if complete else np.nan,
        "z_pai_n_supported_layers": int(np.sum(supported)),
        "z_pai_profile_support_fraction": float(np.sum(thicknesses[supported]) / np.sum(thicknesses)),
        "z_pai_profile_complete": complete,
        "z_pai_n_rays_intersecting_box": int(np.sum(events["intersects"])),
        "z_pai_n_rays_observed": int(np.sum(events["observed"])),
        "z_pai_n_hits": int(np.sum(events["hit"])),
        "z_pai_n_full_gaps": int(np.sum(events["gap"])),
        "z_pai_n_hits_before_box": int(np.sum(events["before"])),
        "z_pai_n_unknown": int(np.sum(events["unknown"])),
        "z_pai_total_observed_path_m": float(np.sum(paths)),
        "z_pai_log_likelihood": float(log_likelihood) if np.any(supported) else np.nan,
    })
    if layer_rows:
        base["_z_pai_layers"] = layer_rows
    return base


def layer_path_matrix(origins_m, directions_m, box: Box3D, layer_edges_y_m, *, normalize_directions=True):
    origins = np.asarray(origins_m, dtype=float)
    directions, valid = _prepare_directions(directions_m, normalize=normalize_directions)
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
    explicit_no_return_mask=None, max_observation_range_m: float | None = 60.0,
    g_function: str = "spherical", g_value: float = 0.5,
    layer_thickness_m: float | None = 0.1, include_layer_columns: bool = True,
    run_conditional_profile: bool = False,
    run_joint_profile: bool = False,
    diagnostic: bool = False,
    normalize_directions: bool = True,
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
        "pai_n_hits_before_box": 0, "pai_n_unknown": 0,
        "pai_max_observation_range_m": max_observation_range_m,
        "pai_reach_fraction": np.nan,
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

    directions, intersects, observed, hits, gaps, prehit, unknown, chord = _classify_rays(
        origins_m, directions_m, ranges_m, raw_hit_mask, box,
        explicit_no_return_mask=explicit_no_return_mask,
        max_observation_range_m=max_observation_range_m,
        normalize_directions=normalize_directions,
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
        "pai_n_unknown": int(unknown.sum()),
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
        matrix = layer_path_matrix(
            np.asarray(origins_m)[observed], directions[observed], box, edges,
            normalize_directions=False,
        )
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
        candidate_no_returns = (
            (~np.asarray(raw_hit_mask, dtype=bool) & np.isinf(np.asarray(ranges_m, dtype=float)))[candidate]
            if explicit_no_return_mask is None
            else np.asarray(explicit_no_return_mask, dtype=bool)[candidate]
        )
        conditional_pai = []
        layer_rows = []
        for bottom, top in zip(edges[:-1], edges[1:]):
            label = f"{round(bottom * 100):03d}_{round(top * 100):03d}"
            layer = Box3D(box.x_min, box.x_max, float(bottom), float(top), box.z_min, box.z_max)
            (
                _, layer_intersects, layer_observed, layer_hits, layer_gaps,
                layer_censored, layer_unknown, layer_chord,
            ) = _classify_rays(
                candidate_origins, candidate_directions, candidate_ranges,
                candidate_raw_hits, layer,
                explicit_no_return_mask=candidate_no_returns,
                max_observation_range_m=max_observation_range_m,
                normalize_directions=False,
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
                    "n_rays_unknown": int(layer_unknown.sum()),
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
                base[f"pai_layer_{label}_conditional_n_unknown"] = int(layer_unknown.sum())
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
