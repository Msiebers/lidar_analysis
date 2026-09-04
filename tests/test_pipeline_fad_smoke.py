from pathlib import Path
import math

import numpy as np
import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.mark_splitting import build_mark_segments
from lidar_analysis.pipeline_core import (
    Plot,
    _apply_additional_scan_side_split,
    _fad_x_bounds_for_plot,
    _filter_fused_indices_for_plot_side,
    analyze_plot,
    build_plot_objects_from_mark_segments,
    reconstruct_world_points,
    reconstruct_world_rays,
)


def _cfg() -> AnalysisConfig:
    return AnalysisConfig(data_dirs=[], calibration_dir=Path("."), cart_id="CART")


def test_fad_world_rays_match_reconstructed_point_frame():
    cfg = _cfg()
    fused_np = np.array(
        [
            [0.0, 0.0, math.pi / 2.0, 1000.0, 1.0, 2.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )

    points_mm, _ = reconstruct_world_points(
        fused_np,
        cfg,
        step_mm=500.0,
        lidar_height_mm=2000.0,
        roll_offset=0.0,
        pitch_offset=0.0,
    )
    origins_m, directions_m = reconstruct_world_rays(
        fused_np,
        cfg,
        step_mm=500.0,
        lidar_height_mm=2000.0,
        roll_offset=0.0,
        pitch_offset=0.0,
    )

    reconstructed_from_ray_m = origins_m[0] + directions_m[0]
    np.testing.assert_allclose(reconstructed_from_ray_m, points_mm[0, :3] / 1000.0, atol=1e-6)


def test_fad_x_bounds_follow_plot_side_logic():
    row_width_m = 1.5
    left_plot = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    right_plot = Plot("right", "A", (0.0, 1000.0), out_dir=".")
    single_plot = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    positive_side = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    positive_side.side_sign = "positive"
    negative_side = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    negative_side.side_sign = "negative"

    assert _fad_x_bounds_for_plot(left_plot, ["left", "right"], row_width_m) == pytest.approx((0.0, 1.5))
    assert _fad_x_bounds_for_plot(right_plot, ["left", "right"], row_width_m) == pytest.approx((-1.5, 0.0))
    assert _fad_x_bounds_for_plot(single_plot, ["left", "left"], row_width_m) == pytest.approx((-1.5, 1.5))
    assert _fad_x_bounds_for_plot(positive_side, ["left", "left"], row_width_m) == pytest.approx((0.0, 1.5))
    assert _fad_x_bounds_for_plot(negative_side, ["left", "left"], row_width_m) == pytest.approx((-1.5, 0.0))
    assert _fad_x_bounds_for_plot(positive_side, ["left", "left"], row_width_m, 0.2) == pytest.approx((0.2, 1.5))
    assert _fad_x_bounds_for_plot(negative_side, ["left", "left"], row_width_m, 0.2) == pytest.approx((-1.5, -0.2))


def test_additional_scan_config_keeps_pointcloud_lai_and_fad_on_same_x_half(tmp_path):
    cfg = _cfg()
    cfg.additional_scan_side_split = True
    cfg.additional_scan_positive_side_label = "right"
    cfg.additional_scan_negative_side_label = "left"
    base = Plot("scan", "1", (0.0, 20.0), out_dir=str(tmp_path), scan_base="scan_001")

    right, left = _apply_additional_scan_side_split([base], "scan_001", cfg)

    assert (right.side_label, right.side_sign) == ("right", "positive")
    assert (left.side_label, left.side_sign) == ("left", "negative")
    assert _fad_x_bounds_for_plot(right, ["scan", "scan"], 1.5, 0.2) == pytest.approx((0.2, 1.5))
    assert _fad_x_bounds_for_plot(left, ["scan", "scan"], 1.5, 0.2) == pytest.approx((-1.5, -0.2))

    fused = np.array([
        [0.0, 0.0, np.pi / 2.0, 500.0, 1.0, 10.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -np.pi / 2.0, 500.0, 1.0, 10.0, 0.0, 0.0, 0.0],
    ], dtype=np.float32)
    idx = np.array([0, 1], dtype=np.int32)
    assert _filter_fused_indices_for_plot_side(fused, idx, right, cfg, ["scan", "scan"], 1.0, 1000.0, 0.0, 0.0).tolist() == [0]
    assert _filter_fused_indices_for_plot_side(fused, idx, left, cfg, ["scan", "scan"], 1.0, 1000.0, 0.0, 0.0).tolist() == [1]

    data = np.array([[500.0, 100.0, 10.0, 1.0], [-500.0, 100.0, 10.0, 1.0]], dtype=np.float32)
    right_row = analyze_plot(right, data, idx, fused, "scan_001", cfg, ["scan", "scan"], 1000.0, 1.0)
    left_row = analyze_plot(left, data, idx, fused, "scan_001", cfg, ["scan", "scan"], 1000.0, 1.0)
    assert (right_row["row"], right_row["side"], right_row["points"]) == ("scan", "right", 1)
    assert (left_row["row"], left_row["side"], left_row["points"]) == ("scan", "left", 1)


@pytest.mark.parametrize(
    ("counts", "expected_intervals"),
    [([0, 100], [(10.0, 90.0)]), ([0, 100, 200, 300], [(10.0, 90.0), (210.0, 290.0)])],
)
def test_additional_plot_mark_pairs_each_split_into_two_x_sides(
    tmp_path, counts, expected_intervals
):
    cfg = _cfg()
    cfg.additional_scan_side_split = True
    cfg.additional_scan_positive_side_label = "right"
    cfg.additional_scan_negative_side_label = "left"
    marker_path = tmp_path / "scan_007_marker.csv"
    rows = "".join(
        f"{index},free,,mark,{count}\n"
        for index, count in enumerate(counts, start=1)
    )
    marker_path.write_text(
        "marker_idx,target_type,target_number,mark_role,encoder_count\n" + rows,
        encoding="utf-8",
    )
    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=10.0,
        target_type="plot",
    )
    plots, _ = build_plot_objects_from_mark_segments("scan_007", segments, str(tmp_path))

    targets = _apply_additional_scan_side_split(plots, "scan_007", cfg)

    assert [(segment.min_z, segment.max_z) for segment in segments] == expected_intervals
    assert len(targets) == len(expected_intervals) * 2
    for index, interval in enumerate(expected_intervals):
        right, left = targets[index * 2:index * 2 + 2]
        assert (right.side_label, right.side_sign, right.letter) == ("right", "positive", str(index + 1))
        assert (left.side_label, left.side_sign, left.letter) == ("left", "negative", str(index + 1))
        assert (right.min_z, right.max_z) == (left.min_z, left.max_z) == interval
        assert _fad_x_bounds_for_plot(right, ["scan", "scan"], 1.5) == (0.0, 1.5)
        assert _fad_x_bounds_for_plot(left, ["scan", "scan"], 1.5) == (-1.5, 0.0)
