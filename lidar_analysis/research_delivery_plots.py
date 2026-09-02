from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


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
    metrics: Sequence[str],
    top_fraction: float,
    ranking_directory: str,
    include_ties: bool,
    graph_dpi: int,
    date_metric_values: Mapping[str, Mapping[str, Sequence[float]]],
    date_rankings: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    latest_usable_date: str | None,
    exploratory: bool,
) -> list[str]:
    """Generate preview PNGs and return their sorted paths relative to ``root``."""
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
        for date in sorted(date_metric_values):
            for metric in metrics:
                values = date_metric_values[date].get(metric, ())
                selected = date_rankings.get(date, {}).get(metric, ())
                if not values or not selected:
                    continue
                distribution_path = (
                    root / date / "results" / "graphs" / f"{metric}_distribution.png"
                )
                ranking_path = (
                    root
                    / date
                    / "results"
                    / "graphs"
                    / f"{metric}_{ranking_directory}.png"
                )
                _plot_distribution(
                    pyplot,
                    path=distribution_path,
                    experiment=experiment,
                    date=date,
                    metric=metric,
                    values=values,
                    dpi=graph_dpi,
                )
                _plot_top_fraction(
                    pyplot,
                    path=ranking_path,
                    experiment=experiment,
                    date=date,
                    metric=metric,
                    fraction=top_fraction,
                    include_ties=include_ties,
                    rows=selected,
                    dpi=graph_dpi,
                )
                graph_paths.extend((distribution_path, ranking_path))

        for metric in metrics:
            values_by_date = [
                (date, date_metric_values[date][metric])
                for date in sorted(date_metric_values)
                if date_metric_values[date].get(metric)
            ]
            if not values_by_date:
                continue
            summary_path = root / "summary" / "graphs" / f"{metric}_by_date.png"
            _plot_by_date(
                pyplot,
                path=summary_path,
                experiment=experiment,
                metric=metric,
                values_by_date=values_by_date,
                exploratory=exploratory,
                dpi=graph_dpi,
            )
            graph_paths.append(summary_path)

        if latest_usable_date is not None:
            latest_graph_dir = root / latest_usable_date / "results" / "graphs"
            latest_copy_dir = (
                root
                / "summary"
                / f"latest_date_{ranking_directory}"
                / "graphs"
            )
            for metric in metrics:
                source = latest_graph_dir / f"{metric}_{ranking_directory}.png"
                if not source.is_file():
                    continue
                destination = latest_copy_dir / f"{metric}.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                graph_paths.append(destination)

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
