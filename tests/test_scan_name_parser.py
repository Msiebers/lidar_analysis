from pathlib import Path
import csv

import numpy as np

from lidar_analysis.central_runner import append_trait_rows, ensure_results_csv, phenotype_columns
from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pipeline_core import (
    Plot,
    _apply_forced_two_sided_targets,
    _filter_fused_indices_for_plot_side,
    analyze_plot,
    parse_scan_name,
)


def test_parse_bare_single_target_names():
    for name in ["1", "control", "test", "2b5"]:
        parsed = parse_scan_name(name)
        assert parsed["rows"] == [name]
        assert parsed["plot_numbers"] == [1]
        assert parsed["is_two_row"] is False
        assert parsed["is_single_plot"] is True


def test_parse_single_target_numeric_suffixes():
    assert parse_scan_name("1_7")["rows"] == ["1"]
    assert parse_scan_name("1_7")["plot_numbers"] == [7]
    assert parse_scan_name("control_7")["rows"] == ["control"]
    assert parse_scan_name("control_7")["plot_numbers"] == [7]
    assert parse_scan_name("1_1_20")["plot_numbers"] == list(range(1, 21))
    assert parse_scan_name("test_1_20")["plot_numbers"] == list(range(1, 21))
    assert parse_scan_name("2b5_1_20")["plot_numbers"] == list(range(1, 21))


def test_parse_two_sided_names():
    cases = {
        "1&2": (["1", "2"], [1]),
        "1&2_7": (["1", "2"], [7]),
        "1&2_1_20": (["1", "2"], list(range(1, 21))),
        "2&1_20_1": (["2", "1"], list(range(20, 0, -1))),
        "control&test": (["control", "test"], [1]),
        "2b5&1control": (["2b5", "1control"], [1]),
        "control&test_1_20": (["control", "test"], list(range(1, 21))),
    }

    for name, (rows, plot_numbers) in cases.items():
        parsed = parse_scan_name(name)
        assert parsed["rows"] == rows
        assert parsed["plot_numbers"] == plot_numbers
        assert parsed["is_two_row"] is True


def test_force_two_sided_targets_adds_left_right_for_single_target_scan(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        force_two_sided_targets=True,
    )
    plot = Plot('2', '1', (0.0, 1000.0), out_dir=str(tmp_path), scan_base='2_1')

    plots = _apply_forced_two_sided_targets([plot], '2_1', cfg)

    assert [p.side_label for p in plots] == ['left', 'right']
    assert [p.side_sign for p in plots] == ['positive', 'negative']
    assert [Path(p.csv_out).name for p in plots] == ['2_1_left.csv', '2_1_right.csv']


def test_force_two_sided_targets_does_not_duplicate_ampersand_scan(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        force_two_sided_targets=True,
    )
    plot = Plot('1', '1', (0.0, 1000.0), out_dir=str(tmp_path), scan_base='1&2')

    assert _apply_forced_two_sided_targets([plot], '1&2', cfg) == [plot]


def test_side_ray_selection_uses_left_positive_x_right_negative_x():
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=Path('.'), cart_id='CART')
    fused_np = np.array([
        [0.0, 0.0, np.pi / 2.0, 1000.0, 1.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -np.pi / 2.0, 1000.0, 1.0, 1.0, 0.0, 0.0, 0.0],
    ], dtype=np.float32)
    idx = np.array([0, 1], dtype=np.int32)
    left = Plot('target', '1', (0.0, 1000.0), out_dir='.', scan_base='target_1')
    left.side_sign = 'positive'
    right = Plot('target', '1', (0.0, 1000.0), out_dir='.', scan_base='target_1')
    right.side_sign = 'negative'

    left_idx = _filter_fused_indices_for_plot_side(fused_np, idx, left, cfg, ['target', 'target'], 1000.0, 1000.0, 0.0, 0.0)
    right_idx = _filter_fused_indices_for_plot_side(fused_np, idx, right, cfg, ['target', 'target'], 1000.0, 1000.0, 0.0, 0.0)

    assert left_idx.tolist() == [0]
    assert right_idx.tolist() == [1]


def test_forced_two_sided_topology_outputs_side_neutral_rows(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        force_two_sided_targets=True,
        pointcloud_ops=[{"op": "topology_trait", "split_sides_for_single_plot": True}],
    )
    plot = Plot('2', '1', (0.0, 1000.0), out_dir=str(tmp_path), scan_base='2_1')
    plots = _apply_forced_two_sided_targets([plot], '2_1', cfg)
    data = np.array([
        [20.0, 100.0, 100.0, 1.0],
        [20.0, 100.0, 300.0, 2.0],
        [-20.0, 100.0, 100.0, 3.0],
        [-20.0, 100.0, 300.0, 4.0],
    ], dtype=np.float32)
    keep_idx = np.arange(data.shape[0], dtype=np.int32)
    fused_np = np.zeros((data.shape[0], 9), dtype=np.float32)

    records = [
        analyze_plot(
            p, data, keep_idx, fused_np, '2_1', cfg, ['2', '2'],
            lidar_height_mm=1000.0, step_mm=1.0,
        )
        for p in plots
    ]

    cols = phenotype_columns(cfg)
    assert "stand_topo_count" in cols
    assert "stand_topo_per_m" in cols
    assert "stand_topo_left_count" not in cols
    assert "stand_topo_right_count" not in cols

    assert [r["scan"] for r in records] == ["2_1_left", "2_1_right"]
    assert [r["row"] for r in records] == ["2", "2"]
    assert [r["side"] for r in records] == ["left", "right"]
    for rec in records:
        assert np.isfinite(float(rec["stand_topo_count"]))
        assert np.isfinite(float(rec["stand_topo_per_m"]))
        assert np.isnan(float(rec["stand_topo_left_count"]))
        assert np.isnan(float(rec["stand_topo_right_count"]))


def test_internal_topology_side_split_columns_stay_for_unsplit_workflow():
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        pointcloud_ops=[{"op": "topology_trait", "split_sides_for_single_plot": True}],
    )

    cols = phenotype_columns(cfg)

    assert "stand_topo_count" in cols
    assert "stand_topo_per_m" in cols
    assert "stand_topo_left_count" in cols
    assert "stand_topo_right_count" in cols
    assert "stand_topo_left_per_m" in cols
    assert "stand_topo_right_per_m" in cols


def _manual_voxel_count(points, voxel_size_m):
    xyz_m = np.asarray(points, dtype=float)[:, :3] / 1000.0
    if xyz_m.shape[0] == 0:
        return 0
    return int(np.unique(np.floor(xyz_m / float(voxel_size_m)).astype(np.int64), axis=0).shape[0])


def test_forced_two_sided_voxel_count_uses_side_specific_cloud(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        force_two_sided_targets=True,
        pointcloud_ops=[{"op": "voxel_count", "voxel_size_m": 0.05}],
    )
    plot = Plot('5', '1', (0.0, 1000.0), out_dir=str(tmp_path), scan_base='5_1')
    left, right = _apply_forced_two_sided_targets([plot], '5_1', cfg)
    data = np.array([
        [20.0, 100.0, 100.0, 1.0],
        [20.0, 100.0, 120.0, 2.0],
        [-20.0, 100.0, 100.0, 3.0],
        [-80.0, 100.0, 100.0, 4.0],
        [-140.0, 100.0, 100.0, 5.0],
    ], dtype=np.float32)
    keep_idx = np.arange(data.shape[0], dtype=np.int32)
    fused_np = np.zeros((data.shape[0], 9), dtype=np.float32)

    left_rec = analyze_plot(left, data, keep_idx, fused_np, '5_1', cfg, ['5', '5'], 1000.0, 1.0)
    right_rec = analyze_plot(right, data, keep_idx, fused_np, '5_1', cfg, ['5', '5'], 1000.0, 1.0)

    assert left_rec["points"] == 2
    assert right_rec["points"] == 3
    assert left_rec["voxel_count"] == _manual_voxel_count(left.cloud, 0.05)
    assert right_rec["voxel_count"] == _manual_voxel_count(right.cloud, 0.05)
    assert left_rec["voxel_count"] != _manual_voxel_count(data, 0.05)
    assert right_rec["voxel_count"] != _manual_voxel_count(data, 0.05)


def test_voxel_count_after_filter_uses_filtered_side_cloud(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir=Path('.'),
        cart_id='CART',
        force_two_sided_targets=True,
        pointcloud_ops=[
            {"op": "voxel_count", "voxel_size_m": 0.05},
            {"op": "height_range_filter", "axis": "Y", "min_m": 0.15},
        ],
    )
    plot = Plot('5', '1', (0.0, 1000.0), out_dir=str(tmp_path), scan_base='5_1')
    left, right = _apply_forced_two_sided_targets([plot], '5_1', cfg)
    data = np.array([
        [20.0, 100.0, 100.0, 1.0],
        [20.0, 200.0, 200.0, 2.0],
        [-20.0, 200.0, 100.0, 3.0],
    ], dtype=np.float32)
    keep_idx = np.arange(data.shape[0], dtype=np.int32)
    fused_np = np.zeros((data.shape[0], 9), dtype=np.float32)

    left_rec = analyze_plot(left, data, keep_idx, fused_np, '5_1', cfg, ['5', '5'], 1000.0, 1.0)
    right_rec = analyze_plot(right, data, keep_idx, fused_np, '5_1', cfg, ['5', '5'], 1000.0, 1.0)

    assert left_rec["points"] == left_rec["voxel_input_points"] == 1
    assert right_rec["points"] == right_rec["voxel_input_points"] == 1
    assert left_rec["voxel_count"] == _manual_voxel_count(left.cloud, 0.05) == 1
    assert right_rec["voxel_count"] == _manual_voxel_count(right.cloud, 0.05) == 1
    assert left_rec["voxel_input_min_x"] >= 0.0
    assert right_rec["voxel_input_max_x"] < 0.0
    assert left_rec["voxel_size_m"] == right_rec["voxel_size_m"] == 0.05

    results_csv = tmp_path / "results.csv"
    ensure_results_csv(results_csv, cfg)
    append_trait_rows(results_csv, "board", "2026_08_24", "5_1", [left_rec, right_rec], cfg)
    with open(results_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert [int(row["points"]) for row in rows] == [1, 1]
    assert [int(row["voxel_input_points"]) for row in rows] == [1, 1]
    assert float(rows[0]["voxel_input_min_x"]) >= 0.0
    assert float(rows[1]["voxel_input_max_x"]) < 0.0
