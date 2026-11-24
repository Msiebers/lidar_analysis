#!/usr/bin/env python3
"""Generate an experiment plot_key.csv from a breeder field list and plot_id.yaml.

Run:
    python3 plotkey.py /path/to/raw_mirror/MeadowFescue_2026
    python3 plotkey.py /path/to/raw_mirror/MeadowFescue_2026 --config /path/to/plot_id.yaml

The breeder input and LiDAR results.csv files are read-only. Only plot_key.csv is
created or replaced beside plot_id.yaml. Requires PyYAML; .xlsx additionally
requires openpyxl.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


KEY_COLUMNS = (
    "target_id",
    "lidar_id",
    "breeder_id",
    "breeder_row",
    "breeder_range",
    "lidar_row",
    "lidar_position",
    "target_type",
)
TARGET_ID_PATTERN = re.compile(r"^(\d+)_(plant|plot)_(\d+)$", re.IGNORECASE)


class PlotKeyError(Exception):
    """An input or mapping problem that a user can fix."""


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise PlotKeyError(
            "PyYAML is missing. On Ubuntu, install it with: sudo apt install python3-yaml"
        ) from exc
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            loaded = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise PlotKeyError(f"Cannot read YAML {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PlotKeyError(f"The YAML must contain a mapping of settings: {path}")
    return loaded


def require_text(mapping: dict[str, Any], key: str, source: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlotKeyError(f"Missing or empty '{key}' in {source}")
    return value.strip()


def integer(value: Any, source: str) -> int:
    if value is None or str(value).strip() == "":
        raise PlotKeyError(f"Missing integer for {source}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PlotKeyError(f"Invalid integer {value!r} for {source}") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise PlotKeyError(f"Expected a whole number for {source}, got {value!r}")
    return int(number)


def direction_sign(value: Any, source: str) -> int:
    if value is None:
        return 1
    if not isinstance(value, str) or value.strip().casefold() not in (
        "increasing",
        "decreasing",
    ):
        raise PlotKeyError(f"{source} must be 'increasing' or 'decreasing'")
    return 1 if value.strip().casefold() == "increasing" else -1


def resolve_header(headers: list[str], requested: str, path: Path) -> str:
    matches = [name for name in headers if name.strip().casefold() == requested.casefold()]
    if len(matches) != 1:
        raise PlotKeyError(
            f"Column {requested!r} in {path}: found {len(matches)} matches. "
            f"Available headers: {', '.join(headers)}"
        )
    return matches[0]


def csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(handle, dialect=dialect)
            headers = reader.fieldnames
            if not headers:
                raise PlotKeyError(f"No column headers found in {path}")
            if any(not name for name in headers):
                raise PlotKeyError(f"Empty column header in {path}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise PlotKeyError(f"Cannot read CSV {path}: {exc}") from exc
    return headers, rows


def excel_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise PlotKeyError(
            "Reading Excel requires openpyxl. On Ubuntu: sudo apt install python3-openpyxl"
        ) from exc
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook.active
            values = worksheet.iter_rows(values_only=True)
            header_cells = next(values, None)
            if header_cells is None:
                raise PlotKeyError(f"Excel file is empty: {path}")
            headers = [str(cell).strip() if cell is not None else "" for cell in header_cells]
            if any(not name for name in headers):
                raise PlotKeyError(f"Blank column header in first row of {path}")
            rows = [
                dict(zip(headers, cells))
                for cells in values
                if any(cell is not None and str(cell).strip() for cell in cells)
            ]
        finally:
            workbook.close()
    except OSError as exc:
        raise PlotKeyError(f"Cannot read Excel {path}: {exc}") from exc
    return headers, rows


def breeder_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    extension = path.suffix.lower()
    if extension in (".csv", ".tsv"):
        return csv_rows(path)
    if extension == ".xlsx":
        return excel_rows(path)
    raise PlotKeyError(
        f"Unsupported breeder file extension {extension!r}. Use CSV, TSV, or XLSX."
    )


def find_config(experiment: Path, supplied: Path | None) -> Path:
    if supplied is not None:
        config = supplied.expanduser().resolve()
        if not config.is_file():
            raise PlotKeyError(f"YAML file not found: {config}")
        return config
    candidates = (
        experiment / "plot_id.yaml",
        experiment / "results" / "plot_id.yaml",
        experiment / "metadata" / "plot_id.yaml",
    )
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        raise PlotKeyError(
            f"No plot_id.yaml found in {experiment}, results/, or metadata/. "
            "Use --config PATH if it is stored elsewhere."
        )
    if len(existing) > 1:
        raise PlotKeyError(
            "Multiple plot_id.yaml files found; specify the intended one using --config: "
            + ", ".join(str(p) for p in existing)
        )
    return existing[0]


def resolve_breeder_file(config_path: Path, filename: str) -> Path:
    candidate = (config_path.parent / filename).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    # The YAML is often typed with lower-case names while the original is upper-case.
    if not candidate.parent.is_dir():
        raise PlotKeyError(f"Breeder input directory does not exist: {candidate.parent}")
    alternatives = [
        p for p in candidate.parent.iterdir()
        if p.is_file() and p.name.casefold() == candidate.name.casefold()
    ]
    if len(alternatives) == 1:
        print(f"Note: Using {alternatives[0].name} (case differs from YAML).")
        return alternatives[0].resolve()
    raise PlotKeyError(
        f"Breeder source_file {filename!r} was not found beside {config_path.name} "
        f"({candidate.parent})."
    )


def discover_result_files(experiment: Path, max_depth: int = 5) -> list[Path]:
    files: list[Path] = []
    root_depth = len(experiment.parts)
    for folder, subdirs, filenames in os.walk(experiment):
        path = Path(folder)
        depth = len(path.parts) - root_depth
        subdirs[:] = sorted(
            d for d in subdirs if not d.startswith(".") and d not in ("__pycache__",)
        ) if depth < max_depth else []
        if "results.csv" in filenames:
            files.append(path / "results.csv")
    return sorted(files)


@dataclass
class ResultsCheck:
    path: Path
    target_type: str | None
    target_ids: set[str]
    duplicate_count: int
    side_counts: Counter[str]


def inspect_results(path: Path) -> ResultsCheck:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"target_id", "target_type"}.issubset(reader.fieldnames):
                raise PlotKeyError(
                    f"Expected target_id and target_type columns in LiDAR file {path}"
                )
            kinds: set[str] = set()
            seen: set[str] = set()
            duplicates = 0
            sides: Counter[str] = Counter()
            for n, row in enumerate(reader, start=2):
                target_id = (row.get("target_id") or "").strip()
                raw_type = (row.get("target_type") or "").strip().lower()
                if not target_id:
                    raise PlotKeyError(f"Blank target_id at {path}:{n}")
                parsed = TARGET_ID_PATTERN.fullmatch(target_id)
                if not parsed:
                    raise PlotKeyError(
                        f"Unrecognized target_id {target_id!r} at {path}:{n}; "
                        "expected e.g. 1_plant_1 or 1_plot_1"
                    )
                embedded_type = parsed.group(2).lower()
                if raw_type not in ("plant", "plot") or raw_type != embedded_type:
                    raise PlotKeyError(
                        f"Mismatch between target_type={raw_type!r} and "
                        f"target_id={target_id!r} at {path}:{n}"
                    )
                kinds.add(raw_type)
                if target_id in seen:
                    duplicates += 1
                seen.add(target_id)
                sides[(row.get("side") or "unknown").strip().lower()] += 1
    except (OSError, UnicodeError, csv.Error) as exc:
        raise PlotKeyError(f"Cannot read results file {path}: {exc}") from exc
    if len(kinds) > 1:
        raise PlotKeyError(
            f"Mixed plant and plot target types in {path}; do not guess the mapping."
        )
    return ResultsCheck(path, next(iter(kinds)) if kinds else None, seen, duplicates, sides)


def generate_key(
    breeder_path: Path, config: dict[str, Any], target_type: str
) -> list[dict[str, Any]]:
    row_config = config.get("row")
    range_config = config.get("range")
    if not isinstance(row_config, dict) or not isinstance(range_config, dict):
        raise PlotKeyError("plot_id.yaml must contain 'row:' and 'range:' sections")

    id_requested = require_text(config, "id_column", "plot_id.yaml")
    row_requested = require_text(row_config, "breeder_row", "row section")
    range_requested = require_text(range_config, "breeder_range", "range section")
    row_anchor = integer(row_config.get("breeder_start_row"), "row.breeder_start_row")
    range_anchor = integer(
        range_config.get("breeder_plant_plot_start"),
        "range.breeder_plant_plot_start",
    )
    row_sign = direction_sign(row_config.get("direction"), "row.direction")
    range_sign = direction_sign(range_config.get("direction"), "range.direction")

    headers, records = breeder_rows(breeder_path)
    id_column = resolve_header(headers, id_requested, breeder_path)
    row_column = resolve_header(headers, row_requested, breeder_path)
    range_column = resolve_header(headers, range_requested, breeder_path)
    if len({id_column, row_column, range_column}) != 3:
        raise PlotKeyError("ID, breeder row, and breeder range must be different columns")
    if not records:
        raise PlotKeyError(f"No breeder observations found in {breeder_path}")

    key: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_targets: set[str] = set()
    for line, record in enumerate(records, start=2):
        identifier = str(record.get(id_column) or "").strip()
        if not identifier or identifier.casefold() in ("na", "n/a", "nan"):
            raise PlotKeyError(f"Missing plant/plot ID in breeder file row {line}")
        breeder_row = integer(record.get(row_column), f"breeder row {line} / {row_column}")
        breeder_range = integer(record.get(range_column), f"breeder row {line} / {range_column}")
        lidar_row = 1 + row_sign * (breeder_row - row_anchor)
        lidar_position = 1 + range_sign * (breeder_range - range_anchor)
        if lidar_row < 1 or lidar_position < 1:
            raise PlotKeyError(
                f"Breeder ID {identifier} maps to LiDAR {lidar_row}-{lidar_position}. "
                "Check your starting values and increasing/decreasing directions."
            )
        target_id = f"{lidar_row}_{target_type}_{lidar_position}"
        if identifier in used_ids:
            raise PlotKeyError(
                f"Duplicate breeder ID {identifier!r} at row {line}. "
                "id_column must identify unique field positions, not repeated genotypes."
            )
        if target_id in used_targets:
            raise PlotKeyError(
                f"More than one breeder entry maps to {target_id}; check rows/columns."
            )
        used_ids.add(identifier)
        used_targets.add(target_id)
        key.append(
            {
                "target_id": target_id,
                "lidar_id": f"{lidar_row}-{lidar_position}",
                "breeder_id": identifier,
                "breeder_row": breeder_row,
                "breeder_range": breeder_range,
                "lidar_row": lidar_row,
                "lidar_position": lidar_position,
                "target_type": target_type,
            }
        )
    key.sort(key=lambda item: (item["lidar_row"], item["lidar_position"]))
    return key


def atomic_write_csv(output: Path, rows: Iterable[dict[str, Any]]) -> None:
    # A temporary file and atomic rename prevent half-written keys.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=output.parent,
            prefix=".plot_key_", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=KEY_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(output)
    except OSError as exc:
        raise PlotKeyError(f"Cannot write {output}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate plot_key.csv from plot_id.yaml and a breeder field list."
    )
    parser.add_argument(
        "experiment", type=Path,
        help="Path to one experiment folder in raw_mirror (not raw_mirror itself)",
    )
    parser.add_argument(
        "--config", type=Path,
        help="Explicit plot_id.yaml location (default: experiment/, results/, or metadata/)",
    )
    parser.add_argument(
        "--results", type=Path,
        help="Read only this results.csv to infer plant or plot (otherwise find all dates)",
    )
    args = parser.parse_args()
    try:
        experiment = args.experiment.expanduser().resolve()
        if not experiment.is_dir():
            raise PlotKeyError(f"Experiment folder not found: {experiment}")
        config_path = find_config(experiment, args.config)
        config = read_yaml(config_path)
        breeder_name = require_text(config, "source_file", "plot_id.yaml")
        breeder_path = resolve_breeder_file(config_path, breeder_name)
        output_path = config_path.parent / "plot_key.csv"
        if breeder_path == output_path:
            raise PlotKeyError("source_file cannot point to plot_key.csv")

        if args.results is not None:
            result_files = [args.results.expanduser().resolve()]
            if not result_files[0].is_file():
                raise PlotKeyError(f"Results file not found: {result_files[0]}")
        else:
            result_files = discover_result_files(experiment)
        if not result_files:
            raise PlotKeyError(
                "No LiDAR results.csv found in this experiment. "
                "Process a date first or provide --results PATH."
            )
        checks = [inspect_results(path) for path in result_files]
        types = {c.target_type for c in checks if c.target_type is not None}
        if len(types) != 1:
            raise PlotKeyError(
                "Cannot infer one target type for the experiment. "
                f"Found: {', '.join(sorted(types)) or 'none'}. "
                "Specify a single plant-only or plot-only results.csv with --results."
            )
        target_type = types.pop()
        key = generate_key(breeder_path, config, target_type)
        valid_ids = {row["target_id"] for row in key}
        print(f"Experiment: {experiment}")
        print(f"Mapping: {config_path}")
        print(f"Breeder file: {breeder_path}")
        print(f"LiDAR target type (from results.csv): {target_type}")
        print(f"Breeder positions in key: {len(key)}")
        print("\nResults checks:")
        for result in checks:
            matched = len(result.target_ids & valid_ids)
            unmatched = len(result.target_ids - valid_ids)
            missing = len(valid_ids - result.target_ids)
            side_breakdown = ", ".join(
                f"{side}={count}" for side, count in sorted(result.side_counts.items())
            )
            print(f"  {result.path.relative_to(experiment) if result.path.is_relative_to(experiment) else result.path}")
            print(
                f"    matched={matched}, outside_map={unmatched}, "
                f"mapped_but_not_measured={missing}, "
                f"duplicate_result_ids={result.duplicate_count}; {side_breakdown}"
            )
        print("\nSample mappings:")
        sample = {row["target_id"]: row for row in key[:4] + key[-2:]}
        for row in sample.values():
            print(f"  {row['target_id']:<14} -> {row['breeder_id']}")
        atomic_write_csv(output_path, key)
        print(f"\nSaved: {output_path} ({len(key)} positions)")
        print("Original breeder and LiDAR result files were not modified.")
        return 0
    except PlotKeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
