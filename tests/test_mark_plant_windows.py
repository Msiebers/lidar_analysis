import pandas as pd

from lidar_analysis.mark_splitting import (
    build_mark_segments,
    plant_window_offsets_mm,
)


def _write_plant_markers(path, encoder_counts, roles):
    pd.DataFrame(
        {
            "marker_idx": list(range(1, len(encoder_counts) + 1)),
            "target_type": ["plant"] * len(encoder_counts),
            "target_number": ["1"] * len(encoder_counts),
            "mark_role": roles,
            "encoder_count": encoder_counts,
        }
    ).to_csv(path, index=False)


def test_plant_center_offsets_override_symmetric_buffer(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_plant_markers(marker_path, [1000], ["center"])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=250.0,
        plant_window_offsets_mm=plant_window_offsets_mm([0.0, 0.5], "m"),
        target_type="plant",
    )

    assert len(segments) == 1
    assert (segments[0].min_z, segments[0].max_z) == (1000.0, 1500.0)


def test_plant_center_without_offsets_keeps_symmetric_buffer(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_plant_markers(marker_path, [1000], ["center"])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=250.0,
        target_type="plant",
    )

    assert (segments[0].min_z, segments[0].max_z) == (750.0, 1250.0)


def test_plant_center_offsets_are_clipped_to_scan_bounds(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_plant_markers(marker_path, [100], ["center"])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=0.0,
        plant_window_offsets_mm=(-250.0, 250.0),
        target_type="plant",
        zmax_clip=300.0,
    )

    assert (segments[0].min_z, segments[0].max_z) == (0.0, 300.0)


def test_explicit_plant_boundaries_keep_using_inward_buffer(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_plant_markers(marker_path, [1000, 2000], ["start", "stop"])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=100.0,
        plant_window_offsets_mm=(0.0, 500.0),
        target_type="plant",
    )

    assert (segments[0].min_z, segments[0].max_z) == (1100.0, 1900.0)
