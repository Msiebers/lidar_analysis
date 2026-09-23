from __future__ import annotations

import csv
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lidar_analysis.research_delivery_layout import (
    GraphSpec,
    date_graph_data_file,
    date_graph_dir,
    growth_graph_data_file,
    growth_graph_file,
)


METRIC_LABELS = {
    "points": "Point count",
    "point_density_m2": "Point density (points/m²)",
    "stand_topo_per_m": "Topological stand count (stands/m)",
}
PNG_METADATA = {"Software": "lidar_analysis research delivery"}


def _metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def _date_label(date: str) -> str:
    return date.replace("_", "-")


def _row_label(row: Mapping[str, object], rank: int) -> str:
    row_number = str(row.get("row", "")).strip()
    plot_number = str(row.get("plot", "")).strip()
    if row_number and plot_number:
        return f"R{row_number} P{plot_number}"
    if plot_number:
        return f"Plot {plot_number}"
    scan_id = str(row.get("scan_id", "")).strip()
    return scan_id or f"Rank {rank}"


def _save_figure(figure: Any, path: Path, *, dpi: int, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        path,
        dpi=dpi,
        format="png",
        bbox_inches="tight",
        metadata={**PNG_METADATA, "Description": description},
    )


GRAPH_DATA_FIELDS = (
    "date",
    "scan_id",
    "row",
    "plot",
    "metric",
    "value",
    "qc_status",
    "is_outlier",
    "outlier_direction",
)


def _write_graph_data_csv(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    """Write the canonical, row-identified data behind one graph.

    This is the single source researchers use to trace a plotted point (or an
    outlier) back to its scan_id/row/plot. It is not a duplicate of any other
    file: the ranking chart reuses the existing per-date ranking CSV instead
    of getting one of these.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GRAPH_DATA_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in GRAPH_DATA_FIELDS})


def _plot_distribution(
    pyplot: Any,
    *,
    path: Path,
    experiment: str,
    date: str,
    metric: str,
    values: Sequence[float],
    dpi: int,
) -> None:
    figure, axis = pyplot.subplots(figsize=(9.0, 5.5), constrained_layout=True)
    try:
        bins = min(20, max(5, round(len(values) ** 0.5)))
        axis.hist(values, bins=bins, color="#2878B5", edgecolor="white", linewidth=0.8)
        axis.set_title(
            f"{experiment}: {_metric_label(metric)} distribution\n"
            f"Scan date {_date_label(date)} • n={len(values):,} QC-eligible rows"
        )
        axis.set_xlabel(_metric_label(metric))
        axis.set_ylabel("Number of result rows")
        axis.grid(axis="y", alpha=0.25)
        _save_figure(
            figure,
            path,
            dpi=dpi,
            description=(
                f"Distribution of {metric} for {experiment} on {date}; "
                f"n={len(values)} QC-eligible rows."
            ),
        )
    finally:
        pyplot.close(figure)


def _plot_top_fraction(
    pyplot: Any,
    *,
    path: Path,
    experiment: str,
    date: str,
    metric: str,
    fraction: float,
    include_ties: bool,
    rows: Sequence[Mapping[str, object]],
    dpi: int,
) -> None:
    values = [float(row["_ranking_value"]) for row in rows]
    cutoff = float(rows[0]["_ranking_cutoff"])
    eligible_rows = int(rows[0]["_ranking_eligible_rows"])
    labels = [_row_label(row, rank) for rank, row in enumerate(rows, start=1)]
    width = min(16.0, max(9.0, 0.34 * len(rows) + 5.0))
    figure, axis = pyplot.subplots(figsize=(width, 6.2), constrained_layout=True)
    try:
        positions = list(range(len(rows)))
        axis.bar(positions, values, color="#F28E2B", edgecolor="#9A5700", linewidth=0.6)
        axis.axhline(
            cutoff,
            color="#B22222",
            linestyle="--",
            linewidth=1.5,
            label=f"Cutoff: {cutoff:g}",
        )
        percent = fraction * 100.0
        tie_note = "cutoff ties included" if include_ties else "exact cutoff count"
        axis.set_title(
            f"{experiment}: top {percent:g}% by {_metric_label(metric)}\n"
            f"Scan date {_date_label(date)} • {len(rows):,} selected of "
            f"{eligible_rows:,} eligible rows ({tie_note})"
        )
        axis.set_xlabel("Selected row / plot (ranking order)")
        axis.set_ylabel(_metric_label(metric))
        axis.set_xticks(positions, labels, rotation=55, ha="right")
        axis.grid(axis="y", alpha=0.25)
        axis.legend(loc="best")
        _save_figure(
            figure,
            path,
            dpi=dpi,
            description=(
                f"Top {percent:g}% ranking for {metric} in {experiment} on {date}; "
                f"selected={len(rows)}, eligible={eligible_rows}, cutoff={cutoff:g}."
            ),
        )
    finally:
        pyplot.close(figure)


def _plot_by_date(
    pyplot: Any,
    *,
    path: Path,
    experiment: str,
    metric: str,
    values_by_date: Sequence[tuple[str, Sequence[float]]],
    exploratory: bool,
    dpi: int,
) -> None:
    dates = [date for date, _values in values_by_date]
    value_groups = [list(values) for _date, values in values_by_date]
    labels = [
        f"{_date_label(date)}\n(n={len(values):,})"
        for date, values in values_by_date
    ]
    figure, axis = pyplot.subplots(figsize=(9.5, 6.2), constrained_layout=True)
    try:
        boxplot = axis.boxplot(
            value_groups,
            tick_labels=labels,
            patch_artist=True,
            widths=0.55,
            medianprops={"color": "#B22222", "linewidth": 1.8},
        )
        for patch in boxplot["boxes"]:
            patch.set_facecolor("#59A14F")
            patch.set_alpha(0.7)
        axis.set_title(
            f"{experiment}: {_metric_label(metric)} by scan date\n"
            f"{sum(len(values) for values in value_groups):,} total QC-eligible rows"
        )
        if exploratory:
            figure.suptitle(
                "EXPLORATORY ONLY — historical analysis configurations differ or are unavailable",
                color="#B22222",
                fontsize=11,
                fontweight="bold",
            )
        axis.set_xlabel("Scan date")
        axis.set_ylabel(_metric_label(metric))
        axis.grid(axis="y", alpha=0.25)
        exploratory_text = " EXPLORATORY ONLY." if exploratory else ""
        _save_figure(
            figure,
            path,
            dpi=dpi,
            description=(
                f"{metric} by scan date for {experiment}; dates={','.join(dates)}."
                f"{exploratory_text}"
            ),
        )
    finally:
        pyplot.close(figure)


def generate_delivery_graphs(
    root: Path,
    *,
    experiment: str,
    graph_specs: Sequence[GraphSpec],
    top_fraction: float,
    ranking_directory: str,
    include_ties: bool,
    graph_dpi: int,
    date_metric_rows: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    date_rankings: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    exploratory: bool,
) -> list[str]:
    """Generate the requested preview PNGs (plus graph-data CSVs) for ``graph_specs``.

    Returns the sorted PNG paths relative to ``root``. Each histogram/boxplot PNG
    gets a companion CSV of the rows it plots (see ``_write_graph_data_csv``); the
    ranking PNG has no companion because its data already lives in the per-date
    ranking CSV under ``results/<ranking_dir>/<metric>.csv``.
    """
    cache_dir = root / ".matplotlib-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    previous_mplconfigdir = os.environ.get("MPLCONFIGDIR")
    os.environ["MPLCONFIGDIR"] = str(cache_dir)

    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        if hasattr(matplotlib.get_cachedir, "cache_clear"):
            matplotlib.get_cachedir.cache_clear()
        from matplotlib import pyplot

        graph_paths: list[Path] = []
        dates = sorted(date_metric_rows)

        for spec in graph_specs:
            if spec.type == "histogram":
                for date in dates:
                    records = date_metric_rows.get(date, {}).get(spec.metric, ())
                    if not records:
                        continue
                    values = [record["value"] for record in records]
                    path = root / date_graph_dir(date) / f"{spec.metric}_distribution.png"
                    _plot_distribution(
                        pyplot,
                        path=path,
                        experiment=experiment,
                        date=date,
                        metric=spec.metric,
                        values=values,
                        dpi=graph_dpi,
                    )
                    _write_graph_data_csv(
                        root / date_graph_data_file(date, f"{spec.metric}_distribution"),
                        records,
                    )
                    graph_paths.append(path)

            elif spec.type == "ranking":
                for date in dates:
                    selected = date_rankings.get(date, {}).get(spec.metric, ())
                    if not selected:
                        continue
                    path = root / date_graph_dir(date) / f"{spec.metric}_{ranking_directory}.png"
                    _plot_top_fraction(
                        pyplot,
                        path=path,
                        experiment=experiment,
                        date=date,
                        metric=spec.metric,
                        fraction=top_fraction,
                        include_ties=include_ties,
                        rows=selected,
                        dpi=graph_dpi,
                    )
                    graph_paths.append(path)

            elif spec.type == "boxplot":
                values_by_date = [
                    (date, [record["value"] for record in date_metric_rows[date][spec.metric]])
                    for date in dates
                    if date_metric_rows.get(date, {}).get(spec.metric)
                ]
                if not values_by_date:
                    continue
                path = root / growth_graph_file(spec.metric)
                _plot_by_date(
                    pyplot,
                    path=path,
                    experiment=experiment,
                    metric=spec.metric,
                    values_by_date=values_by_date,
                    exploratory=exploratory,
                    dpi=graph_dpi,
                )
                all_records = [
                    record
                    for date in dates
                    for record in date_metric_rows.get(date, {}).get(spec.metric, ())
                ]
                _write_graph_data_csv(root / growth_graph_data_file(spec.metric), all_records)
                graph_paths.append(path)

            else:
                raise ValueError(f"Unsupported graph type: {spec.type!r}")

        return sorted(str(path.relative_to(root)) for path in graph_paths)
    finally:
        try:
            pyplot.close("all")
        except (NameError, AttributeError):
            pass
        shutil.rmtree(cache_dir, ignore_errors=True)
        if previous_mplconfigdir is None:
            os.environ.pop("MPLCONFIGDIR", None)
        else:
            os.environ["MPLCONFIGDIR"] = previous_mplconfigdir
        try:
            matplotlib.get_cachedir.cache_clear()
        except (NameError, AttributeError):
            pass
