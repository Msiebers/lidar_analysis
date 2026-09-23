from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import lidar_analysis.research_delivery as research_delivery
from lidar_analysis.research_delivery import (
    DeliveryConfig,
    build_delivery,
    inspect_experiment,
)
from lidar_analysis.research_delivery_layout import GraphSpec


RESULT_FIELDS = [
    "experiment",
    "date",
    "scan_name",
    "scan_number",
    "plot",
    "side",
    "target_type",
    "target_id",
    "points",
    "point_density_m2",
    "stand_topo_per_m",
    "qc_status",
]


def write_results(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def add_source_pair(source: Path, scan_name: str) -> None:
    source.mkdir(parents=True, exist_ok=True)
    (source / f"{scan_name}_lidar.csv").write_text("time,distance\n0,1\n", encoding="utf-8")
    (source / f"{scan_name}_pico.csv").write_text("time,encoder\n0,1\n", encoding="utf-8")


@pytest.fixture
def experiment(tmp_path: Path) -> tuple[DeliveryConfig, Path, Path, Path]:
    raw_root = tmp_path / "raw" / "MeadowFescue_2026"
    analysis_root = tmp_path / "analysis" / "MeadowFescue_2026"
    delivery_root = tmp_path / "deliveries"
    raw_root.mkdir(parents=True)
    analysis_root.mkdir(parents=True)

    may14_source = raw_root / "2026_05_14" / "source"
    add_source_pair(may14_source, "scan14a")
    add_source_pair(may14_source, "scan14b")
    (may14_source / "experiment_config.yaml").write_text(
        "analysis:\n  voxel_size: 0.01\n", encoding="utf-8"
    )
    may14_rows = [
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_14",
            "scan_name": "scan14a",
            "scan_number": "",
            "plot": 1,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_1",
            "points": 10,
            "point_density_m2": 100,
            "stand_topo_per_m": 2,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_14",
            "scan_name": "scan14b",
            "scan_number": "",
            "plot": 2,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_2",
            "points": 20,
            "point_density_m2": 90,
            "stand_topo_per_m": 3,
            "qc_status": "pass",
        },
    ]
    may14_output = analysis_root / "2026_05_14" / "output"
    write_results(may14_output / "results.csv", may14_rows)
    may14_pointclouds = may14_output / "pointclouds"
    may14_pointclouds.mkdir(parents=True)
    (may14_pointclouds / "plot_1_MeadowFescue_2026.csv").write_text("x,y,z\n", encoding="utf-8")
    (may14_pointclouds / "topology_count_plot_1.csv").write_text("count\n1\n", encoding="utf-8")

    may27_source = raw_root / "2026_05_27" / "source"
    add_source_pair(may27_source, "scan27a")

    may28_source = raw_root / "2026_05_28" / "source"
    for scan_name in ("scan28a", "scan28b", "scan28c", "scan28d", "scan28e"):
        add_source_pair(may28_source, scan_name)
    (may28_source / "experiment_config.yaml").write_text(
        "analysis:\n  voxel_size: 0.02\n", encoding="utf-8"
    )
    may28_rows = [
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_name": "scan28a",
            "scan_number": "",
            "plot": 1,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_1",
            "points": 100,
            "point_density_m2": 10,
            "stand_topo_per_m": 2,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_name": "scan28b",
            "scan_number": "",
            "plot": 2,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_2",
            "points": 100,
            "point_density_m2": 20,
            "stand_topo_per_m": 3,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_name": "scan28c",
            "scan_number": "",
            "plot": 3,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_3",
            "points": 80,
            "point_density_m2": 500,
            "stand_topo_per_m": 4,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_name": "scan28d",
            "scan_number": "",
            "plot": 4,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_4",
            "points": 70,
            "point_density_m2": 40,
            "stand_topo_per_m": 10,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_name": "scan28e",
            "scan_number": "",
            "plot": 5,
            "side": "none",
            "target_type": "plot",
            "target_id": "plot_5",
            "points": 1000,
            "point_density_m2": 1000,
            "stand_topo_per_m": 1000,
            "qc_status": "failed",
        },
    ]
    may28_root = analysis_root / "2026_05_28"
    write_results(may28_root / "results.csv", may28_rows)
    may28_pointclouds = may28_root / "pointclouds"
    may28_pointclouds.mkdir()
    (may28_pointclouds / "plot_1_MeadowFescue_2026.csv").write_text("x,y,z\n", encoding="utf-8")
    (may28_pointclouds / "marker_reference_points.csv").write_text("x,y,z\n", encoding="utf-8")
    (may28_root / "output").mkdir()
    (may28_root / "output" / "results.csv").symlink_to("../results.csv")
    (may28_root / "output" / "pointclouds").symlink_to("../pointclouds")

    config = DeliveryConfig(
        experiment="MeadowFescue_2026",
        raw_experiment_root=raw_root,
        analysis_experiment_root=analysis_root,
        delivery_root=delivery_root,
        metrics=("points", "point_density_m2", "stand_topo_per_m"),
        top_fraction=0.15,
        include_ties=True,
        generate_graphs=False,
    )
    return config, raw_root, analysis_root, delivery_root


def test_inspection_supports_both_layouts_and_marks_incomplete_date(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment

    inspections = {item.date: item for item in inspect_experiment(config)}

    assert inspections["2026_05_14"].status == "usable"
    assert inspections["2026_05_14"].results_path == (
        config.analysis_experiment_root / "2026_05_14" / "output" / "results.csv"
    )
    assert inspections["2026_05_14"].main_pointcloud_csv_files == 1
    assert inspections["2026_05_14"].topology_pointcloud_csv_files == 1

    assert inspections["2026_05_27"].status == "incomplete"
    assert "No analysis directory" in inspections["2026_05_27"].reason

    assert inspections["2026_05_28"].status == "usable"
    assert inspections["2026_05_28"].main_pointcloud_csv_files == 1
    assert inspections["2026_05_28"].marker_reference_csv_files == 1


def test_dry_run_writes_nothing(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, delivery_root = experiment

    result = build_delivery(config, run_id="dry_run", write=False)

    assert result.wrote_files is False
    assert result.latest_usable_date == "2026_05_28"
    assert not delivery_root.exists()


def test_write_builds_separate_rankings_without_changing_inputs(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, raw_root, analysis_root, _delivery_root = experiment
    raw_before = file_hashes(raw_root)
    analysis_before = file_hashes(analysis_root)

    result = build_delivery(config, run_id="preview_v1", write=True)

    assert result.wrote_files is True
    assert result.latest_usable_date == "2026_05_28"
    target = result.target_dir
    assert (target / ".research_delivery_test_output").is_file()
    assert (target / "2026_05_27" / "metadata" / "source_reference.md").is_file()
    assert not (target / "2026_05_27" / "results" / "results.csv").exists()

    points = read_rows(target / "2026_05_28" / "results" / "top_15_percent" / "points.csv")
    assert [row["plot"] for row in points] == ["1", "2"]
    assert {row["_ranking_value"] for row in points} == {"100.0"}

    density = read_rows(
        target / "2026_05_28" / "results" / "top_15_percent" / "point_density_m2.csv"
    )
    assert [row["plot"] for row in density] == ["3"]
    assert all(row["plot"] != "5" for row in density)

    date_index = {
        row["date"]: row
        for row in read_rows(target / "manifest" / "experiment_date_index.csv")
    }
    assert date_index["2026_05_27"]["status"] == "incomplete"
    assert date_index["2026_05_28"]["status"] == "usable"

    summary = (target / "summary" / "EXPERIMENT_SUMMARY.md").read_text(encoding="utf-8")
    assert "Preview Build" in summary
    assert "Per-date algorithm enable/disable differences are not acceptable" in summary
    assert "inconsistent" in summary
    assert "2026_05_28/results/top_15_percent" in summary

    assert not list(target.rglob("plot_*.csv"))
    assert file_hashes(raw_root) == raw_before
    assert file_hashes(analysis_root) == analysis_before


def test_graph_enabled_preview_builds_expected_deterministic_inventory(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=96)

    result = build_delivery(graph_config, run_id="preview_v2_graphs", write=True)
    target = result.target_dir
    metrics = graph_config.metrics
    expected = {
        f"{date}/graphs/{metric}_{suffix}.png"
        for date in USABLE_DATES
        for metric in metrics
        for suffix in ("distribution", "top_15_percent")
    }
    expected.update(f"summary/growth/{metric}_by_date.png" for metric in metrics)

    graph_paths = sorted(target.rglob("*.png"))
    graph_files = [path.relative_to(target).as_posix() for path in graph_paths]
    assert len(graph_files) == 15
    assert set(graph_files) == expected
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in graph_paths)
    assert (target / "2026_05_27" / "graphs").is_dir()
    assert not list((target / "2026_05_27" / "graphs").iterdir())
    assert not (target / ".matplotlib-cache").exists()

    points_ranking = read_rows(target / "2026_05_28" / "results" / "top_15_percent" / "points.csv")
    points_graph = (target / "2026_05_28" / "graphs" / "points_top_15_percent.png").read_bytes()
    assert {row["_ranking_cutoff"] for row in points_ranking} == {"100.0"}
    assert b"selected=2, eligible=4, cutoff=100" in points_graph

    manifest = load_manifest(target)
    assert manifest["graphs_generated"] is True
    assert manifest["graph_files"] == sorted(expected)
    png_artifacts = {a["path"] for a in manifest["artifacts"] if a["path"].endswith(".png")}
    assert png_artifacts == expected

    for metric in metrics:
        summary_graph = target / "summary" / "growth" / f"{metric}_by_date.png"
        assert b"EXPLORATORY ONLY" in summary_graph.read_bytes()


def test_graph_disabled_mode_preserves_non_graph_outputs(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment

    result = build_delivery(config, run_id="preview_graphs_disabled", write=True)

    assert not list(result.target_dir.rglob("*.png"))
    assert (
        result.target_dir / "2026_05_28" / "results" / "top_15_percent" / "points.csv"
    ).is_file()
    manifest = load_manifest(result.target_dir)
    assert manifest["graphs_generated"] is False
    assert manifest["graph_files"] == []


@pytest.mark.parametrize("graph_dpi", [71, 601, 160.0, True, "160"])
def test_rejects_invalid_graph_dpi(
    experiment: tuple[DeliveryConfig, Path, Path, Path], graph_dpi: object
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment

    with pytest.raises(ValueError, match="integer from 72 through 600"):
        replace(config, graph_dpi=graph_dpi).validate()


def test_graph_failure_leaves_no_partial_delivery(
    experiment: tuple[DeliveryConfig, Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True)
    target = graph_config.delivery_root / graph_config.experiment / "graph_failure"

    def fail_graphs(*_args: object, **_kwargs: object) -> list[str]:
        raise RuntimeError("synthetic graph failure")

    monkeypatch.setattr(research_delivery, "generate_delivery_graphs", fail_graphs)
    with pytest.raises(RuntimeError, match="synthetic graph failure"):
        build_delivery(graph_config, run_id="graph_failure", write=True)

    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_existing_run_is_never_overwritten(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    build_delivery(config, run_id="preview_v1", write=True)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        build_delivery(config, run_id="preview_v1", write=True)


def test_rejects_delivery_root_that_overlaps_raw_input(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, raw_root, _analysis_root, _delivery_root = experiment
    unsafe = DeliveryConfig(
        experiment=config.experiment,
        raw_experiment_root=config.raw_experiment_root,
        analysis_experiment_root=config.analysis_experiment_root,
        delivery_root=raw_root / "unsafe_output",
    )

    with pytest.raises(ValueError, match="must not equal, contain, or be contained"):
        unsafe.validate()


def test_rejects_unvalidated_geometry_metric(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    unsafe = DeliveryConfig(
        experiment=config.experiment,
        raw_experiment_root=config.raw_experiment_root,
        analysis_experiment_root=config.analysis_experiment_root,
        delivery_root=config.delivery_root,
        metrics=("points", "height_m"),
    )

    with pytest.raises(ValueError, match="Unvalidated ranking metric"):
        unsafe.validate()



# ---------------------------------------------------------------------------
# Research Delivery V2A: folder contract + generated-duplicate elimination
# ---------------------------------------------------------------------------

DATE_SUBDIRS = ("results", "graphs", "qc", "metadata")
ALL_DATES = ("2026_05_14", "2026_05_27", "2026_05_28")
USABLE_DATES = ("2026_05_14", "2026_05_28")
INCOMPLETE_DATE = "2026_05_27"
KNOWN_ARTIFACT_ROLES = {
    "readme",
    "delivery_config",
    "build_marker",
    "experiment_summary",
    "experiment_results",
    "experiment_qc",
    "growth_graph",
    "growth_graph_data",
    "date_index",
    "date_results_snapshot",
    "date_ranking",
    "date_graph",
    "date_graph_data",
    "date_qc",
    "date_metadata",
}


def load_manifest(target: Path) -> dict:
    return json.loads(
        (target / "manifest" / "delivery_manifest.json").read_text(encoding="utf-8")
    )


def relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_folder_contract_layout_is_consistent_for_every_date(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    target = build_delivery(config, run_id="contract_layout", write=True).target_dir

    assert {path.name for path in target.iterdir()} == {
        "README.md",
        "summary_config.yaml",
        "summary",
        "manifest",
        ".research_delivery_test_output",
        *ALL_DATES,
    }
    # Every date has the same four folders, even when some are empty.
    for date in ALL_DATES:
        date_root = target / date
        assert {path.name for path in date_root.iterdir()} == set(DATE_SUBDIRS)
        assert all((date_root / name).is_dir() for name in DATE_SUBDIRS)
        assert (date_root / "metadata" / "source_reference.md").is_file()
    # QC artifacts exist only where results QC was actually performed.
    for date in USABLE_DATES:
        assert (target / date / "results" / "results.csv").is_file()
        assert (target / date / "qc" / "qc_flags.csv").is_file()
        assert (target / date / "qc" / "outliers.csv").is_file()
    for name in ("results", "graphs", "qc"):
        assert not list((target / INCOMPLETE_DATE / name).iterdir())

    assert {path.name for path in (target / "summary").iterdir()} == {
        "EXPERIMENT_SUMMARY.md",
        "data",
        "growth",
        "qc",
    }
    assert (target / "summary" / "data" / "combined_results.csv").is_file()
    assert (target / "summary" / "qc" / "missing_metrics.csv").is_file()
    assert sorted(path.name for path in (target / "manifest").iterdir()) == [
        "delivery_manifest.json",
        "experiment_date_index.csv",
    ]

    readme = (target / "README.md").read_text(encoding="utf-8")
    for token in ("summary/", "manifest/", "results/", "graphs/", "qc/", "metadata/"):
        assert token in readme


def test_incomplete_date_status_is_recorded_without_qc_artifacts(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    target = build_delivery(config, run_id="incomplete_date", write=True).target_dir
    index = {
        row["date"]: row
        for row in read_rows(target / "manifest" / "experiment_date_index.csv")
    }
    row = index[INCOMPLETE_DATE]
    assert row["status"] == "incomplete"
    assert row["reason"]

    reference = (target / INCOMPLETE_DATE / "metadata" / "source_reference.md").read_text(
        encoding="utf-8"
    )
    assert "incomplete" in reference
    assert row["reason"] in reference
    assert "Results QC was not performed" in reference
    # Input-availability findings from inspection are preserved, not dropped.
    assert "Inspection findings" in reference
    assert "is unavailable; its ranking will be skipped" in reference

    missing = read_rows(target / "summary" / "qc" / "missing_metrics.csv")
    assert {r["metric"] for r in missing if r["date"] == INCOMPLETE_DATE} == set(config.metrics)

    usable_reference = (target / "2026_05_28" / "metadata" / "source_reference.md").read_text(
        encoding="utf-8"
    )
    assert "Results QC was not performed" not in usable_reference


def test_declared_generated_redundancies_are_absent(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)
    target = build_delivery(graph_config, run_id="no_redundancy", write=True).target_dir
    files = relative_files(target)

    # Latest-date copies and the legacy summary graph folder are not generated.
    assert not [f for f in files if f.startswith(("summary/latest_date_", "summary/graphs/"))]
    # Legacy top-level / summary locations are gone.
    for legacy in (
        "delivery_manifest.json",
        "summary/experiment_date_index.csv",
        "summary/combined_results.csv",
        "summary/missing_metrics.csv",
    ):
        assert legacy not in files
    for date in ALL_DATES:
        assert not (target / date / "source").exists()
        assert not (target / date / "pointclouds").exists()
        assert not (target / date / "metadata" / "date_status.json").exists()
        for legacy_dir in ("graphs", "qc", "outliers"):
            assert not (target / date / "results" / legacy_dir).exists()
    assert not [f for f in files if f.endswith("pointcloud_inventory.csv")]

    # Each of these artifacts has exactly one canonical home.
    assert [f for f in files if f.endswith("experiment_date_index.csv")] == [
        "manifest/experiment_date_index.csv"
    ]
    assert [f for f in files if f.endswith("combined_results.csv")] == [
        "summary/data/combined_results.csv"
    ]
    ranking_files = [f for f in files if "/top_15_percent/" in f]
    assert ranking_files
    assert all(f.split("/")[1:3] == ["results", "top_15_percent"] for f in ranking_files)


def test_manifest_is_self_describing_and_inventories_every_artifact(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)
    result = build_delivery(graph_config, run_id="manifest_v2", write=True)
    target = result.target_dir
    manifest = load_manifest(target)

    assert manifest["schema_version"] == 2
    assert manifest["test_preview"] is True
    assert manifest["experiment"] == "MeadowFescue_2026"
    assert manifest["run_id"] == "manifest_v2"
    assert manifest["created_at_utc"]
    assert manifest["delivery_config_sha256"] == result.config_sha256
    assert manifest["latest_usable_date"] == "2026_05_28"
    assert manifest["immutable_inputs_modified"] is False
    assert manifest["source_scans_copied"] is False
    assert manifest["pointclouds_copied"] is False
    assert manifest["date_index"] == "manifest/experiment_date_index.csv"
    assert (target / manifest["date_index"]).is_file()
    assert manifest["date_count"] == 3
    # Lightweight date list only; full provenance lives in the date index.
    assert manifest["dates"] == [
        {"date": "2026_05_14", "status": "usable"},
        {"date": "2026_05_27", "status": "incomplete"},
        {"date": "2026_05_28", "status": "usable"},
    ]

    artifacts = manifest["artifacts"]
    paths = [artifact["path"] for artifact in artifacts]
    assert paths == sorted(paths)
    assert set(paths) == relative_files(target) - {"manifest/delivery_manifest.json"}
    for artifact in artifacts:
        assert set(artifact) == {"path", "role", "sha256"}
        artifact_path = Path(artifact["path"])
        assert not artifact_path.is_absolute()
        assert ".." not in artifact_path.parts
        assert sha256_bytes(target / artifact_path) == artifact["sha256"]

    roles = {artifact["path"]: artifact["role"] for artifact in artifacts}
    assert set(roles.values()) <= KNOWN_ARTIFACT_ROLES
    assert roles["README.md"] == "readme"
    assert roles["summary_config.yaml"] == "delivery_config"
    assert roles[".research_delivery_test_output"] == "build_marker"
    assert roles["summary/EXPERIMENT_SUMMARY.md"] == "experiment_summary"
    assert roles["summary/data/combined_results.csv"] == "experiment_results"
    assert roles["summary/qc/missing_metrics.csv"] == "experiment_qc"
    assert roles["summary/growth/points_by_date.png"] == "growth_graph"
    assert roles["manifest/experiment_date_index.csv"] == "date_index"
    assert roles["2026_05_28/results/results.csv"] == "date_results_snapshot"
    assert roles["2026_05_28/results/top_15_percent/points.csv"] == "date_ranking"
    assert roles["2026_05_28/graphs/points_distribution.png"] == "date_graph"
    assert roles["2026_05_28/graphs/points_distribution.csv"] == "date_graph_data"
    assert roles["summary/growth/points_by_date.csv"] == "growth_graph_data"
    assert roles["2026_05_28/qc/outliers.csv"] == "date_qc"
    assert roles["2026_05_28/qc/qc_flags.csv"] == "date_qc"
    assert roles["2026_05_28/metadata/source_reference.md"] == "date_metadata"
    assert roles["2026_05_27/metadata/source_reference.md"] == "date_metadata"
    assert set(manifest["graph_files"]) == {
        path for path, role in roles.items() if role in {"date_graph", "growth_graph"}
    }


def test_results_snapshot_is_a_verifiable_copy_of_its_source(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
    tmp_path: Path,
) -> None:
    config, _raw_root, analysis_root, _delivery_root = experiment
    # SAFETY GUARD: the mutation below is only allowed on pytest's temporary fixture.
    assert analysis_root.resolve().is_relative_to(tmp_path.resolve())
    assert not analysis_root.resolve().is_relative_to(Path("/media"))
    may14_source = analysis_root / "2026_05_14" / "output" / "results.csv"
    assert may14_source.resolve().is_relative_to(tmp_path.resolve())

    # A byte-order mark must survive: the snapshot is a frozen copy, not a re-serialization.
    may14_source.write_bytes(b"\xef\xbb\xbf" + may14_source.read_bytes())

    target = build_delivery(config, run_id="snapshot", write=True).target_dir
    index = {
        row["date"]: row
        for row in read_rows(target / "manifest" / "experiment_date_index.csv")
    }
    for date in USABLE_DATES:
        row = index[date]
        source = Path(row["results_path"])
        assert source.is_absolute() and source.is_file()
        source_hash = sha256_bytes(source)
        assert row["results_sha256"] == source_hash
        # Intentional, documented duplication: frozen delivery snapshot of an input.
        assert sha256_bytes(target / date / "results" / "results.csv") == source_hash
        assert row["pointcloud_dir"] and Path(row["pointcloud_dir"]).is_dir()
    assert index[INCOMPLETE_DATE]["results_sha256"] == ""
    assert index[INCOMPLETE_DATE]["pointcloud_dir"] == ""


def test_combined_results_trace_back_to_date_snapshot_and_source(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    target = build_delivery(config, run_id="traceability", write=True).target_dir
    index = {
        row["date"]: row
        for row in read_rows(target / "manifest" / "experiment_date_index.csv")
    }
    combined = read_rows(target / "summary" / "data" / "combined_results.csv")
    assert len(combined) == 7

    snapshot_ids: dict[str, set[tuple[str, str, str, str]]] = {}
    for row in combined:
        relative = row["_delivery_results_path"]
        assert relative == f"{row['_delivery_date']}/results/results.csv"
        snapshot = target / relative
        assert snapshot.is_file()
        if relative not in snapshot_ids:
            snapshot_ids[relative] = {
                (r["scan_name"], r["scan_number"], r["plot"], r["side"])
                for r in read_rows(snapshot)
            }
        assert (
            row["scan_name"], row["scan_number"], row["plot"], row["side"]
        ) in snapshot_ids[relative]
        assert row["_source_results_path"] == index[row["_delivery_date"]]["results_path"]
        assert Path(row["_source_results_path"]).is_file()

    reference = (target / "2026_05_28" / "metadata" / "source_reference.md").read_text(
        encoding="utf-8"
    )
    for key in ("raw_date_dir", "source_dir", "results_path", "results_sha256", "pointcloud_dir"):
        assert index["2026_05_28"][key] in reference
    assert "../../manifest/experiment_date_index.csv" in reference


def test_build_identity_lives_only_in_manifest(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    """Contract: run_id and created_at_utc appear only in delivery_manifest.json.

    Graphs are disabled so the comparison cannot depend on PNG rendering.
    """
    config, _raw_root, _analysis_root, _delivery_root = experiment
    first = build_delivery(config, run_id="repeat_a", write=True).target_dir
    second = build_delivery(config, run_id="repeat_b", write=True).target_dir

    first_hashes = {k.replace("\\", "/"): v for k, v in file_hashes(first).items()}
    second_hashes = {k.replace("\\", "/"): v for k, v in file_hashes(second).items()}
    assert set(first_hashes) == set(second_hashes)
    differing = {k for k in first_hashes if first_hashes[k] != second_hashes[k]}
    assert differing == {"manifest/delivery_manifest.json"}

    for root, run_id in ((first, "repeat_a"), (second, "repeat_b")):
        for relative in relative_files(root) - {"manifest/delivery_manifest.json"}:
            assert run_id.encode() not in (root / relative).read_bytes(), relative

    first_manifest = load_manifest(first)
    second_manifest = load_manifest(second)
    for manifest in (first_manifest, second_manifest):
        manifest.pop("created_at_utc")
        manifest.pop("run_id")
    assert first_manifest == second_manifest


def test_dates_filter_builds_only_requested_dates(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    filtered = replace(config, dates=USABLE_DATES)

    result = build_delivery(filtered, run_id="filtered", write=True)

    assert [inspection.date for inspection in result.dates] == list(USABLE_DATES)
    target = result.target_dir
    assert not (target / INCOMPLETE_DATE).exists()
    assert [
        row["date"] for row in read_rows(target / "manifest" / "experiment_date_index.csv")
    ] == list(USABLE_DATES)
    assert load_manifest(target)["dates"] == [
        {"date": date, "status": "usable"} for date in USABLE_DATES
    ]


def test_dates_filter_is_optional_in_config_snapshot(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    assert "dates" not in config.as_dict()
    assert replace(config, dates=("2026_05_14",)).as_dict()["dates"] == ["2026_05_14"]


def test_dates_filter_is_parsed_from_mapping(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, raw_root, analysis_root, delivery_root = experiment
    mapping = {
        "experiment": config.experiment,
        "raw_experiment_root": str(raw_root),
        "analysis_experiment_root": str(analysis_root),
        "delivery_root": str(delivery_root),
        "dates": ["2026_05_28", "2026_05_14"],
    }
    assert DeliveryConfig.from_mapping(mapping).dates == ("2026_05_14", "2026_05_28")
    assert DeliveryConfig.from_mapping({**mapping, "dates": None}).dates == ()
    with pytest.raises(ValueError, match="dates must be a list"):
        DeliveryConfig.from_mapping({**mapping, "dates": "2026_05_14"})


@pytest.mark.parametrize(
    ("dates", "message"),
    [
        (("2026_05_30",), "not found"),
        (("2026-05-14",), "YYYY_MM_DD"),
        (("2026_05_14", "2026_05_14"), "duplicates"),
    ],
)
def test_rejects_invalid_dates_filter(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
    dates: tuple[str, ...],
    message: str,
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    with pytest.raises(ValueError, match=message):
        build_delivery(replace(config, dates=dates), run_id="bad_dates")


# ---------------------------------------------------------------------------
# Research Delivery V2B: config-driven graphs + graph-data traceability
# ---------------------------------------------------------------------------


def test_graphs_config_rejects_invalid_entries(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment

    with pytest.raises(ValueError, match="type must be one of"):
        replace(
            config,
            graphs=(GraphSpec(type="pie", metric="points", scope="date"),),
        ).validate()

    with pytest.raises(ValueError, match="requires scope"):
        replace(
            config,
            graphs=(GraphSpec(type="histogram", metric="points", scope="summary"),),
        ).validate()

    with pytest.raises(ValueError, match="is not in this config's metrics"):
        replace(
            config,
            graphs=(GraphSpec(type="histogram", metric="height_m", scope="date"),),
        ).validate()

    with pytest.raises(ValueError, match="must not repeat"):
        replace(
            config,
            graphs=(
                GraphSpec(type="histogram", metric="points", scope="date"),
                GraphSpec(type="histogram", metric="points", scope="date"),
            ),
        ).validate()


def test_graphs_config_selects_only_requested_graphs(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    subset_config = replace(
        config,
        generate_graphs=True,
        graph_dpi=72,
        graphs=(GraphSpec(type="histogram", metric="points", scope="date"),),
    )

    target = build_delivery(subset_config, run_id="graphs_subset", write=True).target_dir

    png_files = {p.relative_to(target).as_posix() for p in target.rglob("*.png")}
    assert png_files == {
        "2026_05_14/graphs/points_distribution.png",
        "2026_05_28/graphs/points_distribution.png",
    }
    graphish_csvs = {
        p.relative_to(target).as_posix()
        for p in target.rglob("*.csv")
        if "/graphs/" in p.relative_to(target).as_posix()
        or p.relative_to(target).as_posix().startswith("summary/growth/")
    }
    assert graphish_csvs == {
        "2026_05_14/graphs/points_distribution.csv",
        "2026_05_28/graphs/points_distribution.csv",
    }
    manifest = load_manifest(target)
    assert set(manifest["graph_files"]) == png_files


def test_histogram_graph_data_traces_back_to_results(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)

    target = build_delivery(graph_config, run_id="histogram_trace", write=True).target_dir

    records = read_rows(target / "2026_05_28" / "graphs" / "points_distribution.csv")
    # scan28e fails QC and is excluded; the other four rows are eligible.
    assert len(records) == 4
    assert {r["scan_name"] for r in records} == {"scan28a", "scan28b", "scan28c", "scan28d"}
    results_rows = {
        row["scan_name"]: row
        for row in read_rows(target / "2026_05_28" / "results" / "results.csv")
    }
    for record in records:
        source = results_rows[record["scan_name"]]
        assert record["scan_number"] == source["scan_number"]
        assert record["plot"] == source["plot"]
        assert record["side"] == source["side"]
        assert float(record["value"]) == float(source["points"])
        assert record["date"] == "2026_05_28"
        assert record["metric"] == "points"


def test_boxplot_graph_data_covers_all_usable_dates(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)

    target = build_delivery(graph_config, run_id="boxplot_trace", write=True).target_dir

    records = read_rows(target / "summary" / "growth" / "points_by_date.csv")
    assert {r["date"] for r in records} == {"2026_05_14", "2026_05_28"}
    assert len(records) == 6  # 2 QC-eligible rows on 2026_05_14 + 4 on 2026_05_28


def test_graph_data_outlier_flag_matches_find_outliers(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)

    target = build_delivery(graph_config, run_id="outlier_trace", write=True).target_dir

    inspections = {item.date: item for item in inspect_experiment(config)}
    expected_outliers = {
        row["scan_name"]
        for row in research_delivery.find_outliers(
            inspections["2026_05_28"].rows, "point_density_m2", config.outlier_iqr_multiplier
        )
    }
    records = read_rows(
        target / "2026_05_28" / "graphs" / "point_density_m2_distribution.csv"
    )
    assert records  # sanity: the fixture actually produced rows to check
    for record in records:
        assert (record["is_outlier"] == "True") == (record["scan_name"] in expected_outliers)


def test_ranking_graph_has_no_redundant_data_file(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment
    graph_config = replace(config, generate_graphs=True, graph_dpi=72)

    target = build_delivery(graph_config, run_id="ranking_no_dup", write=True).target_dir

    assert not (target / "2026_05_28" / "graphs" / "points_top_15_percent.csv").exists()
    ranking_csv = read_rows(
        target / "2026_05_28" / "results" / "top_15_percent" / "points.csv"
    )
    assert {"scan_name", "scan_number", "plot", "side"} <= set(ranking_csv[0])


def test_result_identity_matches_central_runner() -> None:
    """RESULT_IDENTITY_FIELDS/RESULT_UNIQUE_FIELDS are declared independently in
    research_delivery.py (see the comment there for why). This test is the
    trip-wire: if central_runner's identity fields ever change, this fails
    loudly instead of the delivery builder silently misidentifying rows.
    """
    import lidar_analysis.central_runner as central_runner

    assert research_delivery.RESULT_IDENTITY_FIELDS == central_runner._RESULT_ID_FIELDS
    assert research_delivery.RESULT_UNIQUE_FIELDS == central_runner._RESULT_UNIQUE_FIELDS


# --- V3A: genotype mapping -----------------------------------------------
#
# A dedicated, self-contained fixture rather than reusing `experiment`
# above: genotype tests need a left/right pair for one plot (the existing
# fixture has none) and a genotype_map_path, and keeping this separate
# means these tests can't accidentally affect the 34 tests already built
# on `experiment`.

GENOTYPE_RESULT_ROWS = [
    {
        "experiment": "MeadowFescue_2026",
        "date": "2026_06_01",
        "scan_name": "scan1",
        "scan_number": "",
        "plot": 1,
        "side": "none",
        "target_type": "plot",
        "target_id": "plot_1",
        "points": 100,
        "point_density_m2": 10,
        "stand_topo_per_m": 2,
        "qc_status": "pass",
    },
    {
        "experiment": "MeadowFescue_2026",
        "date": "2026_06_01",
        "scan_name": "scan2_left",
        "scan_number": "",
        "plot": 2,
        "side": "left",
        "target_type": "plot",
        "target_id": "2_plot_2",
        "points": 90,
        "point_density_m2": 9,
        "stand_topo_per_m": 3,
        "qc_status": "pass",
    },
    {
        "experiment": "MeadowFescue_2026",
        "date": "2026_06_01",
        "scan_name": "scan2_right",
        "scan_number": "",
        "plot": 2,
        "side": "right",
        "target_type": "plot",
        "target_id": "1_plot_2",
        "points": 95,
        "point_density_m2": 9.5,
        "stand_topo_per_m": 3,
        "qc_status": "pass",
    },
    {
        "experiment": "MeadowFescue_2026",
        "date": "2026_06_01",
        "scan_name": "scan3",
        "scan_number": "",
        "plot": 3,
        "side": "none",
        "target_type": "plot",
        "target_id": "plot_3",
        "points": 80,
        "point_density_m2": 8,
        "stand_topo_per_m": 4,
        "qc_status": "pass",
    },
    {
        # Plot 99 is deliberately absent from the genotype map.
        "experiment": "MeadowFescue_2026",
        "date": "2026_06_01",
        "scan_name": "scan99",
        "scan_number": "",
        "plot": 99,
        "side": "none",
        "target_type": "plot",
        "target_id": "plot_99",
        "points": 50,
        "point_density_m2": 5,
        "stand_topo_per_m": 1,
        "qc_status": "pass",
    },
]

GENOTYPE_MAP_CSV = (
    "experiment,plot,genotype_id,notes\n"
    "MeadowFescue_2026,1,MF001,\n"
    "MeadowFescue_2026,2,MF017,\n"
    "MeadowFescue_2026,3,MF042,\n"
    "MeadowFescue_2026,42,MF999,not scanned yet\n"  # unused: no result row has plot 42
)


@pytest.fixture
def genotype_experiment(tmp_path: Path):
    raw_root = tmp_path / "raw"
    analysis_root = tmp_path / "analysis"
    delivery_root = tmp_path / "delivery"

    source = raw_root / "2026_06_01" / "source"
    for scan_name in ("scan1", "scan2_left", "scan2_right", "scan3", "scan99"):
        add_source_pair(source, scan_name)

    analysis_date_dir = analysis_root / "2026_06_01"
    write_results(analysis_date_dir / "results.csv", GENOTYPE_RESULT_ROWS)

    genotype_map_path = tmp_path / "genotype_map.csv"
    genotype_map_path.write_text(GENOTYPE_MAP_CSV, encoding="utf-8")

    config = DeliveryConfig(
        experiment="MeadowFescue_2026",
        raw_experiment_root=raw_root,
        analysis_experiment_root=analysis_root,
        delivery_root=delivery_root,
        metrics=("points", "point_density_m2", "stand_topo_per_m"),
        generate_graphs=False,
        genotype_map_path=genotype_map_path,
    )
    return config, raw_root, analysis_root, delivery_root, genotype_map_path


def _combined_rows_by_scan(target: Path) -> dict[str, dict[str, str]]:
    rows = read_rows(target / "summary" / "data" / "combined_results.csv")
    return {row["scan_name"]: row for row in rows}


def test_whole_plot_mapping_propagates_to_combined_results(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_join", write=True).target_dir
    rows = _combined_rows_by_scan(target)
    assert rows["scan1"]["genotype_id"] == "MF001"


def test_left_and_right_rows_get_the_same_genotype(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_side", write=True).target_dir
    rows = _combined_rows_by_scan(target)
    assert rows["scan2_left"]["plot"] == "2"
    assert rows["scan2_right"]["plot"] == "2"
    assert rows["scan2_left"]["side"] == "left"
    assert rows["scan2_right"]["side"] == "right"
    assert rows["scan2_left"]["genotype_id"] == "MF017"
    assert rows["scan2_right"]["genotype_id"] == "MF017"


def test_multiple_plots_get_different_genotypes(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_multi", write=True).target_dir
    rows = _combined_rows_by_scan(target)
    assert rows["scan1"]["genotype_id"] == "MF001"
    assert rows["scan2_left"]["genotype_id"] == "MF017"
    assert rows["scan3"]["genotype_id"] == "MF042"


def test_missing_mapping_keeps_row_with_empty_genotype_and_is_logged(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_missing", write=True).target_dir

    combined = _combined_rows_by_scan(target)
    assert "scan99" in combined  # never dropped
    assert combined["scan99"]["genotype_id"] == ""

    missing = read_rows(target / "summary" / "qc" / "missing_genotype_mapping.csv")
    assert len(missing) == 1
    assert missing[0]["scan_name"] == "scan99"
    assert missing[0]["plot"] == "99"
    assert missing[0]["experiment"] == "MeadowFescue_2026"
    assert missing[0]["date"] == "2026_06_01"


def test_unused_mapping_is_audited_not_an_error(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_unused", write=True).target_dir

    unused = read_rows(target / "summary" / "qc" / "unused_genotype_mappings.csv")
    assert len(unused) == 1
    assert unused[0]["plot"] == "42"
    assert unused[0]["genotype_id"] == "MF999"
    assert unused[0]["notes"] == "not scanned yet"


def test_genotype_map_not_configured_produces_no_genotype_column(experiment) -> None:
    """Backward compatibility: a config with no genotype_map_path must produce
    byte-for-byte the same combined_results.csv shape as before V3A -- no
    genotype_id column appears at all, not an empty one."""
    config, *_ = experiment
    assert config.genotype_map_path is None
    target = build_delivery(config, run_id="no_genotype", write=True).target_dir
    rows = read_rows(target / "summary" / "data" / "combined_results.csv")
    assert rows
    assert "genotype_id" not in rows[0]
    assert not (target / "summary" / "qc" / "missing_genotype_mapping.csv").exists()
    assert not (target / "summary" / "qc" / "unused_genotype_mappings.csv").exists()


def test_wrong_experiment_rows_in_map_do_not_leak_in(tmp_path: Path, genotype_experiment) -> None:
    config, *_rest, genotype_map_path = genotype_experiment
    # Add a row for a different experiment reusing plot 1 with a different
    # genotype; it must never be considered for MeadowFescue_2026's plot 1.
    genotype_map_path.write_text(
        GENOTYPE_MAP_CSV + "OtherTrial,1,OT999,\n", encoding="utf-8"
    )
    target = build_delivery(config, run_id="v3a_isolation", write=True).target_dir
    rows = _combined_rows_by_scan(target)
    assert rows["scan1"]["genotype_id"] == "MF001"


def test_invalid_genotype_map_fails_clearly(genotype_experiment) -> None:
    config, *_rest, genotype_map_path = genotype_experiment
    genotype_map_path.write_text(
        "experiment,plot,genotype_id\nMeadowFescue_2026,1,,\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="genotype_id is blank"):
        build_delivery(config, run_id="v3a_invalid", write=True)


def test_invalid_genotype_map_fails_even_in_dry_run(genotype_experiment) -> None:
    config, *_rest, genotype_map_path = genotype_experiment
    genotype_map_path.write_text(
        "experiment,plot,genotype_id\nMeadowFescue_2026,1,,\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="genotype_id is blank"):
        build_delivery(config, run_id="v3a_invalid_dry", write=False)


def test_missing_genotype_map_path_fails_at_validate(genotype_experiment) -> None:
    config, *_rest, genotype_map_path = genotype_experiment
    config = replace(config, genotype_map_path=genotype_map_path.parent / "nope.csv")
    with pytest.raises(FileNotFoundError, match="genotype_map_path"):
        config.validate()


def test_canonical_results_and_frozen_snapshot_unchanged_by_genotype_join(
    genotype_experiment,
) -> None:
    config, _raw_root, analysis_root, _delivery_root, _map_path = genotype_experiment
    canonical_path = analysis_root / "2026_06_01" / "results.csv"
    before = hashlib.sha256(canonical_path.read_bytes()).hexdigest()

    target = build_delivery(config, run_id="v3a_untouched", write=True).target_dir

    after = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    assert before == after  # canonical source: untouched

    snapshot_path = target / "2026_06_01" / "results" / "results.csv"
    snapshot_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    assert snapshot_hash == before  # frozen snapshot: identical to canonical, no genotype_id added


def test_genotype_map_recorded_in_manifest_with_correct_hash(genotype_experiment) -> None:
    config, _raw_root, _analysis_root, _delivery_root, genotype_map_path = genotype_experiment
    target = build_delivery(config, run_id="v3a_provenance", write=True).target_dir

    manifest = json.loads((target / "manifest" / "delivery_manifest.json").read_text())
    genotype_manifest = manifest["genotype_map"]
    assert genotype_manifest["configured"] is True
    assert genotype_manifest["path"] == str(genotype_map_path.resolve())
    assert genotype_manifest["sha256"] == hashlib.sha256(genotype_map_path.read_bytes()).hexdigest()
    assert genotype_manifest["experiment_rows"] == 4  # plots 1, 2, 3, 42 (42 is unused, still counted)
    assert genotype_manifest["missing_mapping_rows"] == 1  # plot 99
    assert genotype_manifest["unused_mapping_entries"] == 1  # plot 42


def test_genotype_map_not_configured_manifest_says_so(experiment) -> None:
    config, *_ = experiment
    target = build_delivery(config, run_id="v3a_no_map_manifest", write=True).target_dir
    manifest = json.loads((target / "manifest" / "delivery_manifest.json").read_text())
    assert manifest["genotype_map"] == {"configured": False}


def test_overwrite_protection_still_works_with_genotype_configured(genotype_experiment) -> None:
    config, *_ = genotype_experiment
    build_delivery(config, run_id="v3a_overwrite", write=True)
    with pytest.raises(FileExistsError):
        build_delivery(config, run_id="v3a_overwrite", write=True)


def test_genotype_qc_artifacts_are_in_the_layout_contract() -> None:
    from lidar_analysis.research_delivery_layout import (
        MISSING_GENOTYPE_MAPPING_FILE,
        UNUSED_GENOTYPE_MAPPINGS_FILE,
        artifact_role,
    )

    assert artifact_role(MISSING_GENOTYPE_MAPPING_FILE) == "experiment_qc"
    assert artifact_role(UNUSED_GENOTYPE_MAPPINGS_FILE) == "experiment_qc_audit"


def test_genotype_map_artifacts_pass_manifest_artifact_inventory(genotype_experiment) -> None:
    """Every file actually written, including the two new genotype QC CSVs,
    must resolve under the folder contract or build_delivery itself would
    raise -- this just makes that explicit and asserts the two new files
    are actually present and hashed in the manifest's artifact inventory."""
    config, *_ = genotype_experiment
    target = build_delivery(config, run_id="v3a_inventory", write=True).target_dir
    manifest = json.loads((target / "manifest" / "delivery_manifest.json").read_text())
    artifact_paths = {entry["path"] for entry in manifest["artifacts"]}
    assert "summary/qc/missing_genotype_mapping.csv" in artifact_paths
    assert "summary/qc/unused_genotype_mappings.csv" in artifact_paths
