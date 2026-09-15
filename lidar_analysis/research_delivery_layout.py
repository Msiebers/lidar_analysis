"""Research-delivery folder contract (Research Delivery V2A).

This module is the single source of truth for where each generated delivery
artifact lives. Every generated artifact has exactly one canonical location.
All paths are POSIX-style and relative to the delivery run directory.
See docs/RESEARCH_DELIVERY_TEST_PREVIEW.md for the researcher-facing contract.
"""
from __future__ import annotations

import re

MANIFEST_SCHEMA_VERSION = 2

README_FILE = "README.md"
CONFIG_SNAPSHOT_FILE = "summary_config.yaml"
MARKER_FILE = ".research_delivery_test_output"

SUMMARY_DIR = "summary"
SUMMARY_SUBDIRS = ("data", "growth", "qc")
EXPERIMENT_SUMMARY_FILE = "summary/EXPERIMENT_SUMMARY.md"
COMBINED_RESULTS_FILE = "summary/data/combined_results.csv"
MISSING_METRICS_FILE = "summary/qc/missing_metrics.csv"
GROWTH_DIR = "summary/growth"

MANIFEST_DIR = "manifest"
MANIFEST_FILE = "manifest/delivery_manifest.json"
DATE_INDEX_FILE = "manifest/experiment_date_index.csv"

# Every date folder always contains exactly these subfolders (some may be empty).
DATE_SUBDIRS = ("results", "graphs", "qc", "metadata")

_DATE_DIR_PATTERN = re.compile(r"^\d{4}_\d{2}_\d{2}$")


def date_results_file(date: str) -> str:
    return f"{date}/results/results.csv"


def date_ranking_file(date: str, ranking_directory: str, metric: str) -> str:
    return f"{date}/results/{ranking_directory}/{metric}.csv"


def date_graph_dir(date: str) -> str:
    return f"{date}/graphs"


def date_qc_flags_file(date: str) -> str:
    return f"{date}/qc/qc_flags.csv"


def date_outliers_file(date: str) -> str:
    return f"{date}/qc/outliers.csv"


def date_source_reference_file(date: str) -> str:
    return f"{date}/metadata/source_reference.md"


def growth_graph_file(metric: str) -> str:
    return f"{GROWTH_DIR}/{metric}_by_date.png"


_FIXED_ROLES = {
    README_FILE: "readme",
    CONFIG_SNAPSHOT_FILE: "delivery_config",
    MARKER_FILE: "build_marker",
    EXPERIMENT_SUMMARY_FILE: "experiment_summary",
    COMBINED_RESULTS_FILE: "experiment_results",
    MISSING_METRICS_FILE: "experiment_qc",
    DATE_INDEX_FILE: "date_index",
}
_DATE_SUBDIR_ROLES = {"graphs": "date_graph", "qc": "date_qc", "metadata": "date_metadata"}


def artifact_role(relative_path: str) -> str:
    """Return the contract role of a generated file, or raise if it has no canonical home."""
    if relative_path in _FIXED_ROLES:
        return _FIXED_ROLES[relative_path]
    parts = relative_path.split("/")
    if len(parts) == 3 and parts[:2] == ["summary", "growth"]:
        return "growth_graph"
    if len(parts) >= 3 and _DATE_DIR_PATTERN.fullmatch(parts[0]):
        if parts[1] == "results":
            if parts[2:] == ["results.csv"]:
                return "date_results_snapshot"
            if len(parts) == 4:
                return "date_ranking"
        elif len(parts) == 3 and parts[1] in _DATE_SUBDIR_ROLES:
            return _DATE_SUBDIR_ROLES[parts[1]]
    raise ValueError(f"Generated file is outside the delivery folder contract: {relative_path}")
