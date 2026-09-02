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


RESULT_FIELDS = [
    "experiment",
    "date",
    "scan_id",
    "row",
    "plot",
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


def add_source_pair(source: Path, scan_id: str) -> None:
    source.mkdir(parents=True, exist_ok=True)
    (source / f"{scan_id}_lidar.csv").write_text("time,distance\n0,1\n", encoding="utf-8")
    (source / f"{scan_id}_pico.csv").write_text("time,encoder\n0,1\n", encoding="utf-8")


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
            "scan_id": "scan14a",
            "row": 1,
            "plot": 1,
            "points": 10,
            "point_density_m2": 100,
            "stand_topo_per_m": 2,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_14",
            "scan_id": "scan14b",
            "row": 1,
            "plot": 2,
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
    for scan_id in ("scan28a", "scan28b", "scan28c", "scan28d", "scan28e"):
        add_source_pair(may28_source, scan_id)
    (may28_source / "experiment_config.yaml").write_text(
        "analysis:\n  voxel_size: 0.02\n", encoding="utf-8"
    )
    may28_rows = [
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_id": "scan28a",
            "row": 1,
            "plot": 1,
            "points": 100,
            "point_density_m2": 10,
            "stand_topo_per_m": 2,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_id": "scan28b",
            "row": 1,
            "plot": 2,
            "points": 100,
            "point_density_m2": 20,
            "stand_topo_per_m": 3,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_id": "scan28c",
            "row": 1,
            "plot": 3,
            "points": 80,
            "point_density_m2": 500,
            "stand_topo_per_m": 4,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_id": "scan28d",
            "row": 1,
            "plot": 4,
            "points": 70,
            "point_density_m2": 40,
            "stand_topo_per_m": 10,
            "qc_status": "pass",
        },
        {
            "experiment": "MeadowFescue_2026",
            "date": "2026_05_28",
            "scan_id": "scan28e",
            "row": 1,
            "plot": 5,
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
    assert (target / "2026_05_27" / "metadata" / "date_status.json").is_file()
    assert not (target / "2026_05_27" / "results" / "results.csv").exists()

    points = read_rows(
        target / "2026_05_28" / "results" / "top_15_percent" / "points.csv"
    )
    assert [row["plot"] for row in points] == ["1", "2"]
    assert {row["_ranking_value"] for row in points} == {"100.0"}

    density = read_rows(
        target
        / "2026_05_28"
        / "results"
        / "top_15_percent"
        / "point_density_m2.csv"
    )
    assert [row["plot"] for row in density] == ["3"]
    assert all(row["plot"] != "5" for row in density)

    latest_points = read_rows(
        target / "summary" / "latest_date_top_15_percent" / "points.csv"
    )
    assert latest_points == points

    date_index = {row["date"]: row for row in read_rows(target / "summary" / "experiment_date_index.csv")}
    assert date_index["2026_05_27"]["status"] == "incomplete"
    assert date_index["2026_05_28"]["status"] == "usable"

    summary = (target / "summary" / "EXPERIMENT_SUMMARY.md").read_text(encoding="utf-8")
    assert "TEST PREVIEW" in summary
    assert "Per-date algorithm enable/disable differences are not acceptable" in summary
    assert "inconsistent" in summary

    assert not list((target / "2026_05_28" / "pointclouds").glob("plot_*.csv"))
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
    usable_dates = ("2026_05_14", "2026_05_28")
    expected = {
        f"{date}/results/graphs/{metric}_{suffix}.png"
        for date in usable_dates
        for metric in metrics
        for suffix in ("distribution", "top_15_percent")
    }
    expected.update(f"summary/graphs/{metric}_by_date.png" for metric in metrics)
    expected.update(
        f"summary/latest_date_top_15_percent/graphs/{metric}.png"
        for metric in metrics
    )

    graph_paths = sorted(path for path in target.rglob("*.png"))
    graph_files = [str(path.relative_to(target)) for path in graph_paths]
    assert len(graph_files) == 18
    assert set(graph_files) == expected
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in graph_paths)
    assert not (target / "2026_05_27" / "results" / "graphs").exists()
    assert not (target / ".matplotlib-cache").exists()

    for metric in metrics:
        source = target / "2026_05_28" / "results" / "graphs" / (
            f"{metric}_top_15_percent.png"
        )
        latest = (
            target
            / "summary"
            / "latest_date_top_15_percent"
            / "graphs"
            / f"{metric}.png"
        )
        assert source.read_bytes() == latest.read_bytes()

    points_ranking = read_rows(
        target / "2026_05_28" / "results" / "top_15_percent" / "points.csv"
    )
    points_graph = (
        target
        / "2026_05_28"
        / "results"
        / "graphs"
        / "points_top_15_percent.png"
    ).read_bytes()
    assert {row["_ranking_cutoff"] for row in points_ranking} == {"100.0"}
    assert b"selected=2, eligible=4, cutoff=100" in points_graph

    manifest = json.loads((target / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert manifest["graphs_generated"] is True
    assert manifest["graph_files"] == sorted(expected)
    assert manifest["graph_files"] == sorted(manifest["graph_files"])

    for metric in metrics:
        summary_graph = target / "summary" / "graphs" / f"{metric}_by_date.png"
        assert b"EXPLORATORY ONLY" in summary_graph.read_bytes()


def test_graph_disabled_mode_preserves_non_graph_outputs(
    experiment: tuple[DeliveryConfig, Path, Path, Path],
) -> None:
    config, _raw_root, _analysis_root, _delivery_root = experiment

    result = build_delivery(config, run_id="preview_graphs_disabled", write=True)

    assert not list(result.target_dir.rglob("*.png"))
    assert (
        result.target_dir
        / "2026_05_28"
        / "results"
        / "top_15_percent"
        / "points.csv"
    ).is_file()
    manifest = json.loads(
        (result.target_dir / "delivery_manifest.json").read_text(encoding="utf-8")
    )
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
