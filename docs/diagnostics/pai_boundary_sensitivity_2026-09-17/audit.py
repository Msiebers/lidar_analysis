#!/usr/bin/env python3
"""Read-only audit of the five alfalfa-density PAI near-boundary runs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


OUT = Path(__file__).resolve().parent
RAW = Path("/media/central/raw_mirror/al_lai/density")
RUNS = {
    0.0: ("results_near00.csv", "ray_box_diagnostics_results00.csv"),
    0.1: ("results_near01.csv", "ray_box_diagnostics_near01.csv"),
    0.2: ("results_near02.csv", "ray_box_diagnostics_near02.csv"),
    0.3: ("results_near03.csv", "ray_box_diagnostics_near03.csv"),
    0.4: ("results_near04.csv", "ray_box_diagnostics_near04.csv"),
}
KEY = ["scan_name", "plot", "side"]
ESTIMATORS = {
    "z_pai": "z_pai_m2_m2",
    "whole_box": "pai_whole_box_m2_m2",
    "conditional": "pai_m2_m2",
}


def add_design(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["collection_date"] = pd.to_datetime(
        frame["scan_name"].str.extract(r"(2026_\d\d_\d\d)")[0].str.replace("_", "-")
    )
    frame["scan_number"] = pd.to_numeric(frame["scan_number"])
    frame["plot"] = pd.to_numeric(frame["plot"])
    frame["repeat"] = (frame["scan_number"] + 1) // 2
    frame["odd"] = frame["scan_number"] % 2 == 1
    odd = np.array([0, 100, 90, 70, 50, 30, 10])
    even = np.array([10, 30, 50, 70, 90, 100, 0])
    late = frame["collection_date"].eq(pd.Timestamp("2026-07-23"))
    frame["treatment"] = np.where(
        late,
        np.where(frame["odd"], even[frame["plot"] - 1], odd[frame["plot"] - 1]),
        np.where(frame["odd"], odd[frame["plot"] - 1], even[frame["plot"] - 1]),
    )
    frame["view"] = np.select(
        [
            frame["odd"] & frame["side"].eq("right"),
            frame["odd"] & frame["side"].eq("left"),
            ~frame["odd"] & frame["side"].eq("left"),
            ~frame["odd"] & frame["side"].eq("right"),
        ],
        ["Row 1", "Row 2L", "Row 2R", "Row 3"],
    )
    frame["biological_row"] = np.where(
        frame["side"].eq("left"), 2, np.where(frame["odd"], 1, 3)
    )
    return frame


def read_runs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summaries, mta_bins, layers = [], [], []
    expected_keys = None
    for near, (results_name, diagnostic_name) in RUNS.items():
        results = pd.read_csv(RAW / results_name)
        diagnostics = pd.read_csv(RAW / diagnostic_name, low_memory=False)

        summary = diagnostics[diagnostics["diagnostic_type"].eq("summary")].copy()
        actual_near = np.minimum(summary["pai_x_min_m"].abs(), summary["pai_x_max_m"].abs())
        stale_rows = len(summary) - int(np.isclose(actual_near, near).sum())
        summary = summary[np.isclose(actual_near, near)].copy()
        summary["x_near_m"] = near
        summary["stale_summary_rows_excluded"] = stale_rows
        assert len(summary) == 546
        assert not summary.duplicated(KEY).any()
        assert set(map(tuple, results[KEY].to_numpy())) == set(map(tuple, summary[KEY].to_numpy()))
        for column in ["z_pai_m2_m2", "pai_m2_m2", "pai_height_m"]:
            check = results[KEY + [column]].merge(
                summary[KEY + [column]], on=KEY, suffixes=("_result", "_diagnostic")
            )
            assert np.allclose(
                check[f"{column}_result"], check[f"{column}_diagnostic"],
                atol=0.0051, rtol=0, equal_nan=True,
            )
        keys = set(map(tuple, summary[KEY].to_numpy()))
        expected_keys = keys if expected_keys is None else expected_keys
        assert keys == expected_keys
        summaries.append(summary)

        bins = diagnostics[
            diagnostics["diagnostic_type"].eq("mta_bin")
            & diagnostics["mta_direction_group"].eq("all")
            & diagnostics["mta_bin_role"].eq("integration")
        ].copy()
        actual_mta_near = np.minimum(bins["mta_x_min_m"].abs(), bins["mta_x_max_m"].abs())
        bins = bins[np.isclose(actual_mta_near, near)].copy()
        bins["x_near_m"] = near
        mta_bins.append(bins)

        z_layers = diagnostics[diagnostics["diagnostic_type"].eq("z_pai_layer")].copy()
        if near == 0.4:
            # The appended file does not carry an X-bound identifier on layer rows,
            # so the two runs cannot be separated without circularly matching totals.
            z_layers = z_layers.iloc[0:0].copy()
        z_layers["x_near_m"] = near
        layers.append(z_layers)

    response = add_design(pd.concat(summaries, ignore_index=True))
    response["prebox_fraction"] = (
        response["pai_n_hits_before_box"] / response["pai_n_rays_intersecting_box"]
    )
    # Summary rows leave the generic field blank. Z-PAI records the exact observed
    # first-event exposure needed for the requested per-ray diagnostic.
    response["observed_path_per_ray_m"] = (
        response["z_pai_total_observed_path_m"] / response["pai_n_rays_observed"]
    )
    response["observed_path_source"] = "z_pai_total_observed_path_m"
    return response, pd.concat(mta_bins, ignore_index=True), pd.concat(layers, ignore_index=True)


def controlled_field_audit(response: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "pai_y_min_m", "pai_y_max_m", "pai_z_min_m", "pai_z_max_m",
        "pai_box_height_m", "pai_box_length_m", "pai_height_m",
        "pai_layer_thickness_m", "pai_n_layers", "pai_g_function", "pai_g_value",
        "pai_max_observation_range_m", "z_pai_height_m", "z_pai_layer_thickness_m",
        "z_pai_n_layers", "z_pai_g_function", "z_pai_g_value",
        "ray_box_ground_mode", "ray_box_bottom_agl_m",
        "ray_box_ground_grid_x_bin_m", "ray_box_ground_grid_z_bin_m",
        "ray_box_ground_reference_y_m", "ray_box_ground_y_min_m",
        "ray_box_ground_y_mean_m", "ray_box_ground_y_max_m", "ray_box_height_m",
        "ray_box_y_bottom_m", "mta_angle_bin_deg", "mta_fit_angle_min_deg",
        "mta_fit_angle_max_deg", "mta_min_rays_per_bin", "mta_min_path_m_per_bin",
        "mta_min_valid_fit_bins", "mta_min_solid_angle_coverage",
        "mta_max_observation_range_m",
    ]
    rows = []
    for field in fields:
        counts = response.groupby(KEY, dropna=False)[field].nunique(dropna=False)
        rows.append(
            {
                "field": field,
                "maximum_distinct_values_across_five_runs_for_same_target": counts.max(),
                "all_546_targets_match": bool(counts.max() == 1),
            }
        )
    return pd.DataFrame(rows)


def relative_disagreement(paired: pd.DataFrame) -> pd.Series:
    return (paired.iloc[:, 0] - paired.iloc[:, 1]).abs() / paired.mean(axis=1)


def agreement_and_repeatability(response: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    agreement, repeats = [], []
    for near, subset in response.groupby("x_near_m"):
        for estimator, column in ESTIMATORS.items():
            side = subset.pivot_table(index=["scan_name", "plot"], columns="side", values=column).dropna()
            side_diff = side["left"] - side["right"]
            row2 = (
                subset[subset["view"].isin(["Row 2L", "Row 2R"])]
                .pivot_table(
                    index=["collection_date", "treatment", "repeat"],
                    columns="view", values=column, aggfunc="mean"
                )
                .dropna()
            )
            row2_diff = row2["Row 2L"] - row2["Row 2R"]
            agreement.append(
                {
                    "x_near_m": near, "estimator": estimator,
                    "n_same_scan_pairs": len(side),
                    "same_scan_r": side["left"].corr(side["right"]),
                    "same_scan_mae": side_diff.abs().mean(),
                    "same_scan_median_relative_absolute_difference": relative_disagreement(side).median(),
                    "n_row2_pairs": len(row2),
                    "row2_r": row2["Row 2L"].corr(row2["Row 2R"]),
                    "row2_mae": row2_diff.abs().mean(),
                    "row2_median_relative_absolute_difference": relative_disagreement(row2).median(),
                }
            )
            values = (
                subset.groupby(["collection_date", "treatment", "repeat", "view"])[column]
                .mean().reset_index()
            )
            grouped = values.groupby(["collection_date", "treatment", "view"])[column].agg(
                ["mean", "std", "count"]
            )
            cv = (grouped["std"] / grouped["mean"]).replace([np.inf, -np.inf], np.nan)
            repeats.append(
                {
                    "x_near_m": near, "estimator": estimator, "n_groups": len(grouped),
                    "median_cv": cv.median(), "mean_cv": cv.mean(), "p90_cv": cv.quantile(0.9),
                }
            )
    return pd.DataFrame(agreement), pd.DataFrame(repeats)


def date_specific_precision(response: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    agreement, repeats = [], []
    for (near, date), subset in response.groupby(["x_near_m", "collection_date"]):
        for estimator, column in ESTIMATORS.items():
            row2 = (
                subset[subset["view"].isin(["Row 2L", "Row 2R"])]
                .pivot_table(index=["treatment", "repeat"], columns="view", values=column, aggfunc="mean")
                .dropna()
            )
            difference = row2["Row 2L"] - row2["Row 2R"]
            agreement.append(
                {
                    "x_near_m": near, "collection_date": date, "estimator": estimator,
                    "n_pairs": len(row2), "row2_r": row2["Row 2L"].corr(row2["Row 2R"]),
                    "row2_mae": difference.abs().mean(),
                    "row2_median_relative_absolute_difference": relative_disagreement(row2).median(),
                }
            )
            values = (
                subset.groupby(["treatment", "repeat", "view"])[column].mean().reset_index()
            )
            grouped = values.groupby(["treatment", "view"])[column].agg(["mean", "std", "count"])
            cv = (grouped["std"] / grouped["mean"]).replace([np.inf, -np.inf], np.nan)
            repeats.append(
                {
                    "x_near_m": near, "collection_date": date, "estimator": estimator,
                    "n_groups": len(grouped), "median_cv": cv.median(),
                    "mean_cv": cv.mean(), "p90_cv": cv.quantile(0.9),
                }
            )
    return pd.DataFrame(agreement), pd.DataFrame(repeats)


def estimator_sensitivity(response: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for estimator, column in ESTIMATORS.items():
        wide = response.pivot_table(index=KEY, columns="x_near_m", values=column)
        mean = wide.mean(axis=1)
        endpoint_difference = (wide[0.4] - wide[0.0]).abs()
        rows.append(
            {
                "estimator": estimator, "n_matched_targets": len(wide),
                "median_boundary_cv": (wide.std(axis=1) / mean).median(),
                "median_boundary_range_divided_by_mean": ((wide.max(axis=1) - wide.min(axis=1)) / mean).median(),
                "median_abs_true_boundary_minus_near_zero": endpoint_difference.median(),
                "median_relative_true_boundary_minus_near_zero": (endpoint_difference / wide[[0.0, 0.4]].mean(axis=1)).median(),
                "correlation_true_boundary_vs_near_zero": wide[0.4].corr(wide[0.0]),
            }
        )
    return pd.DataFrame(rows)


def treatment_tables(response: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries, means = [], []
    for near, subset in response.groupby("x_near_m"):
        for estimator, column in ESTIMATORS.items():
            repeat_rows = (
                subset.groupby(["collection_date", "treatment", "repeat", "biological_row"])[column]
                .mean().reset_index()
            )
            biological = (
                repeat_rows.groupby(["collection_date", "treatment", "biological_row"])[column]
                .mean().reset_index()
            )
            grouped = (
                biological.groupby(["collection_date", "treatment"])[column]
                .agg(["mean", "std", "count"]).reset_index()
            )
            grouped["se"] = grouped["std"] / np.sqrt(grouped["count"])
            grouped.insert(0, "estimator", estimator)
            grouped.insert(0, "x_near_m", near)
            means.append(grouped)
            for date, date_values in grouped.groupby("collection_date"):
                control = date_values.loc[date_values["treatment"].eq(0), "mean"].iloc[0]
                full = date_values.loc[date_values["treatment"].eq(100), "mean"].iloc[0]
                high = date_values.loc[date_values["treatment"].ge(70), "mean"].mean()
                summaries.append(
                    {
                        "x_near_m": near, "collection_date": date, "estimator": estimator,
                        "spearman_removal_vs_pai": spearmanr(date_values["treatment"], date_values["mean"]).statistic,
                        "linear_slope_per_percent_removal": np.polyfit(date_values["treatment"], date_values["mean"], 1)[0],
                        "control_mean": control, "removal_100_mean": full,
                        "high_removal_70_to_100_mean": high,
                        "high_removal_minus_control": high - control,
                    }
                )
    return pd.DataFrame(summaries), pd.concat(means, ignore_index=True)


def angular_tables(bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pooled = (
        bins.groupby(["x_near_m", "mta_bin_center_deg"])[
            ["mta_bin_n_intersecting", "mta_bin_n_before_box", "mta_bin_n_observed", "mta_bin_total_path_m"]
        ].sum().reset_index()
    )
    pooled["prebox_fraction"] = pooled["mta_bin_n_before_box"] / pooled["mta_bin_n_intersecting"]
    pooled["observed_share"] = pooled["mta_bin_n_observed"] / pooled.groupby("x_near_m")["mta_bin_n_observed"].transform("sum")
    pooled["path_share"] = pooled["mta_bin_total_path_m"] / pooled.groupby("x_near_m")["mta_bin_total_path_m"].transform("sum")
    rows = []
    for near, values in pooled.groupby("x_near_m"):
        observed = values["mta_bin_n_observed"]
        path = values["mta_bin_total_path_m"]
        rows.append(
            {
                "x_near_m": near,
                "observed_weighted_angle_deg": np.average(values["mta_bin_center_deg"], weights=observed),
                "path_weighted_angle_deg": np.average(values["mta_bin_center_deg"], weights=path),
                "observed_share_75_to_90_deg": values.loc[values["mta_bin_center_deg"].ge(75), "observed_share"].sum(),
                "path_share_75_to_90_deg": values.loc[values["mta_bin_center_deg"].ge(75), "path_share"].sum(),
            }
        )
    return pd.DataFrame(rows), pooled


def summaries(
    response: pd.DataFrame, agreement: pd.DataFrame, repeatability: pd.DataFrame,
    treatment: pd.DataFrame, angles: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = [
        "prebox_fraction", "pai_reach_fraction", "pai_gap_fraction", "pai_hit_fraction",
        "pai_mean_chord_m", "pai_median_chord_m", "pai_total_geometric_chord_m",
        "z_pai_total_observed_path_m", "observed_path_per_ray_m", "pai_height_m",
        "pai_n_rays_intersecting_box", "pai_n_hits_before_box", "pai_n_rays_observed",
        *ESTIMATORS.values(),
    ]
    overall = response.groupby("x_near_m")[columns].median().reset_index()
    pooled = response.groupby("x_near_m").agg(
        total_intersecting=("pai_n_rays_intersecting_box", "sum"),
        total_prebox=("pai_n_hits_before_box", "sum"), total_observed=("pai_n_rays_observed", "sum")
    ).reset_index()
    pooled["pooled_prebox_fraction"] = pooled["total_prebox"] / pooled["total_intersecting"]
    pooled["pooled_reach_fraction"] = pooled["total_observed"] / pooled["total_intersecting"]
    overall = overall.merge(pooled, on="x_near_m").merge(angles, on="x_near_m")
    for label, data, prefix in [
        ("agreement", agreement, ""), ("repeatability", repeatability, "repeat_")
    ]:
        del label
        for estimator in ESTIMATORS:
            part = data[data["estimator"].eq(estimator)].drop(columns="estimator")
            part = part.rename(columns={c: f"{prefix}{estimator}_{c}" for c in part if c != "x_near_m"})
            overall = overall.merge(part, on="x_near_m")

    date_columns = ["prebox_fraction", "pai_reach_fraction", *ESTIMATORS.values()]
    by_date = response.groupby(["x_near_m", "collection_date"])[date_columns].median().reset_index()
    for estimator in ESTIMATORS:
        metric = treatment[treatment["estimator"].eq(estimator)][
            ["x_near_m", "collection_date", "spearman_removal_vs_pai"]
        ].rename(columns={"spearman_removal_vs_pai": f"{estimator}_treatment_spearman"})
        by_date = by_date.merge(metric, on=["x_near_m", "collection_date"])

    wide = response.pivot_table(index=KEY, columns="x_near_m", values=columns)
    transitions = []
    for start, end in [(0.4, 0.3), (0.3, 0.2), (0.2, 0.1), (0.1, 0.0)]:
        row = {"from_x_near_m": start, "to_x_near_m": end, "newly_included_band_m": f"{end:.1f}-{start:.1f}"}
        for column in columns:
            row[f"median_change_{column}"] = (wide[column][end] - wide[column][start]).median()
        transitions.append(row)
    return overall, by_date, pd.DataFrame(transitions)


def profile_audit(response: pd.DataFrame, layers: pd.DataFrame) -> pd.DataFrame:
    summed = layers.groupby(KEY + ["x_near_m"])["pai_layer_m2_m2"].sum().rename("layer_sum")
    totals = response.set_index(KEY + ["x_near_m"])["z_pai_m2_m2"]
    matched = pd.concat([summed, totals], axis=1).dropna()
    rows = []
    for near, group in response.groupby("x_near_m"):
        layer_group = matched.xs(near, level="x_near_m") if near in matched.index.get_level_values("x_near_m") else None
        rows.append(
            {
                "x_near_m": near, "n_targets": len(group),
                "all_z_profiles_complete": bool(group["z_pai_profile_complete"].all()),
                "minimum_support_fraction": group["z_pai_profile_support_fraction"].min(),
                "all_conditional_profiles_complete": bool(group["pai_conditional_profile_complete"].all()),
                "all_whole_box_fits_converged": bool(group["pai_converged"].all()),
                "number_whole_box_saturated": int(group["pai_saturated"].sum()),
                "direct_layer_sum_check": (
                    "not separable: appended layer rows lack X-bound identifiers"
                    if layer_group is None else "checked"
                ),
                "maximum_abs_layer_sum_minus_z_total": (
                    np.nan if layer_group is None
                    else (layer_group["layer_sum"] - layer_group["z_pai_m2_m2"]).abs().max()
                ),
            }
        )
    return pd.DataFrame(rows)


def representative_cases(response: pd.DataFrame) -> pd.DataFrame:
    selected = response[
        response["scan_name"].eq("scan_001_multi02_2026_07_09_1_Additional_Scans")
        & response["plot"].isin([1, 2])
    ].copy()
    worst = response[response["x_near_m"].eq(0.4)].nlargest(5, "prebox_fraction")
    selected["case"] = "July 9 scan 1: control marker 1 and 100%-removal marker 2"
    worst = worst.copy()
    worst["case"] = "highest true-boundary prebox interception"
    columns = [
        "case", "scan_name", "collection_date", "plot", "side", "treatment", "view",
        "x_near_m", "prebox_fraction", "pai_reach_fraction", *ESTIMATORS.values(),
    ]
    return pd.concat([selected[columns], worst[columns]], ignore_index=True)


def make_figures(
    overall: pd.DataFrame, treatment: pd.DataFrame, angle_bins: pd.DataFrame,
    representatives: pd.DataFrame,
) -> None:
    colors = {"z_pai": "#0072B2", "whole_box": "#D55E00", "conditional": "#009E73"}
    labels = {"z_pai": "Z-PAI", "whole_box": "Whole-box", "conditional": "Conditional"}
    x = overall["x_near_m"]
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    axes[0, 0].plot(x, overall["prebox_fraction"], "o-", label="Pre-box")
    axes[0, 0].plot(x, overall["pai_reach_fraction"], "o-", label="Reach")
    axes[0, 0].set_ylabel("Median fraction")
    axes[0, 0].legend()
    for estimator, column in ESTIMATORS.items():
        axes[0, 1].plot(x, overall[column], "o-", color=colors[estimator], label=labels[estimator])
        axes[0, 2].plot(x, overall[f"{estimator}_row2_median_relative_absolute_difference"], "o-", color=colors[estimator], label=labels[estimator])
        axes[1, 0].plot(x, overall[f"repeat_{estimator}_median_cv"], "o-", color=colors[estimator], label=labels[estimator])
    axes[0, 1].set_ylabel("Median PAI (m² m⁻²)")
    axes[0, 2].set_ylabel("Row-2 median relative difference")
    axes[1, 0].set_ylabel("Median technical-repeat CV")
    axes[0, 1].legend()
    axes[1, 1].plot(x, overall["observed_weighted_angle_deg"], "o-", label="Observed-ray weighted")
    axes[1, 1].plot(x, overall["path_weighted_angle_deg"], "o-", label="Path weighted")
    axes[1, 1].set_ylabel("Folded zenith angle (degrees)")
    axes[1, 1].legend()
    axes[1, 2].plot(x, overall["observed_path_per_ray_m"], "o-")
    axes[1, 2].set_ylabel("Median observed Z path / observed ray (m)")
    for ax in axes.flat:
        ax.set_xlabel("Near-X boundary (m)")
        ax.grid(alpha=0.25)
        ax.axvline(0.4, color="black", ls=":", lw=1)
    fig.suptitle("Boundary sweep: optical access versus the true 0.4-m plot boundary")
    fig.savefig(OUT / "boundary_sweep.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.3), sharey=True, constrained_layout=True)
    for ax, estimator in zip(axes, ESTIMATORS):
        subset = treatment[treatment["estimator"].eq(estimator)]
        for date, values in subset.groupby("collection_date"):
            ax.plot(values["x_near_m"], values["spearman_removal_vs_pai"], "o-", label=date.strftime("%b %d"))
        ax.axhline(0, color="black", lw=0.8)
        ax.axvline(0.4, color="black", ls=":", lw=1)
        ax.set_title(labels[estimator])
        ax.set_xlabel("Near-X boundary (m)")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Spearman thinning-removal vs PAI")
    axes[-1].legend(title="Collection")
    fig.suptitle("Treatment ordering is recovered at the biological boundary and diluted by foreground")
    fig.savefig(OUT / "treatment_response.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for near, values in angle_bins.groupby("x_near_m"):
        axes[0].plot(values["mta_bin_center_deg"], values["observed_share"], "o-", label=f"near {near:.1f}")
        axes[1].plot(values["mta_bin_center_deg"], values["prebox_fraction"], "o-", label=f"near {near:.1f}")
    axes[0].set_ylabel("Share of observed rays")
    axes[1].set_ylabel("Pre-box fraction within angle bin")
    for ax in axes:
        ax.set_xlabel("Folded zenith-angle bin center (degrees)")
        ax.grid(alpha=0.25)
    axes[0].legend(ncol=2)
    fig.suptitle("Changing near-X changes the angular risk set, not just box width")
    fig.savefig(OUT / "angular_composition.png", dpi=180)
    plt.close(fig)

    cases = representatives[representatives["case"].str.startswith("July 9")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, constrained_layout=True)
    for ax, plot in zip(axes, [1, 2]):
        values = cases[cases["plot"].eq(plot)]
        for side, side_values in values.groupby("side"):
            ax.plot(side_values["x_near_m"], side_values["z_pai_m2_m2"], "o-", label=side)
        ax.set_title(f"July 9 scan 1, marker {plot}, treatment {values['treatment'].iloc[0]}%")
        ax.set_xlabel("Near-X boundary (m)")
        ax.axvline(0.4, color="black", ls=":", lw=1)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Z-PAI (m² m⁻²)")
    axes[1].legend()
    fig.suptitle("A specific control/treatment scan shows why the foreground changes the biological answer")
    fig.savefig(OUT / "representative_scan.png", dpi=180)
    plt.close(fig)


def main() -> None:
    response, bins, layers = read_runs()
    controlled = controlled_field_audit(response)
    assert controlled["all_546_targets_match"].all()
    agreement, repeatability = agreement_and_repeatability(response)
    agreement_by_date, repeatability_by_date = date_specific_precision(response)
    sensitivity = estimator_sensitivity(response)
    treatment, treatment_means = treatment_tables(response)
    angles, angle_bins = angular_tables(bins)
    overall, by_date, transitions = summaries(response, agreement, repeatability, treatment, angles)
    profiles = profile_audit(response, layers)
    representatives = representative_cases(response)

    keep = [
        "scan_name", "scan_number", "collection_date", "plot", "side", "treatment",
        "repeat", "view", "biological_row", "x_near_m", "pai_x_min_m", "pai_x_max_m",
        "pai_box_width_m", "pai_y_min_m", "pai_y_max_m", "pai_z_min_m", "pai_z_max_m",
        "z_pai_m2_m2", "pai_m2_m2", "pai_whole_box_m2_m2", "pai_gap_fraction",
        "pai_hit_fraction", "pai_n_rays_intersecting_box", "pai_n_hits_before_box",
        "pai_n_rays_observed", "pai_reach_fraction", "prebox_fraction", "pai_mean_chord_m",
        "pai_median_chord_m", "pai_total_geometric_chord_m", "total_observed_path_m",
        "z_pai_total_observed_path_m", "observed_path_per_ray_m", "observed_path_source",
        "pai_height_m", "pai_layer_thickness_m", "pai_n_layers",
        "pai_conditional_profile_complete", "z_pai_profile_complete",
        "z_pai_profile_support_fraction", "z_pai_n_supported_layers", "pai_converged",
        "pai_saturated", "pai_profile_converged", "pai_profile_identifiable",
        "stale_summary_rows_excluded",
    ]
    outputs = {
        "boundary_response.csv": response[keep],
        "controlled_field_audit.csv": controlled,
        "boundary_summary.csv": overall,
        "boundary_date_summary.csv": by_date,
        "boundary_transitions.csv": transitions,
        "view_agreement.csv": agreement,
        "view_agreement_by_date.csv": agreement_by_date,
        "technical_repeatability.csv": repeatability,
        "technical_repeatability_by_date.csv": repeatability_by_date,
        "estimator_sensitivity.csv": sensitivity,
        "treatment_response.csv": treatment,
        "treatment_means.csv": treatment_means,
        "angular_composition.csv": angles,
        "angular_bins.csv": angle_bins,
        "profile_support.csv": profiles,
        "representative_cases.csv": representatives,
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    make_figures(overall, treatment, angle_bins, representatives)
    print(f"validated {response[KEY].drop_duplicates().shape[0]} targets x 5 boundaries = {len(response)} rows")
    print("excluded stale near04 summary rows:", int(response[response["x_near_m"].eq(0.4)]["stale_summary_rows_excluded"].iloc[0]))
    print("all controlled diagnostic fields matched target-for-target")
    print("wrote", len(outputs), "tables and 4 figures to", OUT)


if __name__ == "__main__":
    main()
