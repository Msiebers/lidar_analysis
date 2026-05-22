#!/usr/bin/env python3
"""
Plot PCL summary metrics for LiDAR plant/plot outputs.

Creates:
  - height_hist_box.png
  - voxel_hist_box.png
  - height_boxplot.png
  - voxel_boxplot.png

Expected input CSV columns from the summary script:
  - pcl_voxel_count
  - height_extent_m or height_y_max_m
  - optional row
  - optional plant
  - optional file
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def clean_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    values = values[values.notna()]
    values = values[values.apply(math.isfinite)]
    return values


def outlier_limits(values: pd.Series) -> tuple[float, float, float, float]:
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return q1, q3, low, high


def plot_hist_with_box(values: pd.Series, title: str, xlabel: str, output_path: Path) -> None:
    fig, axes = plt.subplots(
        nrows=2,
        ncols=1,
        figsize=(9, 6),
        gridspec_kw={"height_ratios": [1, 4]},
        sharex=True,
    )

    axes[0].boxplot(values, vert=False, showfliers=True)
    axes[0].set_title(title)
    axes[0].set_yticks([])

    axes[1].hist(values, bins="auto")
    axes[1].set_xlabel(xlabel)
    axes[1].set_ylabel("Count")

    q1, q3, low, high = outlier_limits(values)
    n_outliers = int(((values < low) | (values > high)).sum())

    text = (
        f"n = {len(values)}\n"
        f"median = {values.median():.4g}\n"
        f"mean = {values.mean():.4g}\n"
        f"IQR = {q1:.4g} to {q3:.4g}\n"
        f"outliers = {n_outliers}"
    )

    axes[1].text(
        0.98,
        0.95,
        text,
        transform=axes[1].transAxes,
        ha="right",
        va="top",
        bbox={"boxstyle": "round", "alpha": 0.15},
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_boxplot(values: pd.Series, title: str, ylabel: str, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5, 7))

    ax.boxplot(values, vert=True, showfliers=True)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks([1])
    ax.set_xticklabels(["All plants"])

    q1, q3, low, high = outlier_limits(values)
    n_outliers = int(((values < low) | (values > high)).sum())

    text = (
        f"n = {len(values)}\n"
        f"median = {values.median():.4g}\n"
        f"mean = {values.mean():.4g}\n"
        f"outliers = {n_outliers}"
    )

    ax.text(
        0.98,
        0.95,
        text,
        transform=ax.transAxes,
        ha="right",
        va="top",
        bbox={"boxstyle": "round", "alpha": 0.15},
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def write_outlier_csv(df: pd.DataFrame, metric_col: str, output_path: Path) -> None:
    values = clean_numeric(df[metric_col])
    q1, q3, low, high = outlier_limits(values)

    tmp = df.copy()
    tmp[metric_col] = pd.to_numeric(tmp[metric_col], errors="coerce")
    outliers = tmp[(tmp[metric_col] < low) | (tmp[metric_col] > high)].copy()

    keep_cols = []
    for col in ["row", "plant", "file", metric_col, "original_points", "pcl_voxel_count"]:
        if col in outliers.columns and col not in keep_cols:
            keep_cols.append(col)

    if keep_cols:
        outliers = outliers[keep_cols]

    outliers.to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create histogram + boxplot summaries for PCL height and voxel metrics."
    )
    parser.add_argument(
        "summary_csv",
        help="Path to pcl_results_summary_*.csv",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for plots. Default: same folder as summary CSV.",
    )
    parser.add_argument(
        "--height-col",
        default=None,
        help="Height column to plot. Default: height_extent_m if present, else height_y_max_m.",
    )
    parser.add_argument(
        "--voxel-col",
        default="pcl_voxel_count",
        help="Voxel count column to plot. Default: pcl_voxel_count.",
    )

    args = parser.parse_args()

    summary_csv = Path(args.summary_csv).expanduser().resolve()
    if not summary_csv.exists():
        raise SystemExit(f"Summary CSV not found: {summary_csv}")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else summary_csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(summary_csv)

    if args.height_col:
        height_col = args.height_col
    elif "height_extent_m" in df.columns:
        height_col = "height_extent_m"
    elif "height_y_max_m" in df.columns:
        height_col = "height_y_max_m"
    else:
        raise SystemExit(
            "No height column found. Expected height_extent_m or height_y_max_m, "
            "or pass --height-col."
        )

    voxel_col = args.voxel_col

    if height_col not in df.columns:
        raise SystemExit(f"Height column not found: {height_col}")

    if voxel_col not in df.columns:
        raise SystemExit(f"Voxel column not found: {voxel_col}")

    height_values = clean_numeric(df[height_col])
    voxel_values = clean_numeric(df[voxel_col])

    if height_values.empty:
        raise SystemExit(f"No numeric values found in {height_col}")

    if voxel_values.empty:
        raise SystemExit(f"No numeric values found in {voxel_col}")

    plot_hist_with_box(
        height_values,
        title=f"Height distribution ({height_col})",
        xlabel="Height (m)",
        output_path=out_dir / "height_hist_box.png",
    )

    plot_hist_with_box(
        voxel_values,
        title=f"Voxel count distribution ({voxel_col})",
        xlabel="Voxel count",
        output_path=out_dir / "voxel_hist_box.png",
    )

    plot_boxplot(
        height_values,
        title=f"Height boxplot ({height_col})",
        ylabel="Height (m)",
        output_path=out_dir / "height_boxplot.png",
    )

    plot_boxplot(
        voxel_values,
        title=f"Voxel count boxplot ({voxel_col})",
        ylabel="Voxel count",
        output_path=out_dir / "voxel_boxplot.png",
    )

    write_outlier_csv(df, height_col, out_dir / "height_outliers.csv")
    write_outlier_csv(df, voxel_col, out_dir / "voxel_outliers.csv")

    print(f"Wrote plots to: {out_dir}")
    print(f"  {out_dir / 'height_hist_box.png'}")
    print(f"  {out_dir / 'voxel_hist_box.png'}")
    print(f"  {out_dir / 'height_boxplot.png'}")
    print(f"  {out_dir / 'voxel_boxplot.png'}")
    print(f"  {out_dir / 'height_outliers.csv'}")
    print(f"  {out_dir / 'voxel_outliers.csv'}")


if __name__ == "__main__":
    main()
