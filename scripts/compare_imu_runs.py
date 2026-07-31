#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SUMMARY_COLUMNS = [
    "run_id",
    "output_folder",
    "results_rows",
    "pointcloud_csv_files",
    "total_points",
    "mean_height_m",
    "median_height_m",
    "min_height_m",
    "max_height_m",
    "mean_point_density_m2",
    "missing_or_failed_outputs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine and summarize offline IMU test outputs on SLIM."
    )
    parser.add_argument(
        "--run-root",
        required=True,
        help="Output root created by scripts/run_imu_tests.sh, for example /PATH/TO/IMU_OUTPUT_ROOT",
    )
    parser.add_argument(
        "--outputs-dir",
        help="Optional explicit outputs directory. Defaults to <run-root>/outputs.",
    )
    parser.add_argument(
        "--all-results",
        help="Optional output CSV path. Defaults to <run-root>/imu_all_results.csv.",
    )
    parser.add_argument(
        "--summary",
        help="Optional summary CSV path. Defaults to <run-root>/imu_comparison_summary.csv.",
    )
    return parser.parse_args()


def _pointcloud_count(run_dir: Path) -> int:
    pointcloud_dir = run_dir / "pointclouds"
    if not pointcloud_dir.exists():
        return 0
    return sum(1 for _ in pointcloud_dir.glob("*.csv"))


def _safe_stat(df: pd.DataFrame, column: str, stat: str):
    if column not in df.columns:
        return None

    values = pd.to_numeric(df[column], errors="coerce")
    if values.dropna().empty:
        return None

    if stat == "sum":
        return float(values.sum())
    if stat == "mean":
        return float(values.mean())
    if stat == "median":
        return float(values.median())
    if stat == "min":
        return float(values.min())
    if stat == "max":
        return float(values.max())

    raise ValueError(f"Unsupported stat: {stat}")


def _summary_for_missing(run_id: str, run_dir: Path, pointcloud_count: int) -> dict:
    row = {column: None for column in SUMMARY_COLUMNS}
    row.update(
        {
            "run_id": run_id,
            "output_folder": str(run_dir),
            "results_rows": 0,
            "pointcloud_csv_files": pointcloud_count,
            "missing_or_failed_outputs": 1,
        }
    )
    return row


def main() -> int:
    args = parse_args()

    run_root = Path(args.run_root).expanduser().resolve()
    outputs_dir = Path(args.outputs_dir).expanduser().resolve() if args.outputs_dir else run_root / "outputs"
    all_results_path = Path(args.all_results).expanduser().resolve() if args.all_results else run_root / "imu_all_results.csv"
    summary_path = Path(args.summary).expanduser().resolve() if args.summary else run_root / "imu_comparison_summary.csv"

    result_frames: list[pd.DataFrame] = []
    summary_rows: list[dict] = []
    warnings: list[str] = []

    if not outputs_dir.exists():
        warnings.append(f"outputs directory does not exist: {outputs_dir}")
        run_dirs: list[Path] = []
    else:
        run_dirs = sorted(p for p in outputs_dir.iterdir() if p.is_dir())

    if not run_dirs:
        warnings.append(f"no run directories found under: {outputs_dir}")

    for run_dir in run_dirs:
        run_id = run_dir.name
        results_csv = run_dir / "results.csv"
        pc_count = _pointcloud_count(run_dir)

        if not results_csv.exists():
            warnings.append(f"missing results.csv for {run_id}: {results_csv}")
            summary_rows.append(_summary_for_missing(run_id, run_dir, pc_count))
            continue

        try:
            df = pd.read_csv(results_csv)
        except Exception as exc:
            warnings.append(f"could not read results.csv for {run_id}: {exc}")
            summary_rows.append(_summary_for_missing(run_id, run_dir, pc_count))
            continue

        df.insert(0, "output_folder", str(run_dir))
        df.insert(0, "run_id", run_id)
        result_frames.append(df)

        summary_rows.append(
            {
                "run_id": run_id,
                "output_folder": str(run_dir),
                "results_rows": int(len(df)),
                "pointcloud_csv_files": pc_count,
                "total_points": _safe_stat(df, "points", "sum"),
                "mean_height_m": _safe_stat(df, "height_m", "mean"),
                "median_height_m": _safe_stat(df, "height_m", "median"),
                "min_height_m": _safe_stat(df, "height_m", "min"),
                "max_height_m": _safe_stat(df, "height_m", "max"),
                "mean_point_density_m2": _safe_stat(df, "point_density_m2", "mean"),
                "missing_or_failed_outputs": 0,
            }
        )

    if result_frames:
        all_results = pd.concat(result_frames, ignore_index=True, sort=False)
    else:
        all_results = pd.DataFrame(columns=["run_id", "output_folder"])

    summary = pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)

    all_results_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    all_results.to_csv(all_results_path, index=False)
    summary.to_csv(summary_path, index=False)

    for warning in warnings:
        print(f"WARNING: {warning}")

    print(f"Saved combined results: {all_results_path}")
    print(f"Saved summary: {summary_path}")
    if not summary.empty:
        print(summary.to_csv(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
