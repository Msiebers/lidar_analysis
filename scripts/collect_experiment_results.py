#!/usr/bin/env python3

from pathlib import Path
import argparse
import csv
import re
import sys


DATE_DIR_RE = re.compile(r"^\d{4}([_\-\s])\d{2}\1\d{2}$")

# Final column order for the combined output.
# scan_id, source_results_file, source_date_folder, lidar_scans, and lidar_angles are intentionally omitted.
OUTPUT_COLUMNS = [
    "experiment",
    "date",
    "row",
    "plot",
    "height_m",
    "point_density_m2",
    "plot_length_m",
    "plot_width_m",
    "voxel_count",
    "points",
]


def normalized_date_name(name: str) -> str:
    return name.replace("-", "_").replace(" ", "_")


def clean_plot_value(value: str) -> str:
    """
    Convert plant_1 -> 1, plant_21 -> 21.
    Leaves other plot labels alone.
    """
    value = str(value).strip()
    if value.startswith("plant_"):
        return value.replace("plant_", "", 1)
    return value


def find_results_files(experiment_dir: Path, filename: str) -> list[Path]:
    """
    Find date-level results.csv files anywhere under the experiment folder.

    Works with:
        Experiment/2026_05_28/results.csv
        Experiment/2026_05_28/results/results.csv
        Experiment/2026_05_28/results/traits/results.csv
    """
    files = []

    for path in sorted(experiment_dir.rglob(filename)):
        if not path.is_file():
            continue

        path_lower = str(path).lower()

        # Skip combined outputs if rerunning.
        if "combined_results" in path_lower:
            continue

        # Skip anything inside a top-level Experiment/results folder.
        try:
            rel = path.relative_to(experiment_dir)
        except ValueError:
            continue

        if len(rel.parts) >= 2 and rel.parts[0] == "results":
            continue

        files.append(path)

    return files


def get_date_from_path(path: Path) -> str:
    """
    Find nearest date-looking parent folder.
    """
    for parent in path.parents:
        if DATE_DIR_RE.match(parent.name):
            return normalized_date_name(parent.name)
    return ""


def inspect_csv_files(files: list[Path]) -> dict[Path, int]:
    """
    Count rows in each source CSV for the file summary.
    """
    row_counts = {}

    for path in files:
        count = 0
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for _ in reader:
                count += 1
        row_counts[path] = count

    return row_counts


def combine_csv_files(files: list[Path], output_csv: Path) -> int:
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0

    with output_csv.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for path in files:
            date_from_folder = get_date_from_path(path)

            with path.open("r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    clean_row = {col: row.get(col, "") for col in OUTPUT_COLUMNS}

                    # If date is missing in a file, recover it from the folder name.
                    if not clean_row.get("date") and date_from_folder:
                        clean_row["date"] = date_from_folder

                    # plant_1 -> 1
                    clean_row["plot"] = clean_plot_value(clean_row.get("plot", ""))

                    writer.writerow(clean_row)
                    total_rows += 1

    return total_rows


def write_file_summary(summary_csv: Path, row_counts: dict[Path, int]) -> None:
    """
    Keep a small audit file, but do not put source file paths in the main combined CSV.
    """
    summary_csv.parent.mkdir(parents=True, exist_ok=True)

    with summary_csv.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(
            out,
            fieldnames=["source_date_folder", "rows"],
        )
        writer.writeheader()

        for path, rows in sorted(row_counts.items()):
            writer.writerow(
                {
                    "source_date_folder": get_date_from_path(path),
                    "rows": rows,
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine date-level LiDAR results CSV files for one experiment."
    )
    parser.add_argument(
        "experiment_dir",
        help="Path to the experiment folder, e.g. /media/central/raw_mirror/MeadowFescue_2026",
    )
    parser.add_argument(
        "--filename",
        default="results.csv",
        help="CSV filename to collect. Default: results.csv",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output combined CSV. Default: <experiment_dir>/combined_results.csv",
    )
    parser.add_argument(
        "--summary-output",
        default=None,
        help="Output file-level summary CSV. Default: <experiment_dir>/combined_results_file_summary.csv",
    )

    args = parser.parse_args()

    experiment_dir = Path(args.experiment_dir).expanduser().resolve()

    if not experiment_dir.exists():
        print(f"ERROR: experiment folder does not exist: {experiment_dir}", file=sys.stderr)
        return 1

    if not experiment_dir.is_dir():
        print(f"ERROR: not a folder: {experiment_dir}", file=sys.stderr)
        return 1

    output_csv = (
        Path(args.output).expanduser().resolve()
        if args.output
        else experiment_dir / "combined_results.csv"
    )

    summary_csv = (
        Path(args.summary_output).expanduser().resolve()
        if args.summary_output
        else experiment_dir / "combined_results_file_summary.csv"
    )

    files = find_results_files(experiment_dir, args.filename)

    if not files:
        print(
            f"ERROR: no {args.filename} files found under {experiment_dir}",
            file=sys.stderr,
        )
        return 1

    row_counts = inspect_csv_files(files)
    total_rows = combine_csv_files(files, output_csv)
    write_file_summary(summary_csv, row_counts)

    print(f"Found {len(files)} CSV file(s).")
    print(f"Wrote {total_rows} combined row(s).")
    print(f"Combined CSV: {output_csv}")
    print(f"File summary: {summary_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
