from pathlib import Path

import pandas as pd
import pytest

from lidar_analysis.mark_splitting import build_mark_segments


def _write_centers(path: Path, centers: list[tuple[int, int, int]]) -> Path:
    rows = [
        {
            "marker_idx": marker_idx,
            "target_type": "plant",
            "target_number": target_number,
            "mark_role": "center",
            "encoder_count": encoder_count,
        }
        for marker_idx, target_number, encoder_count in centers
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_midpoint_windows_partition_irregular_plant_spacing(tmp_path):
    marker_path = _write_centers(
        tmp_path / "scan_marker.csv",
        [(1, 1, 100), (2, 2, 200), (3, 3, 320)],
    )

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=80.0,
        target_type="plant",
        plant_window_mode="midpoint",
    )

    assert [s.target_number for s in segments] == ["1", "2", "3"]
    assert [(s.min_z, s.max_z) for s in segments] == [
        (50.0, 150.0),
        (150.0, 260.0),
        (260.0, 380.0),
    ]
    assert [s.center_z for s in segments] == [100.0, 200.0, 320.0]


def test_midpoint_windows_are_direction_independent_and_buffer_is_a_cap(tmp_path):
    marker_path = _write_centers(
        tmp_path / "reverse_marker.csv",
        [(1, 3, 320), (2, 2, 200), (3, 1, 100)],
    )

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=40.0,
        target_type="plant",
        plant_window_mode="midpoint",
    )

    assert [s.target_number for s in segments] == ["1", "2", "3"]
    assert [(s.min_z, s.max_z) for s in segments] == [
        (60.0, 140.0),
        (160.0, 240.0),
        (280.0, 360.0),
    ]


def test_fixed_center_windows_keep_existing_behavior(tmp_path):
    marker_path = _write_centers(
        tmp_path / "fixed_marker.csv",
        [(1, 1, 100), (2, 2, 140)],
    )

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=30.0,
        target_type="plant",
        plant_window_mode="fixed",
    )

    assert [(s.min_z, s.max_z) for s in segments] == [
        (70.0, 130.0),
        (110.0, 170.0),
    ]


def test_midpoint_windows_reject_duplicate_positions(tmp_path):
    marker_path = _write_centers(
        tmp_path / "duplicate_marker.csv",
        [(1, 1, 100), (2, 2, 100)],
    )

    with pytest.raises(ValueError, match="distinct encoder positions"):
        build_mark_segments(
            marker_path,
            step_mm=1.0,
            lidar_wheel_offset_mm=0.0,
            z_buffer_mm=50.0,
            target_type="plant",
            plant_window_mode="midpoint",
        )
