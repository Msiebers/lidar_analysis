import pandas as pd
import pytest

from lidar_analysis.mark_splitting import build_mark_segments


def _write_markers(path, encoder_counts, target_type="plot"):
    pd.DataFrame(
        {
            "marker_idx": list(range(1, len(encoder_counts) + 1)),
            "target_type": [target_type] * len(encoder_counts),
            "target_number": [""] * len(encoder_counts),
            "mark_role": ["boundary"] * len(encoder_counts),
            "encoder_count": encoder_counts,
        }
    ).to_csv(path, index=False)


def test_plot_marker_pair_gets_inward_buffer_forward_order(tmp_path, capsys):
    marker_path = tmp_path / "scan_markers.csv"
    _write_markers(marker_path, [1000, 2000])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=100.0,
        target_type="plot",
    )

    assert len(segments) == 1
    assert segments[0].target_number == "1"
    assert segments[0].min_z == 1100.0
    assert segments[0].max_z == 1900.0
    assert "[MARKS] plot 1: raw=1000.0->2000.0 buffered=1100.0->1900.0 buffer=100.0" in capsys.readouterr().out


def test_plot_marker_pair_gets_inward_buffer_reversed_order(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_markers(marker_path, [2000, 1000])

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=100.0,
        target_type="plot",
    )

    assert len(segments) == 1
    assert segments[0].min_z == 1100.0
    assert segments[0].max_z == 1900.0


def test_plot_markers_are_paired_in_file_order_into_windows(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    counts = []
    for i in range(7):
        counts.extend([1000 + i * 1000, 1500 + i * 1000])
    _write_markers(marker_path, counts)

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=50.0,
        target_type="plot",
    )

    assert len(segments) == 7
    assert [s.target_number for s in segments] == [str(i) for i in range(1, 8)]
    assert [(s.min_z, s.max_z) for s in segments] == [
        (1050.0 + i * 1000, 1450.0 + i * 1000) for i in range(7)
    ]


def test_free_boundary_markers_are_paired_in_plot_mode_without_extra_toggle(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    counts = []
    for i in range(7):
        counts.extend([1000 + i * 1000, 1500 + i * 1000])
    _write_markers(marker_path, counts, target_type="free")

    segments = build_mark_segments(
        marker_path,
        step_mm=1.0,
        lidar_wheel_offset_mm=0.0,
        z_buffer_mm=50.0,
        target_type="plot",
    )

    assert len(segments) == 7
    assert [s.target_type for s in segments] == ["plot"] * 7
    assert [(s.min_z, s.max_z) for s in segments] == [
        (1050.0 + i * 1000, 1450.0 + i * 1000) for i in range(7)
    ]


def test_plot_marker_pair_invalid_after_inward_buffer_raises_clear_error(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_markers(marker_path, [1000, 1100])

    with pytest.raises(ValueError, match="Invalid buffered plot marker segment"):
        build_mark_segments(
            marker_path,
            step_mm=1.0,
            lidar_wheel_offset_mm=0.0,
            z_buffer_mm=100.0,
            target_type="plot",
        )


def test_plot_marker_odd_boundary_count_raises_clear_error(tmp_path):
    marker_path = tmp_path / "scan_markers.csv"
    _write_markers(marker_path, [1000, 2000, 3000])

    with pytest.raises(ValueError, match="requires an even number of plot boundary marks"):
        build_mark_segments(
            marker_path,
            step_mm=1.0,
            lidar_wheel_offset_mm=0.0,
            z_buffer_mm=100.0,
            target_type="plot",
        )
