#!/usr/bin/env python3
"""Read-only PAI/Z-PAI side-bias audit for the local al_lai density_test data."""

from __future__ import annotations

import contextlib
import copy
import gc
import io
import json
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from lidar_analysis import central_runner
from lidar_analysis import pipeline_core as pc
from lidar_analysis.fad import Box3D, make_layer_edges, ray_box_intersection
from lidar_analysis.mta import classify_first_events
from lidar_analysis.pai import _first_event_layer_paths, _fit_transmission


DATA_ROOT = Path("/media/central/raw_mirror/al_lai/density_test")
SOURCE = DATA_ROOT / "source"
OUT = Path(__file__).resolve().parent
SCRATCH = Path("/tmp/pai_side_bias_audit")
SCRATCH.mkdir(parents=True, exist_ok=True)
RNG_SEED = 20260917


def load_inputs():
    with (SOURCE / "experiment_config.yaml").open(encoding="utf-8") as f:
        experiment_config = yaml.safe_load(f)
    analysis = central_runner.extract_analysis_cfg(experiment_config)
    calibration = central_runner.read_calibration_from_cart_config(SOURCE / "cart_config.yaml")
    cfg = central_runner.build_config(
        analysis,
        force=False,
        cart_id=calibration["cart_id"],
        data_dir=SOURCE,
    )
    results = pd.read_csv(DATA_ROOT / "results.csv")
    diagnostics = pd.read_csv(DATA_ROOT / "ray_box_diagnostics.csv")
    current_keys = results[["scan_name", "side"]].drop_duplicates()
    current = diagnostics.merge(current_keys, on=["scan_name", "side"], how="inner")
    summary = current[current["diagnostic_type"].eq("summary")].copy()
    if len(summary) != len(results) or summary.groupby(["scan_name", "side"]).size().max() != 1:
        raise AssertionError("Current result keys do not select exactly one diagnostic summary each")
    return experiment_config, cfg, calibration, results, current, summary


def scan_number(scan_name: str) -> int:
    return int(scan_name.split("_", 2)[1])


def scan_paths(number: int) -> tuple[str, Path, Path]:
    prefix = f"scan_{number:03d}_multi02_2026_07_23_Additional_Scans"
    return prefix, SOURCE / f"{prefix}_lidar.csv", SOURCE / f"{prefix}_pico.csv"


def process_kwargs(cfg, calibration):
    row_width_m = pc._to_m_units(cfg.row_width_u, cfg.dim_units)
    start_m = None if cfg.start_u is None else pc._to_m_units(cfg.start_u, cfg.dim_units)
    end_buffer_m = pc._to_m_units(cfg.end_buffer_u, cfg.dim_units)
    max_y_m = None if cfg.max_y_u is None else pc._to_m_units(cfg.max_y_u, cfg.dim_units)
    x_min_m = None if cfg.x_min_u is None else pc._to_m_units(cfg.x_min_u, cfg.dim_units)
    min_radius_m = None if cfg.min_radius_u is None else pc._to_m_units(cfg.min_radius_u, cfg.dim_units)
    return {
        "out_dir": str(SCRATCH),
        "cfg": cfg,
        "width_mm": row_width_m * 1000.0,
        "start_mm_global": 0.0 if start_m is None else start_m * 1000.0,
        "end_buffer_mm": end_buffer_m * 1000.0,
        "y_max_mm": None if max_y_m is None else max_y_m * 1000.0,
        "x_min_mm": None if x_min_m is None else x_min_m * 1000.0,
        "min_radius_mm": None if min_radius_m is None else min_radius_m * 1000.0,
        "step_mm": calibration["step_mm"],
        "lidar_height_mm": calibration["lidar_height_mm"],
        "lidar_wheel_offset_mm": calibration["lidar_wheel_offset_mm"],
        "roll_offset": calibration["roll_offset_deg"],
        "pitch_offset": calibration["pitch_offset_deg"],
        "imu_offset_mm": np.asarray(calibration["imu_offset_mm"], dtype=float),
    }


def classify(shared):
    return classify_first_events(
        origins_m=shared.origins_m,
        directions_m=shared.directions_m,
        ranges_m=shared.ranges_m,
        raw_hit_mask=shared.raw_hit_mask,
        explicit_no_return_mask=shared.explicit_no_return_mask,
        box=shared.box,
        max_observation_range_m=60.0,
        normalize_directions=shared.normalize_directions,
    )


def q(values, probability):
    values = np.asarray(values, dtype=float)
    return float(np.quantile(values, probability)) if values.size else np.nan


def event_record(scan_name, plot, shared, events):
    side = str(plot.side_label)
    box = shared.box
    observed = events["observed"]
    before = events["before"]
    hits = events["hit"]
    gaps = events["gap"]
    unknown = events["unknown"]
    intersects = events["intersects"]
    chord = np.clip(events["exit_m"] - events["entry_m"], 0.0, None)
    points = 0 if plot.analysis_target is None else len(plot.analysis_target.current_points)
    n_observed = int(observed.sum())
    return {
        "scan_name": scan_name,
        "scan_number": scan_number(scan_name),
        "plot": int(plot.letter),
        "side": side,
        "processed_points": points,
        "raw_rays_total": len(shared.ranges_m),
        "raw_returns": int(shared.raw_hit_mask.sum()),
        "rays_intersecting": int(intersects.sum()),
        "hits_before_box": int(before.sum()),
        "rays_observed": n_observed,
        "within_box_hits": int(hits.sum()),
        "full_gaps": int(gaps.sum()),
        "unknown": int(unknown.sum()),
        "pre_box_fraction": float(before.sum() / intersects.sum()),
        "reach_fraction": float(observed.sum() / intersects.sum()),
        "gap_fraction": float(gaps.sum() / observed.sum()),
        "hit_fraction": float(hits.sum() / observed.sum()),
        "mean_chord_m": float(chord[observed].mean()),
        "median_chord_m": float(np.median(chord[observed])),
        "total_geometric_chord_m": float(chord[observed].sum()),
        "total_observed_path_m": float(events["path_m"][observed].sum()),
        "observed_path_per_ray_m": float(events["path_m"][observed].sum() / n_observed),
        "box_x_min_m": box.x_min,
        "box_x_max_m": box.x_max,
        "box_y_min_m": box.y_min,
        "box_y_max_m": box.y_max,
        "box_z_min_m": box.z_min,
        "box_z_max_m": box.z_max,
    }


def prebox_record(scan_name, plot, shared, events, samples):
    before = events["before"]
    directions = events["directions"][before]
    origins = np.asarray(shared.origins_m, dtype=float)[before]
    ranges = np.asarray(shared.ranges_m, dtype=float)[before]
    entry = events["entry_m"][before]
    first = origins + directions * ranges[:, None]
    entry_xyz = origins + directions * entry[:, None]
    shortfall = entry - ranges
    azimuth = np.degrees(np.arctan2(directions[:, 0], directions[:, 2]))
    elevation = np.degrees(np.arcsin(np.clip(directions[:, 1], -1.0, 1.0)))
    box = shared.box
    faces = np.column_stack([
        np.abs(entry_xyz[:, 0] - box.x_min), np.abs(entry_xyz[:, 0] - box.x_max),
        np.abs(entry_xyz[:, 1] - box.y_min), np.abs(entry_xyz[:, 1] - box.y_max),
        np.abs(entry_xyz[:, 2] - box.z_min), np.abs(entry_xyz[:, 2] - box.z_max),
    ])
    face_names = np.asarray(["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"])
    entry_face = face_names[np.argmin(faces, axis=1)]
    yz_aligned = (
        (first[:, 1] >= box.y_min) & (first[:, 1] <= box.y_max)
        & (first[:, 2] >= box.z_min) & (first[:, 2] <= box.z_max)
    )
    near_face_name = "x_min" if plot.side_label == "right" else "x_max"
    near_face = entry_face == near_face_name
    n = len(ranges)
    rng = np.random.default_rng(RNG_SEED + 10 * scan_number(scan_name) + (plot.side_label == "right"))
    chosen = rng.choice(n, size=min(n, 5_000), replace=False) if n else np.empty(0, dtype=int)
    samples.append(pd.DataFrame({
        "scan_name": scan_name,
        "scan_number": scan_number(scan_name),
        "side": plot.side_label,
        "azimuth_deg": azimuth[chosen],
        "elevation_deg": elevation[chosen],
        "entry_distance_m": entry[chosen],
        "first_return_distance_m": ranges[chosen],
        "shortfall_m": shortfall[chosen],
        "first_x_m": first[chosen, 0],
        "first_y_m": first[chosen, 1],
        "first_z_m": first[chosen, 2],
        "entry_face": entry_face[chosen],
    }))
    return {
        "scan_name": scan_name,
        "scan_number": scan_number(scan_name),
        "side": plot.side_label,
        "n_prebox": n,
        "azimuth_median_deg": q(azimuth, 0.5),
        "elevation_median_deg": q(elevation, 0.5),
        "entry_distance_median_m": q(entry, 0.5),
        "first_return_distance_median_m": q(ranges, 0.5),
        "shortfall_p05_m": q(shortfall, 0.05),
        "shortfall_median_m": q(shortfall, 0.5),
        "shortfall_p95_m": q(shortfall, 0.95),
        "first_x_median_m": q(first[:, 0], 0.5),
        "first_y_median_m": q(first[:, 1], 0.5),
        "first_z_median_m": q(first[:, 2], 0.5),
        "fraction_entry_near_x_face": float(np.mean(near_face)),
        "fraction_first_return_yz_aligned": float(np.mean(yz_aligned)),
        "fraction_within_0p25m_of_entry": float(np.mean(shortfall <= 0.25)),
        "fraction_within_0p50m_of_entry": float(np.mean(shortfall <= 0.50)),
        "fraction_near_face_yz_and_0p50m": float(np.mean(near_face & yz_aligned & (shortfall <= 0.50))),
    }


def save_representative(shared, events, key):
    intersects = events["intersects"]
    path = SCRATCH / f"representative_scan_{key[0]:02d}_{key[1]}.npz"
    np.savez(
        path,
        origins=np.asarray(shared.origins_m, dtype=np.float32)[intersects],
        directions=np.asarray(events["directions"], dtype=np.float32)[intersects],
        ranges=np.asarray(shared.ranges_m, dtype=np.float32)[intersects],
        raw_hits=np.asarray(shared.raw_hit_mask, dtype=np.uint8)[intersects],
        no_returns=np.asarray(shared.explicit_no_return_mask, dtype=np.uint8)[intersects],
        box=np.asarray([
            shared.box.x_min, shared.box.x_max, shared.box.y_min,
            shared.box.y_max, shared.box.z_min, shared.box.z_max,
        ]),
    )
    return path


def run_scan(number, cfg, calibration, handler):
    name, lidar, pico = scan_paths(number)
    captured = []
    original = pc._build_shared_ray_box

    def wrapped(plot, fused_np, active_cfg, row_options, step_mm, lidar_height_mm, roll_offset, pitch_offset):
        shared = original(
            plot, fused_np, active_cfg, row_options, step_mm,
            lidar_height_mm, roll_offset, pitch_offset,
        )
        captured.append(handler(name, plot, shared, fused_np))
        return shared

    pc._build_shared_ray_box = wrapped
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rows = pc.process_scan(
                scan_base=name,
                lidar_path=str(lidar),
                pico_path=str(pico),
                **process_kwargs(cfg, calibration),
            )
    finally:
        pc._build_shared_ray_box = original
    with (OUT / "processing.log").open("a", encoding="utf-8") as f:
        f.write(output.getvalue())
    if len(rows) != len(captured):
        raise AssertionError(f"Capture/result mismatch for {name}: {len(captured)} vs {len(rows)}")
    return rows, captured


def choose_representatives(summary):
    pair_mean = summary.groupby("scan_number")["pai_m2_m2"].mean().sort_values()
    chosen_scans = [
        int(pair_mean.index[0]),
        int((pair_mean - pair_mean.median()).abs().idxmin()),
        int(pair_mean.index[-1]),
    ]
    labels = ["low", "medium", "high"]
    representatives = {}
    for label, number in zip(labels, chosen_scans):
        pair = summary[summary["scan_number"].eq(number)].copy()
        rich = pair.sort_values("pai_n_rays_observed").iloc[-1]
        poor = pair.sort_values("pai_n_rays_observed").iloc[0]
        representatives[(number, str(rich["side"]))] = {
            "density_level": label,
            "pair_mean_pai": float(pair["pai_m2_m2"].mean()),
            "baseline_pai": float(rich["pai_m2_m2"]),
            "baseline_z_pai": float(rich["z_pai_m2_m2"]),
            "baseline_observed": int(rich["pai_n_rays_observed"]),
            "poor_side": str(poor["side"]),
            "poor_observed": int(poor["pai_n_rays_observed"]),
        }
    return representatives


def layer_sufficient_arrays(data, layer_thickness=0.1):
    origins = data["origins"].astype(float, copy=False)
    directions = data["directions"].astype(float, copy=False)
    ranges = data["ranges"].astype(float, copy=False)
    raw_hits = data["raw_hits"].astype(bool, copy=False)
    no_returns = data["no_returns"].astype(bool, copy=False)
    values = data["box"]
    box = Box3D(values[0], values[1], values[2], values[3], values[4], values[5])
    events = classify_first_events(
        origins_m=origins, directions_m=directions, ranges_m=ranges,
        raw_hit_mask=raw_hits, explicit_no_return_mask=no_returns,
        box=box, max_observation_range_m=60.0, normalize_directions=False,
    )
    edges = make_layer_edges(y_min_m=box.y_min, y_max_m=box.y_max, layer_thickness_m=layer_thickness)
    conditional = []
    for bottom, top in zip(edges[:-1], edges[1:]):
        layer = Box3D(box.x_min, box.x_max, float(bottom), float(top), box.z_min, box.z_max)
        layer_events = classify_first_events(
            origins_m=origins, directions_m=directions, ranges_m=ranges,
            raw_hit_mask=raw_hits, explicit_no_return_mask=no_returns,
            box=layer, max_observation_range_m=60.0, normalize_directions=False,
        )
        conditional.append({
            "observed": layer_events["observed"],
            "gap": layer_events["gap"],
            "chord": np.asarray(
                np.clip(layer_events["exit_m"] - layer_events["entry_m"], 0.0, None),
                dtype=np.float32,
            ),
        })
        del layer_events
    z_paths = np.asarray(_first_event_layer_paths(origins, events, edges), dtype=np.float32)
    hit_layer = np.full(len(origins), -1, dtype=np.int16)
    hit_rows = np.flatnonzero(events["hit"])
    if hit_rows.size:
        stop = np.minimum(events["entry_m"] + events["path_m"], events["exit_m"])
        hit_y = origins[hit_rows, 1] + directions[hit_rows, 1] * stop[hit_rows]
        hit_y = np.clip(hit_y, edges[0], edges[-1])
        indices = np.searchsorted(edges, hit_y, side="right") - 1
        indices[np.isclose(hit_y, edges[-1])] = len(edges) - 2
        for edge_index, edge in enumerate(edges[1:-1], start=1):
            boundary = np.isclose(hit_y, edge, rtol=0.0, atol=1e-8)
            indices[boundary & (directions[hit_rows, 1] > 0.0)] = edge_index - 1
        hit_layer[hit_rows] = indices
    return box, edges, events, conditional, z_paths, hit_layer


def evaluate_subset(mask, edges, conditional, z_paths, hit_layer):
    layer_pai = []
    for layer, thickness in zip(conditional, np.diff(edges)):
        selected = mask & layer["observed"]
        mu, _, converged, saturated = _fit_transmission(
            layer["chord"][selected], layer["gap"][selected], 0.5
        )
        layer_pai.append(mu * thickness if converged and not saturated and np.isfinite(mu) else np.nan)
    z_layer_pai = []
    for index, thickness in enumerate(np.diff(edges)):
        exposure = float(z_paths[mask, index].sum(dtype=np.float64))
        hits = int(np.sum(mask & (hit_layer == index)))
        z_layer_pai.append(hits * thickness / (0.5 * exposure) if exposure > 0 else np.nan)
    return float(np.sum(layer_pai)) if np.all(np.isfinite(layer_pai)) else np.nan, float(np.sum(z_layer_pai)) if np.all(np.isfinite(z_layer_pai)) else np.nan


def propensity_scores(events):
    directions = events["directions"]
    chord = np.clip(events["exit_m"] - events["entry_m"], 0.0, None)
    features = [
        np.degrees(np.arctan2(directions[:, 0], directions[:, 2])),
        np.degrees(np.arcsin(np.clip(directions[:, 1], -1.0, 1.0))),
        events["entry_m"],
        chord,
    ]
    indices = []
    n_bins = 6
    for feature in features:
        edges = np.unique(np.quantile(feature[np.isfinite(feature)], np.linspace(0, 1, n_bins + 1)))
        if len(edges) < 3:
            indices.append(np.zeros(len(feature), dtype=np.int16))
        else:
            indices.append(np.clip(np.digitize(feature, edges[1:-1]), 0, len(edges) - 2))
    shape = tuple(int(index.max()) + 1 for index in indices)
    flat = np.ravel_multi_index(tuple(indices), shape)
    total = np.bincount(flat, minlength=int(np.prod(shape)))
    before = np.bincount(flat, weights=events["before"].astype(float), minlength=len(total))
    return (before[flat] + 1.0) / (total[flat] + 2.0)


def run_resampling(representatives, saved_paths):
    random_rows = []
    selective_rows = []
    for key, info in representatives.items():
        data = np.load(saved_paths[key])
        box, edges, events, conditional, z_paths, hit_layer = layer_sufficient_arrays(data)
        n = len(events["intersects"])
        baseline_mask = np.ones(n, dtype=bool)
        baseline_pai, baseline_z = evaluate_subset(baseline_mask, edges, conditional, z_paths, hit_layer)
        if not np.isclose(baseline_pai, info["baseline_pai"], atol=2e-3):
            raise AssertionError((key, baseline_pai, info["baseline_pai"]))
        if not np.isclose(baseline_z, info["baseline_z_pai"], atol=2e-3):
            raise AssertionError((key, baseline_z, info["baseline_z_pai"]))
        poor_fraction = info["poor_observed"] / info["baseline_observed"]
        fractions = [("75%", 0.75), ("50%", 0.50), ("25%", 0.25), ("poor_count", poor_fraction)]
        rng = np.random.default_rng(RNG_SEED + 100 * key[0])
        random_rows.append({
            **info, "scan_number": key[0], "side": key[1], "level": "baseline",
            "fraction": 1.0, "repeat": 0, "n_selected": n,
            "pai_m2_m2": baseline_pai, "z_pai_m2_m2": baseline_z,
        })
        for level, fraction in fractions:
            for repeat_index in range(10):
                mask = rng.random(n) < fraction
                pai, z_pai = evaluate_subset(mask, edges, conditional, z_paths, hit_layer)
                random_rows.append({
                    **info, "scan_number": key[0], "side": key[1], "level": level,
                    "fraction": fraction, "repeat": repeat_index + 1,
                    "n_selected": int(mask.sum()), "pai_m2_m2": pai, "z_pai_m2_m2": z_pai,
                })

        observed_idx = np.flatnonzero(events["observed"])
        remove_n = max(1, info["baseline_observed"] - info["poor_observed"])
        scores = propensity_scores(events)[observed_idx]
        weights = np.maximum(scores, 1e-12) ** 3
        weights /= weights.sum()
        for mode in ["random", "selective"]:
            for repeat_index in range(10):
                removed = rng.choice(
                    observed_idx,
                    size=remove_n,
                    replace=False,
                    p=weights if mode == "selective" else None,
                )
                mask = np.ones(n, dtype=bool)
                mask[removed] = False
                pai, z_pai = evaluate_subset(mask, edges, conditional, z_paths, hit_layer)
                selective_rows.append({
                    **info, "scan_number": key[0], "side": key[1], "mode": mode,
                    "repeat": repeat_index + 1, "n_removed": remove_n,
                    "removed_hit_fraction": float(events["hit"][removed].mean()),
                    "removed_gap_fraction": float(events["gap"][removed].mean()),
                    "removed_mean_chord_m": float(np.mean(events["exit_m"][removed] - events["entry_m"][removed])),
                    "pai_m2_m2": pai, "z_pai_m2_m2": z_pai,
                })
        removed = observed_idx[np.argpartition(scores, -remove_n)[-remove_n:]]
        mask = np.ones(n, dtype=bool)
        mask[removed] = False
        pai, z_pai = evaluate_subset(mask, edges, conditional, z_paths, hit_layer)
        selective_rows.append({
            **info, "scan_number": key[0], "side": key[1], "mode": "selective_top_score",
            "repeat": 1, "n_removed": remove_n,
            "removed_hit_fraction": float(events["hit"][removed].mean()),
            "removed_gap_fraction": float(events["gap"][removed].mean()),
            "removed_mean_chord_m": float(np.mean(events["exit_m"][removed] - events["entry_m"][removed])),
            "pai_m2_m2": pai, "z_pai_m2_m2": z_pai,
        })
        data.close()
        del conditional, z_paths, hit_layer, events
        gc.collect()
    return pd.DataFrame(random_rows), pd.DataFrame(selective_rows)


def run_row2(cfg, calibration):
    marker_cfg = replace(
        cfg,
        split_source="marks",
        mark_target_type="plot",
        mark_z_buffer_u=0.1,
        missing_mark_file="error",
        empty_mark_file="error",
        free_marks_as="none",
    )
    records = []
    for number in (1, 2):
        def handler(scan_name, plot, shared, fused_np):
            events = classify(shared)
            return event_record(scan_name, plot, shared, events)

        rows, captured = run_scan(number, marker_cfg, calibration, handler)
        for rec, traits in zip(captured, rows):
            rec["pai_m2_m2"] = traits["pai_m2_m2"]
            rec["z_pai_m2_m2"] = traits["z_pai_m2_m2"]
            records.append(rec)
    frame = pd.DataFrame(records)
    paired = []
    for assignment, odd_side, even_side in [
        ("odd_right_even_left", "right", "left"),
        ("odd_left_even_right", "left", "right"),
    ]:
        for odd_plot in range(1, 8):
            even_plot = 8 - odd_plot
            odd = frame[(frame.scan_number == 1) & (frame.side == odd_side) & (frame["plot"] == odd_plot)].iloc[0]
            even = frame[(frame.scan_number == 2) & (frame.side == even_side) & (frame["plot"] == even_plot)].iloc[0]
            row = {"assignment": assignment, "odd_plot": odd_plot, "even_plot": even_plot}
            for metric in [
                "processed_points", "rays_intersecting", "pre_box_fraction", "reach_fraction",
                "gap_fraction", "mean_chord_m", "observed_path_per_ray_m", "pai_m2_m2", "z_pai_m2_m2",
            ]:
                row[f"odd_{metric}"] = odd[metric]
                row[f"even_{metric}"] = even[metric]
                row[f"difference_{metric}"] = odd[metric] - even[metric]
                denom = (abs(odd[metric]) + abs(even[metric])) / 2
                row[f"relative_difference_{metric}"] = (odd[metric] - even[metric]) / denom if denom else np.nan
            paired.append(row)
    return frame, pd.DataFrame(paired)


def geometry_checks(cfg, calibration):
    rng = np.random.default_rng(RNG_SEED)
    n = 100_000
    origins = np.column_stack([np.zeros(n), rng.uniform(-0.1, 1.0, n), rng.uniform(0.0, 17.0, n)])
    right_directions = rng.normal(size=(n, 3))
    right_directions[:, 0] = np.abs(right_directions[:, 0]) + 0.1
    right_directions /= np.linalg.norm(right_directions, axis=1)[:, None]
    left_directions = right_directions.copy()
    left_directions[:, 0] *= -1
    right_box = Box3D(0.4, 1.5, -0.1, 1.0, 0.0, 17.0)
    left_box = Box3D(-1.5, -0.4, -0.1, 1.0, 0.0, 17.0)
    right = ray_box_intersection(origins_m=origins, directions_unit=right_directions, box=right_box)
    left = ray_box_intersection(origins_m=origins, directions_unit=left_directions, box=left_box)
    return {
        "synthetic_intersection_masks_equal": bool(np.array_equal(right[2], left[2])),
        "synthetic_max_entry_difference_m": float(np.max(np.abs(right[0] - left[0]))),
        "synthetic_max_exit_difference_m": float(np.max(np.abs(right[1] - left[1]))),
        "left_box_width_m": left_box.x_max - left_box.x_min,
        "right_box_width_m": right_box.x_max - right_box.x_min,
        "fixed_lidar_x_offset_m": 0.0,
    }


def make_plots(summary, samples, random_df, selective_df, row2_pairs, variant):
    colors = {"left": "#2c7fb8", "right": "#d95f0e"}
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    relationships = [
        ("pai_gap_fraction", "Gap fraction"),
        ("pai_n_full_gaps", "Full gaps"),
        ("pai_reach_fraction", "Reach fraction"),
        ("pre_box_fraction", "Pre-box fraction"),
        ("z_pai_total_observed_path_m", "Observed path (m)"),
        ("observed_path_per_ray_m", "Observed path/ray (m)"),
    ]
    for ax, (column, label) in zip(axes.flat, relationships):
        for side, group in summary.groupby("side"):
            ax.scatter(group[column], group["pai_m2_m2"], label=side, color=colors[side], s=42)
        ax.set_xlabel(label)
        ax.set_ylabel("PAI")
        ax.grid(alpha=0.2)
    axes[0, 0].legend()
    fig.savefig(OUT / "pai_relationships.png", dpi=180)
    plt.close(fig)

    pivots = []
    for metric in ["pre_box_fraction", "pai_reach_fraction", "pai_gap_fraction", "pai_m2_m2", "z_pai_m2_m2"]:
        pivot = summary.pivot(index="scan_number", columns="side", values=metric)
        pivots.append((metric, pivot))
    fig, axes = plt.subplots(5, 1, figsize=(12, 14), sharex=True, constrained_layout=True)
    for ax, (metric, pivot) in zip(axes, pivots):
        for side in ["left", "right"]:
            ax.plot(pivot.index, pivot[side], marker="o", color=colors[side], label=side)
        ax.set_ylabel(metric.replace("pai_", "").replace("_", " "))
        ax.grid(alpha=0.2)
    axes[0].legend(ncol=2)
    axes[-1].set_xlabel("Scan number")
    fig.savefig(OUT / "left_right_chain.png", dpi=180)
    plt.close(fig)

    focus = samples[samples.scan_number.eq(8)]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    for column, ax in zip(["first_x_m", "first_y_m"], axes[0]):
        for side, group in focus.groupby("side"):
            ax.hist(group[column], bins=80, density=True, alpha=0.55, color=colors[side], label=side)
        ax.set_xlabel(column)
        ax.set_ylabel("density")
    for side, group in focus.groupby("side"):
        axes[1, 0].scatter(group["azimuth_deg"], group["elevation_deg"], s=1, alpha=0.08, color=colors[side], label=side)
        axes[1, 1].hist(group["shortfall_m"], bins=np.linspace(0, min(2.0, focus.shortfall_m.quantile(0.99)), 80), density=True, alpha=0.55, color=colors[side])
    axes[1, 0].set(xlabel="azimuth (deg)", ylabel="elevation (deg)")
    axes[1, 1].set(xlabel="entry minus first-return distance (m)", ylabel="density")
    axes[0, 0].legend()
    fig.savefig(OUT / "prebox_spatial_scan08.png", dpi=180)
    plt.close(fig)

    summarized = random_df.groupby(["density_level", "level"], as_index=False).agg(
        fraction=("fraction", "mean"), pai_mean=("pai_m2_m2", "mean"), pai_sd=("pai_m2_m2", "std"),
        z_mean=("z_pai_m2_m2", "mean"), z_sd=("z_pai_m2_m2", "std"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for density_level, group in summarized.groupby("density_level"):
        group = group.sort_values("fraction")
        axes[0].errorbar(group.fraction, group.pai_mean, yerr=group.pai_sd.fillna(0), marker="o", label=density_level)
        axes[1].errorbar(group.fraction, group.z_mean, yerr=group.z_sd.fillna(0), marker="o", label=density_level)
    axes[0].set(xlabel="retained fraction", ylabel="PAI")
    axes[1].set(xlabel="retained fraction", ylabel="Z-PAI")
    for ax in axes: ax.grid(alpha=0.2)
    axes[0].legend()
    fig.savefig(OUT / "random_subsampling.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    modes = ["random", "selective", "selective_top_score"]
    selective_df.boxplot(column="pai_m2_m2", by=["density_level", "mode"], ax=axes[0], rot=35)
    selective_df.boxplot(column="z_pai_m2_m2", by=["density_level", "mode"], ax=axes[1], rot=35)
    axes[0].set_ylabel("PAI")
    axes[1].set_ylabel("Z-PAI")
    fig.suptitle("")
    fig.savefig(OUT / "selective_censoring.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for assignment, group in row2_pairs.groupby("assignment"):
        axes[0].scatter(group.odd_pai_m2_m2, group.even_pai_m2_m2, label=assignment)
        axes[1].scatter(group.odd_z_pai_m2_m2, group.even_z_pai_m2_m2, label=assignment)
    limits = [
        (min(row2_pairs.odd_pai_m2_m2.min(), row2_pairs.even_pai_m2_m2.min()), max(row2_pairs.odd_pai_m2_m2.max(), row2_pairs.even_pai_m2_m2.max())),
        (min(row2_pairs.odd_z_pai_m2_m2.min(), row2_pairs.even_z_pai_m2_m2.min()), max(row2_pairs.odd_z_pai_m2_m2.max(), row2_pairs.even_z_pai_m2_m2.max())),
    ]
    for ax, (lo, hi), label in zip(axes, limits, ["PAI", "Z-PAI"]):
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        ax.set(xlabel=f"odd-view {label}", ylabel=f"even-view {label}")
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=8)
    fig.savefig(OUT / "row2_opposite_views.png", dpi=180)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "processing.log").write_text("", encoding="utf-8")
    experiment_config, cfg, calibration, results, current, summary = load_inputs()
    for column in summary.columns:
        if column.startswith(("pai_", "z_pai_", "ray_box_")):
            summary[column] = pd.to_numeric(summary[column], errors="ignore")
    summary["scan_number"] = summary.scan_name.map(scan_number)
    summary["pre_box_fraction"] = summary.pai_n_hits_before_box / summary.pai_n_rays_intersecting_box
    summary["observed_path_per_ray_m"] = summary.z_pai_total_observed_path_m / summary.pai_n_rays_observed
    representatives = choose_representatives(summary)

    event_rows = []
    prebox_rows = []
    samples = []
    saved_paths = {}
    for number in range(1, 11):
        def handler(scan_name, plot, shared, fused_np):
            events = classify(shared)
            event_rows.append(event_record(scan_name, plot, shared, events))
            prebox_rows.append(prebox_record(scan_name, plot, shared, events, samples))
            key = (scan_number(scan_name), str(plot.side_label))
            if key in representatives:
                saved_paths[key] = save_representative(shared, events, key)
            return key

        run_scan(number, cfg, calibration, handler)
        gc.collect()

    events_df = pd.DataFrame(event_rows)
    prebox_df = pd.DataFrame(prebox_rows)
    samples_df = pd.concat(samples, ignore_index=True)
    merged = summary.merge(
        results[["scan_name", "side", "points", "point_density_m2"]],
        on=["scan_name", "side"], how="left",
    ).merge(events_df, on=["scan_name", "scan_number", "side"], how="left", suffixes=("", "_raw"))
    for left, right in [
        ("pai_n_rays_intersecting_box", "rays_intersecting"),
        ("pai_n_hits_before_box", "hits_before_box"),
        ("pai_n_rays_observed", "rays_observed"),
        ("pai_n_hits", "within_box_hits"),
        ("pai_n_full_gaps", "full_gaps"),
        ("pai_n_unknown", "unknown"),
    ]:
        if not np.array_equal(merged[left].astype(int), merged[right].astype(int)):
            raise AssertionError(f"Raw reconstruction does not match diagnostics for {left}")
    merged.to_csv(OUT / "summary_metrics.csv", index=False)
    prebox_df.to_csv(OUT / "prebox_spatial_summary.csv", index=False)
    samples_df.to_csv(OUT / "prebox_ray_sample.csv", index=False)

    side_diff = []
    metrics = [
        "points", "raw_returns", "pai_n_rays_total", "pai_n_rays_intersecting_box",
        "pai_n_hits_before_box", "pre_box_fraction", "pai_n_rays_observed", "pai_reach_fraction",
        "pai_n_full_gaps", "pai_n_hits", "pai_gap_fraction", "pai_hit_fraction",
        "pai_mean_chord_m", "pai_median_chord_m", "pai_total_geometric_chord_m",
        "z_pai_total_observed_path_m", "observed_path_per_ray_m", "pai_m2_m2", "z_pai_m2_m2",
    ]
    for number, group in merged.groupby("scan_number"):
        left = group[group.side.eq("left")].iloc[0]
        right = group[group.side.eq("right")].iloc[0]
        row = {"scan_number": number}
        for metric in metrics:
            row[f"left_{metric}"] = left[metric]
            row[f"right_{metric}"] = right[metric]
            row[f"right_minus_left_{metric}"] = right[metric] - left[metric]
        side_diff.append(row)
    pd.DataFrame(side_diff).to_csv(OUT / "side_differences.csv", index=False)

    random_df, selective_df = run_resampling(representatives, saved_paths)
    random_df.to_csv(OUT / "random_subsampling.csv", index=False)
    selective_df.to_csv(OUT / "selective_censoring.csv", index=False)

    row2_metrics, row2_pairs = run_row2(cfg, calibration)
    row2_metrics.to_csv(OUT / "row2_marker_metrics.csv", index=False)
    row2_pairs.to_csv(OUT / "row2_opposite_view_pairs.csv", index=False)

    noimu_cfg = replace(cfg, use_imu=False, use_heading=False, ray_box_ground_mode="global_y")
    variant_rows = []
    def variant_handler(scan_name, plot, shared, fused_np):
        events = classify(shared)
        return event_record(scan_name, plot, shared, events)
    traits, captured = run_scan(8, noimu_cfg, calibration, variant_handler)
    for rec, trait in zip(captured, traits):
        rec["pai_m2_m2"] = trait["pai_m2_m2"]
        rec["z_pai_m2_m2"] = trait["z_pai_m2_m2"]
        variant_rows.append(rec)
    variant = pd.DataFrame(variant_rows)
    variant.to_csv(OUT / "scan08_noimu_global_ground.csv", index=False)

    geometry = geometry_checks(cfg, calibration)
    (OUT / "geometry_checks.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
    (OUT / "representatives.json").write_text(
        json.dumps({f"scan_{k[0]:02d}_{k[1]}": v for k, v in representatives.items()}, indent=2) + "\n",
        encoding="utf-8",
    )
    make_plots(merged, samples_df, random_df, selective_df, row2_pairs, variant)

    metadata = {
        "data_root": str(DATA_ROOT),
        "current_scan_names": sorted(results.scan_name.unique().tolist()),
        "n_result_rows": len(results),
        "n_current_summary_rows": len(summary),
        "old_diagnostic_rows_excluded": int(len(pd.read_csv(DATA_ROOT / "ray_box_diagnostics.csv")) - len(current)),
        "random_seed": RNG_SEED,
        "algorithm_files_modified": False,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
