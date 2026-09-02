from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from lidar_analysis.research_delivery_plots import generate_delivery_graphs


CANONICAL_RANKING_METRICS = (
    "points",
    "point_density_m2",
    "stand_topo_per_m",
)
DATE_PATTERN = re.compile(r"^\d{4}_\d{2}_\d{2}$")
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
FAILED_QC_VALUES = {"0", "false", "fail", "failed", "error", "invalid", "no"}
PASSED_QC_VALUES = {"1", "true", "pass", "passed", "ok", "valid", "yes"}


@dataclass(frozen=True)
class DeliveryConfig:
    experiment: str
    raw_experiment_root: Path
    analysis_experiment_root: Path
    delivery_root: Path
    metrics: tuple[str, ...] = CANONICAL_RANKING_METRICS
    top_fraction: float = 0.15
    include_ties: bool = True
    outlier_iqr_multiplier: float = 1.5
    generate_graphs: bool = True
    graph_dpi: int = 160

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> "DeliveryConfig":
        required = (
            "experiment",
            "raw_experiment_root",
            "analysis_experiment_root",
            "delivery_root",
        )
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            raise ValueError(f"Missing required delivery config key(s): {', '.join(missing)}")

        raw_metrics = data.get("metrics", CANONICAL_RANKING_METRICS)
        if not isinstance(raw_metrics, (list, tuple)) or not raw_metrics:
            raise ValueError("metrics must be a non-empty list")

        raw_generate_graphs = data.get("generate_graphs", True)
        if not isinstance(raw_generate_graphs, bool):
            raise ValueError("generate_graphs must be true or false")
        raw_graph_dpi = data.get("graph_dpi", 160)
        if isinstance(raw_graph_dpi, bool) or not isinstance(raw_graph_dpi, int):
            raise ValueError("graph_dpi must be an integer from 72 through 600")

        config = cls(
            experiment=str(data["experiment"]).strip(),
            raw_experiment_root=Path(str(data["raw_experiment_root"])).expanduser(),
            analysis_experiment_root=Path(str(data["analysis_experiment_root"])).expanduser(),
            delivery_root=Path(str(data["delivery_root"])).expanduser(),
            metrics=tuple(str(metric).strip() for metric in raw_metrics),
            top_fraction=float(data.get("top_fraction", 0.15)),
            include_ties=bool(data.get("include_ties", True)),
            outlier_iqr_multiplier=float(data.get("outlier_iqr_multiplier", 1.5)),
            generate_graphs=raw_generate_graphs,
            graph_dpi=raw_graph_dpi,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not SAFE_NAME_PATTERN.fullmatch(self.experiment):
            raise ValueError("experiment may contain only letters, numbers, '.', '_', and '-'")
        if not 0.0 < self.top_fraction <= 1.0:
            raise ValueError("top_fraction must be greater than 0 and no greater than 1")
        if self.outlier_iqr_multiplier <= 0:
            raise ValueError("outlier_iqr_multiplier must be greater than 0")
        if not isinstance(self.generate_graphs, bool):
            raise ValueError("generate_graphs must be true or false")
        if (
            isinstance(self.graph_dpi, bool)
            or not isinstance(self.graph_dpi, int)
            or not 72 <= self.graph_dpi <= 600
        ):
            raise ValueError("graph_dpi must be an integer from 72 through 600")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must not contain duplicates")

        unsupported = sorted(set(self.metrics) - set(CANONICAL_RANKING_METRICS))
        if unsupported:
            allowed = ", ".join(CANONICAL_RANKING_METRICS)
            raise ValueError(
                f"Unvalidated ranking metric(s): {', '.join(unsupported)}. "
                f"This test builder currently permits only: {allowed}"
            )

        raw_root = self.raw_experiment_root.resolve()
        analysis_root = self.analysis_experiment_root.resolve()
        delivery_root = self.delivery_root.resolve()
        if not raw_root.is_dir():
            raise FileNotFoundError(f"Raw experiment root does not exist: {raw_root}")
        if not analysis_root.is_dir():
            raise FileNotFoundError(f"Analysis experiment root does not exist: {analysis_root}")
        if paths_overlap(delivery_root, raw_root) or paths_overlap(delivery_root, analysis_root):
            raise ValueError(
                "delivery_root must not equal, contain, or be contained by either input root"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "experiment": self.experiment,
            "raw_experiment_root": str(self.raw_experiment_root.resolve()),
            "analysis_experiment_root": str(self.analysis_experiment_root.resolve()),
            "delivery_root": str(self.delivery_root.resolve()),
            "metrics": list(self.metrics),
            "top_fraction": self.top_fraction,
            "include_ties": self.include_ties,
            "outlier_iqr_multiplier": self.outlier_iqr_multiplier,
            "generate_graphs": self.generate_graphs,
            "graph_dpi": self.graph_dpi,
            "test_preview": True,
        }


@dataclass
class DateInspection:
    date: str
    raw_date_dir: Path | None
    source_dir: Path | None
    analysis_date_dir: Path | None
    results_path: Path | None
    pointcloud_dir: Path | None
    rows: list[dict[str, str]] = field(default_factory=list)
    fieldnames: list[str] = field(default_factory=list)
    status: str = "incomplete"
    reason: str = ""
    qc_flags: list[dict[str, str]] = field(default_factory=list)
    lidar_files: int = 0
    pico_files: int = 0
    scan_pairs: int = 0
    processed_scan_ids: int = 0
    pointcloud_csv_files: int = 0
    main_pointcloud_csv_files: int = 0
    topology_pointcloud_csv_files: int = 0
    marker_reference_csv_files: int = 0
    analysis_config_path: Path | None = None
    analysis_config_sha256: str = ""


@dataclass(frozen=True)
class BuildResult:
    target_dir: Path
    dates: tuple[DateInspection, ...]
    latest_usable_date: str | None
    config_sha256: str
    wrote_files: bool


def load_delivery_config(path: Path) -> DeliveryConfig:
    with path.expanduser().open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Delivery config must contain a YAML mapping")
    return DeliveryConfig.from_mapping(data)


def paths_overlap(first: Path, second: Path) -> bool:
    first = first.resolve()
    second = second.resolve()
    return first == second or first in second.parents or second in first.parents


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_config_sha256(config: DeliveryConfig) -> str:
    payload = json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _date_directories(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        child.name: child
        for child in root.iterdir()
        if child.is_dir() and DATE_PATTERN.fullmatch(child.name)
    }


def _unique_existing_paths(candidates: Iterable[Path], *, directories: bool = False) -> list[Path]:
    unique: dict[Path, Path] = {}
    for candidate in candidates:
        exists = candidate.is_dir() if directories else candidate.is_file()
        if not exists:
            continue
        resolved = candidate.resolve()
        unique.setdefault(resolved, candidate)
    return list(unique.values())


def _resolve_results_path(analysis_date_dir: Path | None) -> tuple[Path | None, str]:
    if analysis_date_dir is None:
        return None, "No analysis directory exists for this date."
    paths = _unique_existing_paths(
        (
            analysis_date_dir / "output" / "results.csv",
            analysis_date_dir / "results.csv",
        )
    )
    if not paths:
        return None, "No canonical results.csv exists for this date."
    if len(paths) > 1:
        rendered = ", ".join(str(path) for path in paths)
        return None, f"Multiple different canonical results.csv files were found: {rendered}"
    return paths[0], ""


def _resolve_pointcloud_dir(analysis_date_dir: Path | None) -> tuple[Path | None, str]:
    if analysis_date_dir is None:
        return None, ""
    paths = _unique_existing_paths(
        (
            analysis_date_dir / "output" / "pointclouds",
            analysis_date_dir / "pointclouds",
        ),
        directories=True,
    )
    if not paths:
        return None, "No canonical pointclouds directory exists for this date."
    if len(paths) > 1:
        rendered = ", ".join(str(path) for path in paths)
        return None, f"Multiple different pointcloud directories were found: {rendered}"
    return paths[0], ""


def _resolve_analysis_config(
    raw_date_dir: Path | None,
    source_dir: Path | None,
    analysis_date_dir: Path | None,
    results_path: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if results_path is not None:
        candidates.append(results_path.parent / "experiment_config.snapshot.yaml")
    if analysis_date_dir is not None:
        candidates.extend(
            (
                analysis_date_dir / "output" / "experiment_config.snapshot.yaml",
                analysis_date_dir / "experiment_config.snapshot.yaml",
            )
        )
    if source_dir is not None:
        candidates.append(source_dir / "experiment_config.yaml")
    if raw_date_dir is not None:
        candidates.append(raw_date_dir / "experiment_config.yaml")
    paths = _unique_existing_paths(candidates)
    return paths[0] if paths else None


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        return list(reader), list(reader.fieldnames)


def _scan_bases(source_dir: Path | None, suffix: str) -> set[str]:
    if source_dir is None or not source_dir.is_dir():
        return set()
    return {
        path.name[: -len(suffix)]
        for path in source_dir.rglob(f"*{suffix}")
        if path.is_file()
    }


def _add_flag(inspection: DateInspection, severity: str, category: str, message: str) -> None:
    inspection.qc_flags.append(
        {"severity": severity, "category": category, "message": message}
    )


def _row_passes_qc(row: dict[str, str]) -> bool:
    for column in ("qc_pass", "qc_status"):
        value = str(row.get(column, "")).strip().lower()
        if not value:
            continue
        if value in FAILED_QC_VALUES:
            return False
        if value in PASSED_QC_VALUES:
            return True
    return True


def as_finite_float(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def finite_qc_values(rows: list[dict[str, str]], metric: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        if not _row_passes_qc(row):
            continue
        value = as_finite_float(row.get(metric))
        if value is not None:
            values.append(value)
    return values


def ranking_directory_name(fraction: float) -> str:
    percent = fraction * 100.0
    rendered = f"{percent:.6f}".rstrip("0").rstrip(".").replace(".", "_")
    return f"top_{rendered}_percent"


def inspect_experiment(config: DeliveryConfig) -> list[DateInspection]:
    config.validate()
    raw_dates = _date_directories(config.raw_experiment_root.resolve())
    analysis_dates = _date_directories(config.analysis_experiment_root.resolve())
    date_names = sorted(set(raw_dates) | set(analysis_dates))
    inspections: list[DateInspection] = []

    for date_name in date_names:
        raw_date_dir = raw_dates.get(date_name)
        source_dir = None
        if raw_date_dir is not None:
            source_candidate = raw_date_dir / "source"
            source_dir = source_candidate if source_candidate.is_dir() else raw_date_dir
        analysis_date_dir = analysis_dates.get(date_name)
        results_path, results_problem = _resolve_results_path(analysis_date_dir)
        pointcloud_dir, pointcloud_problem = _resolve_pointcloud_dir(analysis_date_dir)
        inspection = DateInspection(
            date=date_name,
            raw_date_dir=raw_date_dir,
            source_dir=source_dir,
            analysis_date_dir=analysis_date_dir,
            results_path=results_path,
            pointcloud_dir=pointcloud_dir,
        )

        lidar_bases = _scan_bases(source_dir, "_lidar.csv")
        pico_bases = _scan_bases(source_dir, "_pico.csv")
        inspection.lidar_files = len(lidar_bases)
        inspection.pico_files = len(pico_bases)
        inspection.scan_pairs = len(lidar_bases & pico_bases)

        if raw_date_dir is None:
            _add_flag(inspection, "warning", "input", "No raw/source directory exists for this date.")
        if inspection.lidar_files != inspection.pico_files:
            _add_flag(
                inspection,
                "warning",
                "input",
                f"LiDAR/Pico file counts differ: {inspection.lidar_files} vs {inspection.pico_files}.",
            )

        if pointcloud_dir is not None:
            pointcloud_files = [path for path in pointcloud_dir.rglob("*.csv") if path.is_file()]
            inspection.pointcloud_csv_files = len(pointcloud_files)
            inspection.topology_pointcloud_csv_files = sum(
                path.name.startswith("topology_count_") for path in pointcloud_files
            )
            inspection.marker_reference_csv_files = sum(
                "marker_reference_points" in path.name for path in pointcloud_files
            )
            inspection.main_pointcloud_csv_files = sum(
                not path.name.startswith("topology_count_")
                and "marker_reference_points" not in path.name
                for path in pointcloud_files
            )
        elif pointcloud_problem:
            _add_flag(inspection, "warning", "output", pointcloud_problem)

        if results_path is None:
            inspection.reason = results_problem
            _add_flag(inspection, "error", "output", results_problem)
        else:
            try:
                inspection.rows, inspection.fieldnames = _read_csv(results_path)
            except (OSError, ValueError, csv.Error) as exc:
                inspection.reason = f"Canonical results.csv could not be read: {exc}"
                _add_flag(inspection, "error", "output", inspection.reason)
            else:
                if not inspection.rows:
                    inspection.reason = "Canonical results.csv has no data rows."
                    _add_flag(inspection, "error", "output", inspection.reason)
                else:
                    inspection.status = "usable"
                    inspection.reason = "Canonical results.csv is available."

        if inspection.rows and "scan_id" in inspection.fieldnames:
            inspection.processed_scan_ids = len(
                {
                    str(row.get("scan_id", "")).strip()
                    for row in inspection.rows
                    if str(row.get("scan_id", "")).strip()
                }
            )
            if inspection.scan_pairs and inspection.processed_scan_ids < inspection.scan_pairs:
                _add_flag(
                    inspection,
                    "warning",
                    "coverage",
                    f"Only {inspection.processed_scan_ids} distinct processed scan IDs were found "
                    f"for {inspection.scan_pairs} matched source pairs.",
                )

        identity_fields = [
            field_name
            for field_name in ("experiment", "date", "row", "plot")
            if field_name in inspection.fieldnames
        ]
        if inspection.rows and identity_fields:
            identities = [
                tuple(str(row.get(field_name, "")).strip() for field_name in identity_fields)
                for row in inspection.rows
            ]
            duplicate_rows = sum(
                count - 1 for count in Counter(identities).values() if count > 1
            )
            if duplicate_rows:
                _add_flag(
                    inspection,
                    "warning",
                    "results",
                    f"{duplicate_rows} duplicate result row(s) were found using "
                    f"identity fields: {', '.join(identity_fields)}.",
                )

        zero_point_rows = sum(
            1 for row in inspection.rows if as_finite_float(row.get("points")) == 0.0
        )
        if zero_point_rows:
            _add_flag(
                inspection,
                "warning",
                "results",
                f"{zero_point_rows} result row(s) have zero points.",
            )

        for metric in config.metrics:
            if metric not in inspection.fieldnames:
                _add_flag(
                    inspection,
                    "warning",
                    "ranking",
                    f"Metric {metric!r} is unavailable; its ranking will be skipped.",
                )
                continue
            values = [
                as_finite_float(row.get(metric))
                for row in inspection.rows
                if _row_passes_qc(row)
            ]
            if not any(value is not None for value in values):
                _add_flag(
                    inspection,
                    "warning",
                    "ranking",
                    f"Metric {metric!r} has no finite, QC-eligible values; its ranking will be skipped.",
                )

        inspection.analysis_config_path = _resolve_analysis_config(
            raw_date_dir, source_dir, analysis_date_dir, results_path
        )
        if inspection.analysis_config_path is not None:
            inspection.analysis_config_sha256 = sha256_file(inspection.analysis_config_path)
        else:
            _add_flag(
                inspection,
                "info",
                "configuration",
                "No analysis config or config snapshot was found; historical algorithm consistency is unknown.",
            )

        inspections.append(inspection)

    return inspections


def select_top_rows(
    rows: list[dict[str, str]],
    metric: str,
    fraction: float,
    include_ties: bool,
) -> list[dict[str, object]]:
    eligible: list[tuple[int, float, dict[str, str]]] = []
    for index, row in enumerate(rows):
        if not _row_passes_qc(row):
            continue
        value = as_finite_float(row.get(metric))
        if value is not None:
            eligible.append((index, value, row))
    if not eligible:
        return []

    eligible.sort(key=lambda item: (-item[1], item[0]))
    requested_count = max(1, math.ceil(len(eligible) * fraction))
    cutoff = eligible[requested_count - 1][1]
    selected = (
        [item for item in eligible if item[1] >= cutoff]
        if include_ties
        else eligible[:requested_count]
    )

    output: list[dict[str, object]] = []
    for rank, (_index, value, row) in enumerate(selected, start=1):
        output.append(
            {
                **row,
                "_ranking_metric": metric,
                "_ranking_rank": rank,
                "_ranking_value": value,
                "_ranking_cutoff": cutoff,
                "_ranking_eligible_rows": len(eligible),
                "_ranking_selected_rows": len(selected),
            }
        )
    return output


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def find_outliers(
    rows: list[dict[str, str]], metric: str, multiplier: float
) -> list[dict[str, object]]:
    eligible: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        if not _row_passes_qc(row):
            continue
        value = as_finite_float(row.get(metric))
        if value is not None:
            eligible.append((value, row))
    if len(eligible) < 4:
        return []

    sorted_values = sorted(value for value, _row in eligible)
    q1 = _quantile(sorted_values, 0.25)
    q3 = _quantile(sorted_values, 0.75)
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    output: list[dict[str, object]] = []
    for value, row in eligible:
        if value < lower or value > upper:
            output.append(
                {
                    **row,
                    "_outlier_metric": metric,
                    "_outlier_direction": "low" if value < lower else "high",
                    "_outlier_value": value,
                    "_outlier_lower_bound": lower,
                    "_outlier_upper_bound": upper,
                    "_outlier_method": f"IQR x {multiplier:g}",
                }
            )
    return output


def _field_union(rows: Iterable[dict[str, object]], preferred: Iterable[str] = ()) -> list[str]:
    fields: list[str] = []
    for field_name in preferred:
        if field_name not in fields:
            fields.append(field_name)
    for row in rows:
        for field_name in row:
            if field_name not in fields:
                fields.append(field_name)
    return fields


def _write_csv(
    path: Path,
    rows: list[dict[str, object]],
    *,
    fieldnames: Iterable[str] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = _field_union(rows, fieldnames)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _date_index_row(inspection: DateInspection) -> dict[str, object]:
    return {
        "date": inspection.date,
        "status": inspection.status,
        "reason": inspection.reason,
        "raw_date_dir": str(inspection.raw_date_dir or ""),
        "source_dir": str(inspection.source_dir or ""),
        "analysis_date_dir": str(inspection.analysis_date_dir or ""),
        "results_path": str(inspection.results_path or ""),
        "results_rows": len(inspection.rows),
        "lidar_files": inspection.lidar_files,
        "pico_files": inspection.pico_files,
        "scan_pairs": inspection.scan_pairs,
        "processed_scan_ids": inspection.processed_scan_ids,
        "pointcloud_csv_files": inspection.pointcloud_csv_files,
        "main_pointcloud_csv_files": inspection.main_pointcloud_csv_files,
        "topology_pointcloud_csv_files": inspection.topology_pointcloud_csv_files,
        "marker_reference_csv_files": inspection.marker_reference_csv_files,
        "analysis_config_path": str(inspection.analysis_config_path or ""),
        "analysis_config_sha256": inspection.analysis_config_sha256,
        "qc_issue_count": len(inspection.qc_flags),
    }


def _write_date_output(
    root: Path,
    inspection: DateInspection,
    config: DeliveryConfig,
) -> dict[str, list[dict[str, object]]]:
    date_root = root / inspection.date
    source_dir = date_root / "source"
    metadata_dir = date_root / "metadata"
    pointclouds_dir = date_root / "pointclouds"
    results_dir = date_root / "results"
    for directory in (source_dir, metadata_dir, pointclouds_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source_note = (
        "# Test preview source reference\n\n"
        "Source scans were not copied or modified.\n\n"
        f"Read-only source: `{inspection.source_dir or 'unavailable'}`\n"
    )
    (source_dir / "README.md").write_text(source_note, encoding="utf-8")

    pointcloud_note = (
        "# Test preview point-cloud reference\n\n"
        "Point-cloud files were not copied or modified.\n\n"
        f"Read-only point-cloud directory: `{inspection.pointcloud_dir or 'unavailable'}`\n"
    )
    (pointclouds_dir / "README.md").write_text(pointcloud_note, encoding="utf-8")

    _write_csv(
        pointclouds_dir / "pointcloud_inventory.csv",
        [
            {
                "pointcloud_dir": str(inspection.pointcloud_dir or ""),
                "all_csv_files": inspection.pointcloud_csv_files,
                "main_pointcloud_csv_files": inspection.main_pointcloud_csv_files,
                "topology_pointcloud_csv_files": inspection.topology_pointcloud_csv_files,
                "marker_reference_csv_files": inspection.marker_reference_csv_files,
            }
        ],
    )
    (metadata_dir / "date_status.json").write_text(
        json.dumps(_date_index_row(inspection), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        results_dir / "qc" / "qc_flags.csv",
        [dict(row) for row in inspection.qc_flags],
        fieldnames=("severity", "category", "message"),
    )

    rankings: dict[str, list[dict[str, object]]] = {}
    all_outliers: list[dict[str, object]] = []
    if inspection.status == "usable":
        _write_csv(
            results_dir / "results.csv",
            [dict(row) for row in inspection.rows],
            fieldnames=inspection.fieldnames,
        )
        for metric in config.metrics:
            selected = select_top_rows(
                inspection.rows, metric, config.top_fraction, config.include_ties
            )
            rankings[metric] = selected
            if selected:
                _write_csv(
                    results_dir / ranking_directory_name(config.top_fraction) / f"{metric}.csv",
                    selected,
                )
            all_outliers.extend(
                find_outliers(inspection.rows, metric, config.outlier_iqr_multiplier)
            )

    _write_csv(
        results_dir / "outliers" / "outliers.csv",
        all_outliers,
        fieldnames=(
            "_outlier_metric",
            "_outlier_direction",
            "_outlier_value",
            "_outlier_lower_bound",
            "_outlier_upper_bound",
            "_outlier_method",
        ),
    )
    return rankings


def _write_experiment_summary(
    path: Path,
    config: DeliveryConfig,
    inspections: list[DateInspection],
    latest_usable_date: str | None,
    config_sha256: str,
) -> None:
    usable = [inspection.date for inspection in inspections if inspection.status == "usable"]
    incomplete = [inspection.date for inspection in inspections if inspection.status != "usable"]
    analysis_hashes = {
        inspection.analysis_config_sha256
        for inspection in inspections
        if inspection.analysis_config_sha256
    }
    missing_config_dates = [
        inspection.date for inspection in inspections if not inspection.analysis_config_sha256
    ]
    if not analysis_hashes:
        historical_config_status = "unknown (no config snapshots were found)"
    elif len(analysis_hashes) > 1:
        historical_config_status = "inconsistent (multiple config fingerprints were found)"
    elif missing_config_dates:
        historical_config_status = "partially known (one fingerprint plus missing dates)"
    else:
        historical_config_status = "consistent across discovered dates"

    lines = [
        f"# TEST PREVIEW: {config.experiment} Research Delivery",
        "",
        "This folder is an internal, rebuildable preview. It is not an official researcher delivery.",
        "Raw scans, collected point clouds, and existing analysis results were read only and were not modified.",
        "",
        "## Date Status",
        "",
        f"- Usable canonical result dates: {', '.join(usable) if usable else 'none'}",
        f"- Incomplete/unusable dates: {', '.join(incomplete) if incomplete else 'none'}",
        f"- Latest usable date used for summary rankings: {latest_usable_date or 'none'}",
        "",
        "## Rankings",
        "",
        f"- Metrics: {', '.join(config.metrics)}",
        f"- Top fraction: {config.top_fraction:.2%}",
        f"- Include ties at cutoff: {config.include_ties}",
        "- Rankings are calculated independently for each metric and date.",
        "- Rows with explicit failed `qc_pass` or `qc_status` values are excluded.",
        "- When row-level QC columns are absent, finite numeric values are eligible; this does not imply scientific QC approval.",
        "- Preliminary/confounded geometry metrics are not permitted by this builder.",
        "",
        "## Graphs",
        "",
        f"- Graph generation enabled: {config.generate_graphs}",
        f"- Graph resolution: {config.graph_dpi} DPI",
        "- Graphs use the same finite, row-level QC eligibility as the ranking CSVs.",
        "- Cross-date graphs are marked EXPLORATORY ONLY when historical configuration fingerprints differ or are unavailable for usable dates.",
        "",
        "## Configuration Consistency",
        "",
        f"- Historical analysis config status: {historical_config_status}",
        f"- Dates missing a detectable analysis config: {', '.join(missing_config_dates) if missing_config_dates else 'none'}",
        "- Before final deployment, all dates must be rerun with one reviewed, versioned project configuration.",
        "- Per-date algorithm enable/disable differences are not acceptable for the final dataset.",
        "",
        "## Traceability",
        "",
        f"- Delivery configuration SHA-256: `{config_sha256}`",
        "- See `experiment_date_index.csv` for exact read-only input paths and config fingerprints.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _cross_date_graphs_are_exploratory(inspections: list[DateInspection]) -> bool:
    usable = [inspection for inspection in inspections if inspection.status == "usable"]
    fingerprints = {
        inspection.analysis_config_sha256
        for inspection in usable
        if inspection.analysis_config_sha256
    }
    return len(fingerprints) != 1 or any(
        not inspection.analysis_config_sha256 for inspection in usable
    )


def build_delivery(
    config: DeliveryConfig,
    *,
    run_id: str,
    write: bool = False,
) -> BuildResult:
    config.validate()
    if not SAFE_NAME_PATTERN.fullmatch(run_id):
        raise ValueError("run_id may contain only letters, numbers, '.', '_', and '-'")
    target_dir = config.delivery_root.resolve() / config.experiment / run_id
    if paths_overlap(target_dir, config.raw_experiment_root) or paths_overlap(
        target_dir, config.analysis_experiment_root
    ):
        raise ValueError("Resolved output target overlaps an immutable input root")

    inspections = inspect_experiment(config)
    usable_dates = [
        inspection.date for inspection in inspections if inspection.status == "usable"
    ]
    latest_usable_date = max(usable_dates) if usable_dates else None
    config_sha256 = normalized_config_sha256(config)

    if not write:
        return BuildResult(
            target_dir=target_dir,
            dates=tuple(inspections),
            latest_usable_date=latest_usable_date,
            config_sha256=config_sha256,
            wrote_files=False,
        )

    if target_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing delivery run: {target_dir}. Use a new run_id."
        )

    target_parent = target_dir.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=target_parent))
    try:
        (staging_dir / ".research_delivery_test_output").write_text(
            "Internal rebuildable test preview.\n", encoding="utf-8"
        )
        (staging_dir / "summary_config.yaml").write_text(
            yaml.safe_dump(config.as_dict(), sort_keys=False), encoding="utf-8"
        )

        date_rankings: dict[str, dict[str, list[dict[str, object]]]] = {}
        date_metric_values: dict[str, dict[str, list[float]]] = {}
        combined_rows: list[dict[str, object]] = []
        missing_metrics: list[dict[str, object]] = []
        for inspection in inspections:
            date_rankings[inspection.date] = _write_date_output(
                staging_dir, inspection, config
            )
            if inspection.status == "usable":
                date_metric_values[inspection.date] = {
                    metric: finite_qc_values(inspection.rows, metric)
                    for metric in config.metrics
                }
                combined_rows.extend(
                    {
                        **row,
                        "_delivery_date": inspection.date,
                        "_source_results_path": str(inspection.results_path),
                    }
                    for row in inspection.rows
                )
            for metric in config.metrics:
                if not date_rankings[inspection.date].get(metric):
                    missing_metrics.append(
                        {
                            "date": inspection.date,
                            "metric": metric,
                            "status": inspection.status,
                            "reason": "No finite QC-eligible values or no canonical results.",
                        }
                    )

        summary_dir = staging_dir / "summary"
        _write_csv(
            summary_dir / "experiment_date_index.csv",
            [_date_index_row(inspection) for inspection in inspections],
        )
        _write_csv(
            summary_dir / "combined_results.csv",
            combined_rows,
            fieldnames=("_delivery_date", "_source_results_path"),
        )
        _write_csv(
            summary_dir / "missing_metrics.csv",
            missing_metrics,
            fieldnames=("date", "metric", "status", "reason"),
        )
        if latest_usable_date is not None:
            for metric, rows in date_rankings[latest_usable_date].items():
                if rows:
                    _write_csv(
                        summary_dir
                        / f"latest_date_{ranking_directory_name(config.top_fraction)}"
                        / f"{metric}.csv",
                        rows,
                    )

        _write_experiment_summary(
            summary_dir / "EXPERIMENT_SUMMARY.md",
            config,
            inspections,
            latest_usable_date,
            config_sha256,
        )
        graph_files: list[str] = []
        if config.generate_graphs:
            graph_files = generate_delivery_graphs(
                staging_dir,
                experiment=config.experiment,
                metrics=config.metrics,
                top_fraction=config.top_fraction,
                ranking_directory=ranking_directory_name(config.top_fraction),
                include_ties=config.include_ties,
                graph_dpi=config.graph_dpi,
                date_metric_values=date_metric_values,
                date_rankings=date_rankings,
                latest_usable_date=latest_usable_date,
                exploratory=_cross_date_graphs_are_exploratory(inspections),
            )
        manifest = {
            "schema_version": 1,
            "test_preview": True,
            "experiment": config.experiment,
            "run_id": run_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "delivery_config_sha256": config_sha256,
            "latest_usable_date": latest_usable_date,
            "dates": [_date_index_row(inspection) for inspection in inspections],
            "immutable_inputs_modified": False,
            "source_scans_copied": False,
            "pointclouds_copied": False,
            "graphs_generated": bool(graph_files),
            "graph_files": graph_files,
        }
        (staging_dir / "delivery_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staging_dir.rename(target_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return BuildResult(
        target_dir=target_dir,
        dates=tuple(inspections),
        latest_usable_date=latest_usable_date,
        config_sha256=config_sha256,
        wrote_files=True,
    )
