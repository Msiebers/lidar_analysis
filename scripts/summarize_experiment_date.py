#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable


SUMMARY_FIELDS = [
    "experiment",
    "date",
    "input_dir",
    "output_dir",
    "lidar_files",
    "pico_files",
    "scan_pairs",
    "marker_files",
    "has_cart_config",
    "has_experiment_config",
    "has_results_csv",
    "results_rows",
    "pointcloud_files",
    "topology_pointcloud_files",
    "total_points",
    "mean_points",
    "mean_height_m",
    "mean_stand_topo_per_m",
    "mean_point_density_m2",
    "qc_issue_count",
    "overall_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize one LiDAR experiment date into Markdown, summary CSV, and QC flags CSV."
    )
    parser.add_argument("--experiment", help="Experiment name for the summary. Defaults to input parent folder.")
    parser.add_argument("--date", help="Date name for the summary. Defaults to input folder name.")
    parser.add_argument("--input", required=True, help="Date input/source folder containing raw CSVs and cart_config.yaml.")
    parser.add_argument("--output", required=True, help="Analysis output folder containing results.csv and pointclouds/.")
    parser.add_argument(
        "--summary-dir",
        help="Folder to write date_summary.md, date_summary.csv, and qc_flags.csv. Default: output folder.",
    )
    return parser.parse_args()


def count_files(folder: Path, pattern: str) -> int:
    if not folder.exists():
        return 0
    return sum(1 for p in folder.glob(pattern) if p.is_file())


def count_files_recursive(folder: Path, pattern: str) -> int:
    if not folder.exists():
        return 0
    return sum(1 for p in folder.rglob(pattern) if p.is_file())


def scan_bases(folder: Path, suffix: str) -> set[str]:
    if not folder.exists():
        return set()
    return {p.name[: -len(suffix)] for p in folder.glob(f"*{suffix}") if p.is_file()}


def read_results(path: Path) -> tuple[list[dict[str, str]], list[str], str | None]:
    if not path.exists():
        return [], [], None
    try:
        with path.open("r", newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, list(reader.fieldnames or []), None
    except Exception as exc:
        return [], [], str(exc)


def as_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def numeric_values(rows: Iterable[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = as_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.6g}"
    return str(value)


def add_flag(flags: list[dict[str, str]], severity: str, category: str, message: str) -> None:
    flags.append({"severity": severity, "category": category, "message": message})


def summarize(args: argparse.Namespace) -> tuple[dict[str, object], list[dict[str, str]], list[str], dict[str, list[float]]]:
    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    summary_dir = Path(args.summary_dir).expanduser().resolve() if args.summary_dir else output_dir

    experiment = args.experiment or input_dir.parent.name
    date_name = args.date or input_dir.name

    lidar_files = count_files(input_dir, "*_lidar.csv")
    pico_files = count_files(input_dir, "*_pico.csv")
    lidar_bases = scan_bases(input_dir, "_lidar.csv")
    pico_bases = scan_bases(input_dir, "_pico.csv")
    scan_pairs = len(lidar_bases & pico_bases)

    markers_dir = input_dir / "markers"
    marker_files = count_files(markers_dir, "*.csv")
    has_cart_config = (input_dir / "cart_config.yaml").exists()
    has_experiment_config = (input_dir / "experiment_config.yaml").exists()

    results_csv = output_dir / "results.csv"
    rows, fieldnames, read_error = read_results(results_csv)
    pointcloud_dir = output_dir / "pointclouds"
    pointcloud_files = count_files_recursive(pointcloud_dir, "*.csv")
    topology_pointcloud_files = count_files_recursive(pointcloud_dir, "topology_count_*.csv")

    flags: list[dict[str, str]] = []
    if not input_dir.exists():
        add_flag(flags, "error", "input", f"Input folder does not exist: {input_dir}")
    if lidar_files == 0:
        add_flag(flags, "error", "input", "No *_lidar.csv files found in the input folder.")
    if pico_files == 0:
        add_flag(flags, "error", "input", "No *_pico.csv files found in the input folder.")
    if lidar_files != pico_files:
        add_flag(flags, "warning", "input", f"LiDAR/Pico file counts differ: {lidar_files} vs {pico_files}.")
    if scan_pairs == 0 and (lidar_files or pico_files):
        add_flag(flags, "error", "input", "No matching LiDAR/Pico scan base names were found.")
    if not has_cart_config:
        add_flag(flags, "error", "input", "Missing cart_config.yaml in the input folder.")
    if not has_experiment_config:
        add_flag(flags, "info", "input", "No experiment_config.yaml in the input folder; an external --config may have been used.")
    if not results_csv.exists():
        add_flag(flags, "error", "output", f"Missing results.csv: {results_csv}")
    if read_error:
        add_flag(flags, "error", "output", f"Could not read results.csv: {read_error}")
    if results_csv.exists() and not rows:
        add_flag(flags, "error", "output", "results.csv exists but has no result rows.")
    if pointcloud_files == 0:
        add_flag(flags, "warning", "output", "No point-cloud CSV files found under output/pointclouds.")

    metrics = {
        "points": numeric_values(rows, "points"),
        "height_m": numeric_values(rows, "height_m"),
        "stand_topo_per_m": numeric_values(rows, "stand_topo_per_m"),
        "point_density_m2": numeric_values(rows, "point_density_m2"),
        "voxel_count": numeric_values(rows, "voxel_count"),
    }

    if rows and "points" in fieldnames and not metrics["points"]:
        add_flag(flags, "warning", "results", "The points column exists but has no numeric values.")
    if rows and "height_m" in fieldnames and not metrics["height_m"]:
        add_flag(flags, "warning", "results", "height_m is present but all values are blank/NaN.")
    if rows and "stand_topo_per_m" in fieldnames and not metrics["stand_topo_per_m"]:
        add_flag(flags, "warning", "results", "stand_topo_per_m is present but all values are blank/NaN.")

    zero_point_rows = sum(1 for row in rows if as_float(row.get("points")) == 0.0)
    if zero_point_rows:
        add_flag(flags, "warning", "results", f"{zero_point_rows} result row(s) have zero points.")

    error_count = sum(1 for flag in flags if flag["severity"] == "error")
    warning_count = sum(1 for flag in flags if flag["severity"] == "warning")
    if error_count:
        overall_status = "not usable until errors are fixed"
    elif warning_count:
        overall_status = "usable with review"
    else:
        overall_status = "usable"

    summary: dict[str, object] = {
        "experiment": experiment,
        "date": date_name,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "summary_dir": str(summary_dir),
        "lidar_files": lidar_files,
        "pico_files": pico_files,
        "scan_pairs": scan_pairs,
        "marker_files": marker_files,
        "has_cart_config": has_cart_config,
        "has_experiment_config": has_experiment_config,
        "has_results_csv": results_csv.exists() and read_error is None,
        "results_rows": len(rows),
        "results_columns": ", ".join(fieldnames),
        "pointcloud_files": pointcloud_files,
        "topology_pointcloud_files": topology_pointcloud_files,
        "total_points": sum(metrics["points"]) if metrics["points"] else None,
        "mean_points": mean(metrics["points"]),
        "mean_height_m": mean(metrics["height_m"]),
        "mean_stand_topo_per_m": mean(metrics["stand_topo_per_m"]),
        "mean_point_density_m2": mean(metrics["point_density_m2"]),
        "mean_voxel_count": mean(metrics["voxel_count"]),
        "qc_issue_count": len(flags),
        "overall_status": overall_status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return summary, flags, fieldnames, metrics


def write_summary_csv(summary: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerow({field: summary.get(field) for field in SUMMARY_FIELDS})


def write_flags_csv(flags: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["severity", "category", "message"])
        writer.writeheader()
        writer.writerows(flags)


def write_markdown(summary: dict[str, object], flags: list[dict[str, str]], path: Path) -> None:
    lines = [
        f"# Date Summary: {summary['experiment']} {summary['date']}",
        "",
        f"Created: {summary['created_at']}",
        "",
        "## Overall Status",
        "",
        str(summary["overall_status"]),
        "",
        "## Inputs Found",
        "",
        f"- Input folder: `{summary['input_dir']}`",
        f"- LiDAR files: {summary['lidar_files']}",
        f"- Pico files: {summary['pico_files']}",
        f"- Matched scan pairs: {summary['scan_pairs']}",
        f"- `cart_config.yaml`: {summary['has_cart_config']}",
        f"- `experiment_config.yaml`: {summary['has_experiment_config']}",
        f"- Marker CSV files: {summary['marker_files']}",
        "",
        "## Outputs Created",
        "",
        f"- Output folder: `{summary['output_dir']}`",
        f"- `results.csv`: {summary['has_results_csv']}",
        f"- Result rows: {summary['results_rows']}",
        f"- Point-cloud CSV files: {summary['pointcloud_files']}",
        f"- Topology count CSV files: {summary['topology_pointcloud_files']}",
        "",
        "## Main Numeric Results",
        "",
        f"- Total points: {fmt(summary['total_points'])}",
        f"- Mean points per result row: {fmt(summary['mean_points'])}",
        f"- Mean height_m: {fmt(summary['mean_height_m'])}",
        f"- Mean stand_topo_per_m: {fmt(summary['mean_stand_topo_per_m'])}",
        f"- Mean point_density_m2: {fmt(summary['mean_point_density_m2'])}",
        f"- Mean voxel_count: {fmt(summary['mean_voxel_count'])}",
        "",
        "## Possible Issues",
        "",
    ]

    if flags:
        for flag in flags:
            lines.append(f"- [{flag['severity']}] {flag['category']}: {flag['message']}")
    else:
        lines.append("- No automatic QC issues found.")

    lines.extend(
        [
            "",
            "## CloudCompare Notes",
            "",
            "Add 2-3 sentences after inspecting a few point-cloud CSVs.",
            "",
            "## Result Columns",
            "",
            summary.get("results_columns") or "No result columns available.",
            "",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(line) for line in lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    summary, flags, _fieldnames, _metrics = summarize(args)
    summary_dir = Path(summary["summary_dir"])

    md_path = summary_dir / "date_summary.md"
    summary_csv_path = summary_dir / "date_summary.csv"
    flags_csv_path = summary_dir / "qc_flags.csv"

    write_markdown(summary, flags, md_path)
    write_summary_csv(summary, summary_csv_path)
    write_flags_csv(flags, flags_csv_path)

    print(f"Wrote: {md_path}")
    print(f"Wrote: {summary_csv_path}")
    print(f"Wrote: {flags_csv_path}")
    print(f"Overall status: {summary['overall_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
