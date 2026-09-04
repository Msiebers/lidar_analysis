from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    from .fad import Box3D, _normalize_directions, box_is_valid, ray_box_intersection
except ImportError:
    from fad import Box3D, _normalize_directions, box_is_valid, ray_box_intersection


_MTA_POLY_COEFFS = (56.81964, 46.84833, -64.62133, -158.69141, 522.06260, 1008.14931)
_SLOPE_MIN = -0.6964
_SLOPE_MAX = 0.4431


def mta_from_g_slope(slope_per_rad: float) -> float:
    """LI-COR/Lang polynomial; MTA is degrees from horizontal."""
    slope = float(slope_per_rad)
    value = sum(coef * slope**power for power, coef in enumerate(_MTA_POLY_COEFFS))
    return float(np.clip(value, 0.0, 90.0))


def angle_bin_edges_deg(width_deg: float) -> np.ndarray:
    width = float(width_deg)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("mta_angle_bin_deg must be finite and greater than zero")
    edges = np.arange(0.0, 90.0, width, dtype=float)
    if edges.size == 0 or not np.isclose(edges[0], 0.0):
        edges = np.insert(edges, 0, 0.0)
    return np.append(edges, 90.0)


def fit_angle_bin_edges_deg(width_deg: float) -> np.ndarray:
    """Bins anchored at 25 degrees and ending exactly at 65 degrees."""
    width = float(width_deg)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("mta_angle_bin_deg must be finite and greater than zero")
    edges = np.arange(25.0, 65.0, width, dtype=float)
    return np.append(edges, 65.0)


def folded_zenith_deg(directions_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return folded zenith, vertical component, and valid-direction mask."""
    directions, valid = _normalize_directions(directions_m)
    vertical = directions[:, 1]
    folded = np.degrees(np.arccos(np.clip(np.abs(vertical), 0.0, 1.0)))
    folded[~valid] = np.nan
    return folded, vertical, valid


def angle_bin_indices(angles_deg: np.ndarray, edges_deg: np.ndarray) -> np.ndarray:
    """Half-open bins, except that the final bin includes 90 degrees."""
    angles = np.asarray(angles_deg, dtype=float)
    edges = np.asarray(edges_deg, dtype=float)
    indices = np.searchsorted(edges, angles + 1e-10, side="right") - 1
    indices[np.isclose(angles, edges[0], rtol=0.0, atol=1e-10)] = 0
    indices[np.isclose(angles, edges[-1], rtol=0.0, atol=1e-10)] = len(edges) - 2
    invalid = (~np.isfinite(angles)) | (angles < edges[0] - 1e-10) | (angles > edges[-1] + 1e-10)
    indices[invalid] = -1
    return indices


def _first_return_per_ray(
    origins: np.ndarray,
    directions: np.ndarray,
    ranges: np.ndarray,
    raw_hits: np.ndarray,
    explicit_no_returns: np.ndarray,
    ray_ids: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Collapse explicit duplicate echoes to the earliest physical return."""
    if ray_ids is None:
        return origins, directions, ranges, raw_hits, explicit_no_returns

    ray_ids = np.asarray(ray_ids)
    if ray_ids.shape != ranges.shape:
        raise ValueError("ray_ids must match the ray count")

    groups: dict[Any, list[int]] = {}
    for index, ray_id in enumerate(ray_ids.tolist()):
        groups.setdefault(ray_id, []).append(index)

    chosen: list[int] = []
    no_return: list[bool] = []
    for indices in groups.values():
        valid_returns = [i for i in indices if raw_hits[i] and np.isfinite(ranges[i]) and ranges[i] > 0.0]
        if valid_returns:
            chosen.append(min(valid_returns, key=lambda i: ranges[i]))
            no_return.append(False)
        else:
            chosen.append(indices[0])
            no_return.append(bool(np.any(explicit_no_returns[indices])))

    selected = np.asarray(chosen, dtype=int)
    selected_hits = raw_hits[selected] & np.isfinite(ranges[selected]) & (ranges[selected] > 0.0)
    return (
        origins[selected], directions[selected], ranges[selected], selected_hits,
        np.asarray(no_return, dtype=bool),
    )


def classify_first_events(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    raw_hit_mask: np.ndarray,
    explicit_no_return_mask: np.ndarray,
    box: Box3D,
    max_observation_range_m: float | None,
    ray_ids: np.ndarray | None = None,
    tolerance_m: float = 1e-4,
) -> dict[str, np.ndarray]:
    """Classify immutable raw beam observations against one bounded plot box."""
    origins = np.asarray(origins_m, dtype=float)
    directions = np.asarray(directions_m, dtype=float)
    ranges = np.asarray(ranges_m, dtype=float)
    raw_hits = np.asarray(raw_hit_mask, dtype=bool)
    no_returns = np.asarray(explicit_no_return_mask, dtype=bool)
    if origins.ndim != 2 or origins.shape[1] != 3 or directions.shape != origins.shape:
        raise ValueError("origins_m and directions_m must have matching n x 3 shapes")
    if ranges.shape != (len(origins),) or raw_hits.shape != ranges.shape or no_returns.shape != ranges.shape:
        raise ValueError("ranges and return masks must match the ray count")
    input_has_return = raw_hits & np.isfinite(ranges) & (ranges > 0.0)
    if np.any(input_has_return & no_returns):
        raise ValueError("A ray cannot be both a valid return and an explicit no-return")

    origins, directions, ranges, raw_hits, no_returns = _first_return_per_ray(
        origins, directions, ranges, raw_hits, no_returns, ray_ids
    )
    directions, valid_direction = _normalize_directions(directions)
    t_enter, t_exit, intersects = ray_box_intersection(
        origins_m=origins, directions_unit=directions, box=box
    )
    intersects &= valid_direction
    entry = np.maximum(t_enter, 0.0)
    has_return = raw_hits & np.isfinite(ranges) & (ranges > 0.0)
    before = intersects & has_return & (ranges < entry - tolerance_m)
    hit = intersects & has_return & ~before & (ranges <= t_exit + tolerance_m)
    returned_gap = intersects & has_return & (ranges > t_exit + tolerance_m)
    if max_observation_range_m is None:
        no_return_gap = np.zeros(len(origins), dtype=bool)
    else:
        max_range = float(max_observation_range_m)
        if not np.isfinite(max_range) or max_range <= 0.0:
            raise ValueError("mta_max_observation_range_m must be finite and greater than zero")
        no_return_gap = intersects & ~has_return & no_returns & (t_exit <= max_range + tolerance_m)
    gap = returned_gap | no_return_gap
    observed = hit | gap
    unknown = intersects & ~(before | observed)
    classes = np.column_stack([before, hit, gap, unknown])
    if np.any(np.sum(classes, axis=1) > 1):
        raise AssertionError("MTA first-event classes must be mutually exclusive")
    path = np.zeros(len(origins), dtype=float)
    path[hit] = np.clip(ranges[hit] - entry[hit], 0.0, None)
    path[gap] = np.clip(t_exit[gap] - entry[gap], 0.0, None)
    angle, vertical, _ = folded_zenith_deg(directions)
    return {
        "directions": directions,
        "angle_deg": angle,
        "vertical_component": vertical,
        "intersects": intersects,
        "observed": observed,
        "before": before,
        "hit": hit,
        "gap": gap,
        "unknown": unknown,
        "path_m": path,
        "entry_m": entry,
        "exit_m": t_exit,
    }


def _empty_summary(box: Box3D, *, angle_bin_deg: float, fit_min_deg: float, fit_max_deg: float,
                   min_rays_per_bin: int, min_path_m_per_bin: float,
                   min_valid_fit_bins: int, min_solid_angle_coverage: float,
                   max_observation_range_m: float | None, status: str) -> dict[str, Any]:
    nan = float("nan")
    return {
        "mta_deg": nan, "mta_method": "bounded_lang_v1",
        "mta_angle_bin_deg": float(angle_bin_deg),
        "mta_fit_angle_min_deg": float(fit_min_deg),
        "mta_fit_angle_max_deg": float(fit_max_deg),
        "mta_mu_m2_m3": nan, "mta_g_slope_per_rad": nan,
        "mta_fit_intercept": nan, "mta_fit_r2": nan, "mta_fit_rmse": nan,
        "mta_n_valid_bins": 0, "mta_n_fit_bins": 0,
        "mta_n_rays_intersecting_box": 0, "mta_n_rays_observed": 0,
        "mta_n_hits": 0, "mta_n_full_gaps": 0, "mta_n_hits_before_box": 0,
        "mta_n_unknown": 0, "mta_total_path_m": 0.0,
        "mta_solid_angle_coverage": 0.0, "mta_fit_angle_coverage": 0.0,
        "mta_slope_in_calibration_range": False, "mta_qc_pass": False,
        "mta_status": status,
        "mta_min_rays_per_bin": int(min_rays_per_bin),
        "mta_min_path_m_per_bin": float(min_path_m_per_bin),
        "mta_min_valid_fit_bins": int(min_valid_fit_bins),
        "mta_min_solid_angle_coverage": float(min_solid_angle_coverage),
        "mta_max_observation_range_m": max_observation_range_m,
        "mta_x_min_m": box.x_min, "mta_x_max_m": box.x_max,
        "mta_y_min_m": box.y_min, "mta_y_max_m": box.y_max,
        "mta_z_min_m": box.z_min, "mta_z_max_m": box.z_max,
        "mta_upward_deg": nan, "mta_upward_solid_angle_coverage": 0.0,
        "mta_upward_qc_pass": False, "mta_upward_status": "not_run",
        "mta_downward_deg": nan, "mta_downward_solid_angle_coverage": 0.0,
        "mta_downward_qc_pass": False, "mta_downward_status": "not_run",
        # Compatibility aliases used by existing downstream tables.
        "lai_mta_deg": nan, "lai_mta_sem_deg": nan,
        "lai_mta_slope": nan, "lai_mta_n_bins": 0,
    }


def _bin_table(
    events: dict[str, np.ndarray],
    group_mask: np.ndarray,
    edges: np.ndarray,
    *,
    group: str,
    role: str,
    min_rays_per_bin: int,
    min_path_m_per_bin: float,
) -> pd.DataFrame:
    angles = events["angle_deg"]
    bin_index = angle_bin_indices(angles, edges)
    rows: list[dict[str, Any]] = []
    for index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
        selected = group_mask & (bin_index == index)
        observed = selected & events["observed"]
        hits = selected & events["hit"]
        path = float(np.sum(events["path_m"][observed]))
        n_observed = int(np.sum(observed))
        n_hits = int(np.sum(hits))
        rate = float(n_hits / path) if path > 0.0 else float("nan")
        exposure_pass = bool(
            n_observed >= int(min_rays_per_bin)
            and path >= float(min_path_m_per_bin)
            and np.isfinite(rate)
        )
        rows.append({
            "mta_direction_group": group,
            "mta_bin_role": role,
            "mta_bin_lower_deg": float(low),
            "mta_bin_upper_deg": float(high),
            "mta_bin_center_deg": float((low + high) / 2.0),
            "mta_bin_solid_angle_weight": float(np.cos(np.radians(low)) - np.cos(np.radians(high))),
            "mta_bin_n_intersecting": int(np.sum(selected & events["intersects"])),
            "mta_bin_n_observed": n_observed,
            "mta_bin_n_before_box": int(np.sum(selected & events["before"])),
            "mta_bin_n_hits": n_hits,
            "mta_bin_n_full_gaps": int(np.sum(selected & events["gap"])),
            "mta_bin_n_unknown": int(np.sum(selected & events["unknown"])),
            "mta_bin_total_path_m": path,
            "mta_bin_mean_path_m": float(np.mean(events["path_m"][observed])) if n_observed else float("nan"),
            "mta_bin_lambda_m_inv": rate,
            "mta_bin_g": float("nan"),
            "mta_bin_exposure_pass": exposure_pass,
            "mta_bin_used_for_mu": exposure_pass and role == "integration",
            "mta_bin_used_for_fit": exposure_pass and role == "fit",
        })
    return pd.DataFrame(rows)


def _analyze_direction_group(
    events: dict[str, np.ndarray],
    group_mask: np.ndarray,
    integration_edges: np.ndarray,
    fit_edges: np.ndarray,
    *,
    group: str,
    min_rays_per_bin: int,
    min_path_m_per_bin: float,
    min_valid_fit_bins: int,
    min_solid_angle_coverage: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    integration = _bin_table(
        events, group_mask, integration_edges, group=group, role="integration",
        min_rays_per_bin=min_rays_per_bin, min_path_m_per_bin=min_path_m_per_bin,
    )
    fit_table = _bin_table(
        events, group_mask, fit_edges, group=group, role="fit",
        min_rays_per_bin=min_rays_per_bin, min_path_m_per_bin=min_path_m_per_bin,
    )
    table = pd.concat([integration, fit_table], ignore_index=True)

    valid = integration["mta_bin_used_for_mu"].to_numpy(dtype=bool)
    weights = integration["mta_bin_solid_angle_weight"].to_numpy(dtype=float)
    rates = integration["mta_bin_lambda_m_inv"].to_numpy(dtype=float)
    coverage = float(np.sum(weights[valid]))
    summary: dict[str, Any] = {
        "deg": float("nan"), "mu": float("nan"), "slope": float("nan"),
        "intercept": float("nan"), "r2": float("nan"), "rmse": float("nan"),
        "n_valid_bins": int(np.sum(valid)), "n_fit_bins": 0,
        "solid_angle_coverage": coverage, "fit_angle_coverage": 0.0,
        "slope_in_range": False, "qc_pass": False, "qc_level": "fail",
        "status": "insufficient_observed_path",
    }
    if not np.any(group_mask & events["intersects"]):
        summary["status"] = "no_rays_intersect_box"
        return summary, table
    if not np.any(valid):
        return summary, table
    # Explicitly renormalize the represented solid-angle weights.
    mu = float(2.0 * np.sum(weights[valid] * rates[valid]) / coverage)
    summary["mu"] = mu
    if not np.isfinite(mu) or mu <= 0.0:
        summary["status"] = "nonpositive_mu"
        return summary, table
    integration_indices = table["mta_bin_role"].eq("integration").to_numpy()
    table.loc[integration_indices & table["mta_bin_used_for_mu"].to_numpy(dtype=bool), "mta_bin_g"] = rates[valid] / mu

    fit = fit_table["mta_bin_used_for_fit"].to_numpy(dtype=bool)
    fit_rates = fit_table["mta_bin_lambda_m_inv"].to_numpy(dtype=float)
    fit_indices = table["mta_bin_role"].eq("fit").to_numpy()
    table.loc[fit_indices & table["mta_bin_used_for_fit"].to_numpy(dtype=bool), "mta_bin_g"] = fit_rates[fit] / mu
    summary["n_fit_bins"] = int(np.sum(fit))
    fit_width = float(np.sum(
        fit_table.loc[fit, "mta_bin_upper_deg"].to_numpy(dtype=float)
        - fit_table.loc[fit, "mta_bin_lower_deg"].to_numpy(dtype=float)
    ))
    summary["fit_angle_coverage"] = fit_width / 40.0
    if summary["n_fit_bins"] < 2:
        summary["status"] = "too_few_fit_bins"
        return summary, table

    theta = np.radians(fit_table.loc[fit, "mta_bin_center_deg"].to_numpy(dtype=float))
    g = fit_rates[fit] / mu
    design = np.column_stack([np.ones(theta.size), theta])
    if np.linalg.matrix_rank(design) < 2:
        summary["status"] = "singular_fit"
        return summary, table
    intercept, slope = np.linalg.lstsq(design, g, rcond=None)[0]
    fitted = intercept + slope * theta
    residual = g - fitted
    ss_res = float(np.sum(residual**2))
    ss_total = float(np.sum((g - np.mean(g))**2))
    r2 = 1.0 - ss_res / ss_total if ss_total > 1e-15 else (1.0 if ss_res <= 1e-15 else float("nan"))
    summary.update({
        "slope": float(slope), "intercept": float(intercept), "r2": float(r2),
        "rmse": float(np.sqrt(np.mean(residual**2))),
    })
    if not np.all(np.isfinite([intercept, slope])):
        summary["status"] = "singular_fit"
        return summary, table

    in_range = bool(_SLOPE_MIN <= slope <= _SLOPE_MAX)
    summary["slope_in_range"] = in_range
    summary["deg"] = mta_from_g_slope(float(slope))
    warnings = []
    if summary["n_fit_bins"] < int(min_valid_fit_bins):
        warnings.append("too_few_preferred_fit_bins")
    if coverage < max(0.9, float(min_solid_angle_coverage)):
        warnings.append("solid_angle_coverage")
    if summary["fit_angle_coverage"] < 1.0 - 1e-10:
        warnings.append("fit_angle_coverage")
    if int(np.sum(group_mask & events["unknown"])) > 0:
        warnings.append("unknown_rays")
    if not in_range:
        warnings.append("slope_outside_calibration_range")
    if warnings:
        summary["qc_level"] = "warning"
        summary["status"] = "warning_" + "_and_".join(warnings)
    else:
        summary["qc_level"] = "pass"
        summary["qc_pass"] = True
        summary["status"] = "ok"
    return summary, table


def compute_mta_traits(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    raw_hit_mask: np.ndarray,
    explicit_no_return_mask: np.ndarray,
    box: Box3D,
    angle_bin_deg: float = 5.0,
    fit_angle_min_deg: float = 25.0,
    fit_angle_max_deg: float = 65.0,
    min_rays_per_bin: int = 30,
    min_path_m_per_bin: float = 1.0,
    min_valid_fit_bins: int = 3,
    min_solid_angle_coverage: float = 0.8,
    max_observation_range_m: float | None = 60.0,
    ray_ids: np.ndarray | None = None,
    diagnostic: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Estimate bounded effective plant-element MTA and return long bin diagnostics."""
    edges = angle_bin_edges_deg(angle_bin_deg)
    fit_min = float(fit_angle_min_deg)
    fit_max = float(fit_angle_max_deg)
    if not np.isclose(fit_min, 25.0, atol=1e-12) or not np.isclose(fit_max, 65.0, atol=1e-12):
        raise ValueError("bounded_lang_v1 requires the fixed 25-65 degree fitting interval")
    if isinstance(min_rays_per_bin, bool) or int(min_rays_per_bin) < 1:
        raise ValueError("mta_min_rays_per_bin must be a positive integer")
    if not np.isfinite(min_path_m_per_bin) or float(min_path_m_per_bin) < 0.0:
        raise ValueError("mta_min_path_m_per_bin must be finite and nonnegative")
    if isinstance(min_valid_fit_bins, bool) or int(min_valid_fit_bins) < 2:
        raise ValueError("mta_min_valid_fit_bins must be an integer of at least 2")
    if not np.isfinite(min_solid_angle_coverage) or not 0.0 < float(min_solid_angle_coverage) <= 1.0:
        raise ValueError("mta_min_solid_angle_coverage must be in (0, 1]")

    summary = _empty_summary(
        box, angle_bin_deg=angle_bin_deg, fit_min_deg=fit_min, fit_max_deg=fit_max,
        min_rays_per_bin=min_rays_per_bin, min_path_m_per_bin=min_path_m_per_bin,
        min_valid_fit_bins=min_valid_fit_bins,
        min_solid_angle_coverage=min_solid_angle_coverage,
        max_observation_range_m=max_observation_range_m, status="invalid_plot_volume",
    )
    if not box_is_valid(box):
        return summary, pd.DataFrame() if diagnostic else None

    events = classify_first_events(
        origins_m=origins_m, directions_m=directions_m, ranges_m=ranges_m,
        raw_hit_mask=raw_hit_mask, explicit_no_return_mask=explicit_no_return_mask,
        box=box, max_observation_range_m=max_observation_range_m, ray_ids=ray_ids,
    )
    fit_edges = fit_angle_bin_edges_deg(angle_bin_deg)
    groups = {
        "all": np.ones(len(events["angle_deg"]), dtype=bool),
        "upward": events["vertical_component"] > 1e-12,
        "downward": events["vertical_component"] < -1e-12,
    }
    analyses: dict[str, dict[str, Any]] = {}
    tables = []
    for name, mask in groups.items():
        analyses[name], table = _analyze_direction_group(
            events, mask, edges, fit_edges, group=name,
            min_rays_per_bin=min_rays_per_bin, min_path_m_per_bin=min_path_m_per_bin,
            min_valid_fit_bins=min_valid_fit_bins,
            min_solid_angle_coverage=min_solid_angle_coverage,
        )
        if diagnostic:
            for key, value in analyses[name].items():
                table[f"mta_group_{key}"] = value
            tables.append(table)

    primary = analyses["all"]
    summary.update({
        "mta_deg": primary["deg"], "mta_mu_m2_m3": primary["mu"],
        "mta_g_slope_per_rad": primary["slope"], "mta_fit_intercept": primary["intercept"],
        "mta_fit_r2": primary["r2"], "mta_fit_rmse": primary["rmse"],
        "mta_n_valid_bins": primary["n_valid_bins"], "mta_n_fit_bins": primary["n_fit_bins"],
        "mta_n_rays_intersecting_box": int(np.sum(events["intersects"])),
        "mta_n_rays_observed": int(np.sum(events["observed"])),
        "mta_n_hits": int(np.sum(events["hit"])),
        "mta_n_full_gaps": int(np.sum(events["gap"])),
        "mta_n_hits_before_box": int(np.sum(events["before"])),
        "mta_n_unknown": int(np.sum(events["unknown"])),
        "mta_total_path_m": float(np.sum(events["path_m"][events["observed"]])),
        "mta_solid_angle_coverage": primary["solid_angle_coverage"],
        "mta_fit_angle_coverage": primary["fit_angle_coverage"],
        "mta_slope_in_calibration_range": primary["slope_in_range"],
        "mta_qc_pass": primary["qc_pass"], "mta_status": primary["status"],
        "mta_upward_deg": analyses["upward"]["deg"],
        "mta_upward_solid_angle_coverage": analyses["upward"]["solid_angle_coverage"],
        "mta_upward_qc_pass": analyses["upward"]["qc_pass"],
        "mta_upward_status": analyses["upward"]["status"],
        "mta_downward_deg": analyses["downward"]["deg"],
        "mta_downward_solid_angle_coverage": analyses["downward"]["solid_angle_coverage"],
        "mta_downward_qc_pass": analyses["downward"]["qc_pass"],
        "mta_downward_status": analyses["downward"]["status"],
    })
    summary.update({
        "lai_mta_deg": summary["mta_deg"], "lai_mta_sem_deg": float("nan"),
        "lai_mta_slope": summary["mta_g_slope_per_rad"],
        "lai_mta_n_bins": summary["mta_n_fit_bins"],
    })
    if not diagnostic:
        return summary, None
    diagnostics = pd.concat(tables, ignore_index=True)
    for key in (
        "mta_method", "mta_angle_bin_deg", "mta_fit_angle_min_deg",
        "mta_fit_angle_max_deg", "mta_min_rays_per_bin",
        "mta_min_path_m_per_bin", "mta_min_valid_fit_bins",
        "mta_min_solid_angle_coverage", "mta_max_observation_range_m",
        "mta_x_min_m", "mta_x_max_m", "mta_y_min_m", "mta_y_max_m",
        "mta_z_min_m", "mta_z_max_m",
    ):
        diagnostics[key] = summary[key]
    return summary, diagnostics
