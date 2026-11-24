#!/usr/bin/env python3
"""Read-only PAI estimator reassessment using existing al_lai outputs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


OUT = Path(__file__).resolve().parent
RAW = Path("/media/central/raw_mirror/al_lai")
STUDY = Path("/home/central/Documents/al_lai_26")
ESTIMATORS = {
    "whole_box": "pai_whole_box_m2_m2",
    "conditional": "pai_m2_m2",
    "exact_first_event": "z_pai_m2_m2",
}


def read_density() -> tuple[pd.DataFrame, pd.DataFrame]:
    diagnostics = pd.read_csv(RAW / "density/ray_box_diagnostics.csv", low_memory=False)
    summary = diagnostics[diagnostics["diagnostic_type"].eq("summary")].copy()
    summary["collection_date"] = pd.to_datetime(
        summary["scan_name"].str.extract(r"(2026_\d\d_\d\d)")[0].str.replace("_", "-")
    )
    summary["scan_number"] = pd.to_numeric(summary["scan_number"])
    summary["plot"] = pd.to_numeric(summary["plot"])
    summary["repeat"] = (summary["scan_number"] + 1) // 2
    summary["odd"] = summary["scan_number"] % 2 == 1

    odd_treatment = np.array([0, 100, 90, 70, 50, 30, 10])
    even_treatment = np.array([10, 30, 50, 70, 90, 100, 0])
    july_23 = summary["collection_date"].eq(pd.Timestamp("2026-07-23"))
    summary["treatment"] = np.where(
        july_23,
        np.where(
            summary["odd"],
            even_treatment[summary["plot"].astype(int) - 1],
            odd_treatment[summary["plot"].astype(int) - 1],
        ),
        np.where(
            summary["odd"],
            odd_treatment[summary["plot"].astype(int) - 1],
            even_treatment[summary["plot"].astype(int) - 1],
        ),
    )
    summary["view"] = np.select(
        [
            summary["odd"] & summary["side"].eq("right"),
            summary["odd"] & summary["side"].eq("left"),
            ~summary["odd"] & summary["side"].eq("left"),
            ~summary["odd"] & summary["side"].eq("right"),
        ],
        ["Row 1", "Row 2L", "Row 2R", "Row 3"],
    )
    summary["biological_row"] = np.where(
        summary["side"].eq("left"), 2, np.where(summary["odd"], 1, 3)
    )
    return summary, diagnostics


def density_tables(summary: pd.DataFrame, diagnostics: pd.DataFrame):
    estimator_summary = pd.DataFrame(
        {
            "estimator": name,
            "n": summary[column].count(),
            "mean": summary[column].mean(),
            "sd": summary[column].std(),
            "minimum": summary[column].min(),
            "median": summary[column].median(),
            "maximum": summary[column].max(),
        }
        for name, column in ESTIMATORS.items()
    )

    pairwise = []
    for left, right in [
        ("conditional", "whole_box"),
        ("exact_first_event", "whole_box"),
        ("exact_first_event", "conditional"),
    ]:
        x, y = summary[ESTIMATORS[left]], summary[ESTIMATORS[right]]
        pairwise.append(
            {
                "left": left,
                "right": right,
                "n": len(summary),
                "pearson_r": x.corr(y),
                "mean_left_minus_right": (x - y).mean(),
                "mae": (x - y).abs().mean(),
                "median_ratio": np.median(x / y),
            }
        )
    pairwise = pd.DataFrame(pairwise)

    agreement = []
    for name, column in ESTIMATORS.items():
        paired = (
            summary[summary["view"].isin(["Row 2L", "Row 2R"])]
            .pivot_table(
                index=["collection_date", "treatment", "repeat"],
                columns="view",
                values=column,
                aggfunc="mean",
            )
            .dropna()
        )
        difference = paired["Row 2L"] - paired["Row 2R"]
        agreement.append(
            {
                "estimator": name,
                "n_pairs": len(paired),
                "pearson_r": paired["Row 2L"].corr(paired["Row 2R"]),
                "mean_left_minus_right": difference.mean(),
                "mae": difference.abs().mean(),
                "median_relative_absolute_difference": np.median(
                    difference.abs() / paired.mean(axis=1)
                ),
            }
        )
    agreement = pd.DataFrame(agreement)

    repeatability = []
    for name, column in ESTIMATORS.items():
        values = (
            summary.groupby(["collection_date", "treatment", "repeat", "view"])[column]
            .mean()
            .reset_index()
        )
        groups = values.groupby(["collection_date", "treatment", "view"])[column].agg(
            ["mean", "std", "count"]
        )
        cv = (groups["std"] / groups["mean"]).replace([np.inf, -np.inf], np.nan)
        repeatability.append(
            {
                "estimator": name,
                "n_groups": len(groups),
                "median_cv": cv.median(),
                "mean_cv": cv.mean(),
                "p90_cv": cv.quantile(0.9),
            }
        )
    repeatability = pd.DataFrame(repeatability)

    treatment_rows = []
    for name, column in ESTIMATORS.items():
        repeat_rows = (
            summary.groupby(
                ["collection_date", "treatment", "repeat", "biological_row"]
            )[column]
            .mean()
            .reset_index()
        )
        biological = (
            repeat_rows.groupby(["collection_date", "treatment", "biological_row"])[
                column
            ]
            .mean()
            .reset_index()
        )
        means = (
            biological.groupby(["collection_date", "treatment"])[column]
            .agg(["mean", "std", "count"])
            .reset_index()
        )
        means["se"] = means["std"] / np.sqrt(means["count"])
        for date, group in means.groupby("collection_date"):
            means.loc[group.index, "spearman_removal_vs_value"] = spearmanr(
                group["treatment"], group["mean"]
            ).statistic
        means.insert(0, "estimator", name)
        treatment_rows.append(means)
    treatment = pd.concat(treatment_rows, ignore_index=True)

    z_layers = diagnostics[diagnostics["diagnostic_type"].eq("z_pai_layer")].copy()
    key = ["scan_name", "plot", "side"]
    support = z_layers.groupby(key).agg(
        n_layers=("n_hits", "size"),
        minimum_layer_hits=("n_hits", "min"),
        minimum_layer_exposure_m=("total_observed_path_m", "min"),
    )
    profile_support = pd.DataFrame(
        [
            {
                "n_targets": len(support),
                "all_layers_positive_exposure": int(
                    (support["minimum_layer_exposure_m"] > 0).sum()
                ),
                "all_layers_at_least_one_hit": int(
                    (support["minimum_layer_hits"] > 0).sum()
                ),
                "targets_with_zero_hit_layer": int(
                    (support["minimum_layer_hits"] == 0).sum()
                ),
                "layer_cells": len(z_layers),
                "zero_hit_layer_cells": int((z_layers["n_hits"] == 0).sum()),
            }
        ]
    )

    return (
        estimator_summary,
        pairwise,
        agreement,
        repeatability,
        treatment,
        profile_support,
    )


def dated_results(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["collection_date"] = pd.to_datetime(
        frame["scan_name"].str.extract(r"(2026_\d\d_\d\d)")[0].str.replace("_", "-")
    )
    return frame


def destructive_data():
    truth = pd.read_csv(STUDY / "biomass_groundtruth.csv")
    truth["collection_date"] = pd.to_datetime(truth["date"])
    truth = truth[truth["canopy_section"].eq("whole")].copy()

    biomass = dated_results(RAW / "biomass/results.csv")
    biomass = biomass[
        biomass["scan_number"].between(1, 15) & biomass["side"].eq("right")
    ].copy()
    biomass["biological_plot"] = np.ceil(biomass["scan_number"] / 5).astype(int)
    biomass["expected_marker"] = np.where(
        biomass["collection_date"].eq(pd.Timestamp("2026-07-23")), 2, 1
    )
    biomass = biomass[biomass["plot"].eq(biomass["expected_marker"])]

    partition = dated_results(RAW / "partition/results.csv")
    early = partition[
        partition["collection_date"].isin(
            pd.to_datetime(["2026-07-01", "2026-07-09", "2026-07-16"])
        )
        & partition["scan_number"].between(16, 30)
        & partition["plot"].eq(1)
        & partition["side"].eq("right")
    ].copy()
    early["biological_plot"] = np.ceil((early["scan_number"] - 15) / 5).astype(int)
    late = partition[
        partition["collection_date"].eq(pd.Timestamp("2026-07-23"))
        & partition["scan_number"].between(1, 15)
        & partition["plot"].eq(1)
        & partition["side"].eq("right")
    ].copy()
    late["biological_plot"] = np.ceil(late["scan_number"] / 5).astype(int)
    partition = pd.concat([early, late], ignore_index=True)

    joined = []
    for name, frame in [("biomass", biomass), ("partition", partition)]:
        reference = truth[truth["sample_set"].eq(name)].copy()
        merged = frame.merge(
            reference,
            left_on=["collection_date", "biological_plot"],
            right_on=["collection_date", "plot"],
            suffixes=("", "_truth"),
        )
        means = (
            merged.groupby(["collection_date", "biological_plot"])
            .agg(
                conditional=("pai_m2_m2", "mean"),
                exact_first_event=("z_pai_m2_m2", "mean"),
                conditional_sd=("pai_m2_m2", "std"),
                exact_first_event_sd=("z_pai_m2_m2", "std"),
                dry_biomass_g_m2=("dry_biomass_g_m2", "first"),
                destructive_lai=("leaf_area_index_m2_m2", "first"),
                destructive_sai=("stem_area_index_m2_m2", "first"),
                destructive_pai=("plant_area_index_m2_m2", "first"),
            )
            .reset_index()
        )
        means.insert(0, "sample_set", name)
        joined.append(means)
    plot_means = pd.concat(joined, ignore_index=True)

    correlations = []
    for sample_set, group in plot_means.groupby("sample_set"):
        for reference in ["dry_biomass_g_m2", "destructive_lai", "destructive_pai"]:
            available = group.dropna(subset=[reference])
            for estimator in ["conditional", "exact_first_event"]:
                correlations.append(
                    {
                        "sample_set": sample_set,
                        "reference": reference,
                        "estimator": estimator,
                        "n_plot_date_means": len(available),
                        "pearson_r": available[reference].corr(available[estimator]),
                        "spearman_rho": available[reference].corr(
                            available[estimator], method="spearman"
                        ),
                        "raw_rmse_m2_m2": (
                            np.sqrt(
                                np.mean(
                                    (available[reference] - available[estimator]) ** 2
                                )
                            )
                            if reference != "dry_biomass_g_m2" and len(available)
                            else np.nan
                        ),
                    }
                )
    correlations = pd.DataFrame(correlations)

    stems = truth[truth["plant_area_index_m2_m2"].notna()].copy()
    stems["stem_fraction_of_pai"] = (
        stems["stem_area_index_m2_m2"] / stems["plant_area_index_m2_m2"]
    )
    stems["pai_relative_to_lai"] = (
        stems["plant_area_index_m2_m2"] / stems["leaf_area_index_m2_m2"]
    )
    return plot_means, correlations, stems


def old_whole_box_biomass_check() -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(STUDY / "biomass_test_results.csv")
    frame["collection_date"] = pd.to_datetime(
        frame["scan_id"].str.extract(r"(2026_\d\d_\d\d)")[0].str.replace("_", "-")
    )
    frame["scan_number"] = pd.to_numeric(frame["scan_id"].str.extract(r"scan_(\d+)")[0])
    frame["biological_plot"] = np.ceil(frame["scan_number"] / 5).astype(int)
    frame = frame[frame["row"].eq("right") & frame["scan_number"].isin([1, 6, 11])]
    frame["expected_marker"] = np.where(
        frame["collection_date"].eq(pd.Timestamp("2026-07-23")), 2, 1
    )
    frame = frame[frame["plot"].eq(frame["expected_marker"])]
    truth = pd.read_csv(STUDY / "biomass_groundtruth.csv")
    truth["collection_date"] = pd.to_datetime(truth["date"])
    truth = truth[
        truth["sample_set"].eq("biomass") & truth["canopy_section"].eq("whole")
    ]
    joined = frame.merge(
        truth,
        left_on=["collection_date", "biological_plot"],
        right_on=["collection_date", "plot"],
    )
    rows = []
    for estimator in ["pai_whole_box_m2_m2", "pai_m2_m2"]:
        rows.append(
            {
                "estimator": estimator,
                "n_single_scans": len(joined),
                "pearson_r_vs_dry_biomass": joined[estimator].corr(
                    joined["dry_biomass_g_m2"]
                ),
                "spearman_rho_vs_dry_biomass": joined[estimator].corr(
                    joined["dry_biomass_g_m2"], method="spearman"
                ),
            }
        )
    return joined, pd.DataFrame(rows)


def make_figure(summary, treatment, plot_means, old_whole):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)

    axes[0, 0].scatter(
        summary["pai_whole_box_m2_m2"], summary["z_pai_m2_m2"], s=8, alpha=0.35
    )
    limit = max(summary["pai_whole_box_m2_m2"].max(), summary["z_pai_m2_m2"].max())
    axes[0, 0].plot([0, limit], [0, limit], "k--", lw=1)
    axes[0, 0].set(xlabel="Whole-box PAI", ylabel="Exact first-event PAI", title="Corrected density run")

    for estimator, color in [("whole_box", "#3366cc"), ("exact_first_event", "#cc3311")]:
        group = treatment[
            treatment["estimator"].eq(estimator)
            & treatment["collection_date"].eq(pd.Timestamp("2026-07-09"))
        ]
        axes[0, 1].errorbar(
            group["treatment"], group["mean"], yerr=group["se"], marker="o", label=estimator, color=color
        )
    axes[0, 1].set(xlabel="Initial removal (%)", ylabel="PAI", title="July 9 treatment response")
    axes[0, 1].legend()

    biomass = plot_means[plot_means["sample_set"].eq("biomass")]
    axes[1, 0].scatter(biomass["dry_biomass_g_m2"], biomass["conditional"], label="conditional")
    axes[1, 0].scatter(
        biomass["dry_biomass_g_m2"], biomass["exact_first_event"], label="exact first-event"
    )
    axes[1, 0].set(xlabel="Dry biomass (g m$^{-2}$)", ylabel="PAI", title="Five-scan plot means")
    axes[1, 0].legend()

    axes[1, 1].scatter(
        old_whole["dry_biomass_g_m2"], old_whole["pai_whole_box_m2_m2"], label="whole-box"
    )
    axes[1, 1].scatter(old_whole["dry_biomass_g_m2"], old_whole["pai_m2_m2"], label="conditional")
    axes[1, 1].set(
        xlabel="Dry biomass (g m$^{-2}$)",
        ylabel="PAI",
        title="Older one-scan diagnostic (context only)",
    )
    axes[1, 1].legend()
    for axis in axes.flat:
        axis.grid(alpha=0.2)
    fig.savefig(OUT / "pai_estimator_diagnostics.png", dpi=180)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary, diagnostics = read_density()
    tables = density_tables(summary, diagnostics)
    names = [
        "density_estimator_summary.csv",
        "density_pairwise.csv",
        "density_opposite_view_agreement.csv",
        "density_repeatability.csv",
        "density_treatment_means.csv",
        "density_profile_support.csv",
    ]
    for name, table in zip(names, tables):
        table.to_csv(OUT / name, index=False)

    plot_means, correlations, stems = destructive_data()
    plot_means.to_csv(OUT / "destructive_plot_means.csv", index=False)
    correlations.to_csv(OUT / "destructive_correlations.csv", index=False)
    stems.to_csv(OUT / "destructive_stem_fraction.csv", index=False)

    old_whole, old_correlations = old_whole_box_biomass_check()
    old_correlations.to_csv(OUT / "older_whole_box_biomass_check.csv", index=False)
    make_figure(summary, tables[4], plot_means, old_whole)

    before = int(summary["pai_n_hits_before_box"].sum())
    intersecting = int(summary["pai_n_rays_intersecting_box"].sum())
    print(f"density summaries: {len(summary)}")
    print(f"pre-box returns: {before}/{intersecting} ({before / intersecting:.6%})")
    print(tables[0].to_string(index=False))
    print(tables[1].to_string(index=False))
    print(tables[2].to_string(index=False))
    print(tables[3].to_string(index=False))
    print(tables[5].to_string(index=False))
    print(correlations.to_string(index=False))
    print(old_correlations.to_string(index=False))
    print(
        "stem fraction of destructive PAI: "
        f"mean={stems['stem_fraction_of_pai'].mean():.3f}, "
        f"range={stems['stem_fraction_of_pai'].min():.3f}-"
        f"{stems['stem_fraction_of_pai'].max():.3f}"
    )


if __name__ == "__main__":
    main()
