"""Research-delivery folder contract (Research Delivery V2A).

This module is the single source of truth for where each generated delivery
artifact lives. Every generated artifact has exactly one canonical location.
All paths are POSIX-style and relative to the delivery run directory.
See docs/RESEARCH_DELIVERY_TEST_PREVIEW.md for the researcher-facing contract.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

MANIFEST_SCHEMA_VERSION = 2

README_FILE = "README.md"
CONFIG_SNAPSHOT_FILE = "summary_config.yaml"
MARKER_FILE = ".research_delivery_test_output"

SUMMARY_DIR = "summary"
SUMMARY_SUBDIRS = ("data", "growth", "qc")
EXPERIMENT_SUMMARY_FILE = "summary/EXPERIMENT_SUMMARY.md"
COMBINED_RESULTS_FILE = "summary/data/combined_results.csv"
MISSING_METRICS_FILE = "summary/qc/missing_metrics.csv"
# Research Delivery V3A: genotype identity QC artifacts. Placed alongside
# missing_metrics.csv (not summary/data/) because both are the same kind of
# artifact -- a per-experiment QC finding about the combined results, not
# combined results data itself.
MISSING_GENOTYPE_MAPPING_FILE = "summary/qc/missing_genotype_mapping.csv"
UNUSED_GENOTYPE_MAPPINGS_FILE = "summary/qc/unused_genotype_mappings.csv"
GROWTH_DIR = "summary/growth"

MANIFEST_DIR = "manifest"
MANIFEST_FILE = "manifest/delivery_manifest.json"
DATE_INDEX_FILE = "manifest/experiment_date_index.csv"
# Research Delivery V3A: a frozen, byte-identical copy of the genotype map
# used for this build -- same reasoning as date_results_file() freezing
# results.csv (its bytes directly become delivered genotype_id values, so
# unlike analysis_config -- a pure consistency fingerprint, never copied --
# this delivery must be self-contained even if the external map changes
# later). Lives in manifest/ rather than a new top-level directory: it's
# technical provenance researchers rarely need directly, same category as
# experiment_date_index.csv and delivery_manifest.json.
GENOTYPE_MAP_SNAPSHOT_FILE = "manifest/genotype_map.csv"

# Every date folder always contains exactly these subfolders (some may be empty).
DATE_SUBDIRS = ("results", "graphs", "qc", "metadata")

_DATE_DIR_PATTERN = re.compile(r"^\d{4}_\d{2}_\d{2}$")

# Config-driven graph selection (Research Delivery V2B).
# "histogram" and "ranking" are per-date graphs; "boxplot" is a cross-date summary graph.
GRAPH_TYPES = ("histogram", "ranking", "boxplot")
GRAPH_TYPE_SCOPES = {"histogram": "date", "ranking": "date", "boxplot": "summary"}


@dataclass(frozen=True)
class GraphSpec:
    """One researcher-selected graph: what to plot, for which metric, at what scope."""

    type: str
    metric: str
    scope: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "metric": self.metric, "scope": self.scope}


def default_graph_specs(metrics: Sequence[str]) -> tuple[GraphSpec, ...]:
    """The V2A-compatible default: every graph type for every configured metric.

    Used whenever a config omits the optional ``graphs:`` selection list.
    """
    return tuple(
        GraphSpec(type=graph_type, metric=metric, scope=GRAPH_TYPE_SCOPES[graph_type])
        for graph_type in GRAPH_TYPES
        for metric in metrics
    )


def date_results_file(date: str) -> str:
    return f"{date}/results/results.csv"


def date_ranking_file(date: str, ranking_directory: str, metric: str) -> str:
    return f"{date}/results/{ranking_directory}/{metric}.csv"


def date_graph_dir(date: str) -> str:
    return f"{date}/graphs"


def date_graph_data_file(date: str, stem: str) -> str:
    """Companion CSV for a per-date graph, e.g. stem='points_distribution'."""
    return f"{date}/graphs/{stem}.csv"


def date_qc_flags_file(date: str) -> str:
    return f"{date}/qc/qc_flags.csv"


def date_outliers_file(date: str) -> str:
    return f"{date}/qc/outliers.csv"


def date_source_reference_file(date: str) -> str:
    return f"{date}/metadata/source_reference.md"


def growth_graph_file(metric: str) -> str:
    return f"{GROWTH_DIR}/{metric}_by_date.png"


def growth_graph_data_file(metric: str) -> str:
    """Companion CSV for a cross-date growth boxplot."""
    return f"{GROWTH_DIR}/{metric}_by_date.csv"


_FIXED_ROLES = {
    README_FILE: "readme",
    CONFIG_SNAPSHOT_FILE: "delivery_config",
    MARKER_FILE: "build_marker",
    EXPERIMENT_SUMMARY_FILE: "experiment_summary",
    COMBINED_RESULTS_FILE: "experiment_results",
    MISSING_METRICS_FILE: "experiment_qc",
    MISSING_GENOTYPE_MAPPING_FILE: "experiment_qc",
    # Distinct role: an audit note ("this map entry was never observed"),
    # not a QC problem needing action the way a missing mapping is.
    UNUSED_GENOTYPE_MAPPINGS_FILE: "experiment_qc_audit",
    DATE_INDEX_FILE: "date_index",
    GENOTYPE_MAP_SNAPSHOT_FILE: "genotype_map_snapshot",
}
_DATE_SUBDIR_ROLES = {"qc": "date_qc", "metadata": "date_metadata"}


def artifact_role(relative_path: str) -> str:
    """Return the contract role of a generated file, or raise if it has no canonical home."""
    if relative_path in _FIXED_ROLES:
        return _FIXED_ROLES[relative_path]
    parts = relative_path.split("/")
    if len(parts) == 3 and parts[:2] == ["summary", "growth"]:
        return "growth_graph_data" if parts[2].endswith(".csv") else "growth_graph"
    if len(parts) >= 3 and _DATE_DIR_PATTERN.fullmatch(parts[0]):
        if parts[1] == "results":
            if parts[2:] == ["results.csv"]:
                return "date_results_snapshot"
            if len(parts) == 4:
                return "date_ranking"
        elif len(parts) == 3 and parts[1] == "graphs":
            return "date_graph_data" if parts[2].endswith(".csv") else "date_graph"
        elif len(parts) == 3 and parts[1] in _DATE_SUBDIR_ROLES:
            return _DATE_SUBDIR_ROLES[parts[1]]
    raise ValueError(f"Generated file is outside the delivery folder contract: {relative_path}")
