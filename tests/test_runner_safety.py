from pathlib import Path

import pytest

from lidar_analysis.central_runner import select_scan_pairs, validate_generated_paths


def test_scan_selection_preserves_requested_order_and_rejects_missing(tmp_path):
    pairs = [
        ("scan_a", tmp_path / "a_lidar.csv", tmp_path / "a_pico.csv"),
        ("scan_b", tmp_path / "b_lidar.csv", tmp_path / "b_pico.csv"),
    ]

    selected = select_scan_pairs(pairs, ["scan_b", "scan_a", "scan_b"])

    assert [pair[0] for pair in selected] == ["scan_b", "scan_a"]
    with pytest.raises(ValueError, match="not found"):
        select_scan_pairs(pairs, ["scan_missing"])


def test_generated_paths_must_be_outside_input_tree(tmp_path):
    input_dir = tmp_path / "raw" / "date"
    input_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="Refusing to write"):
        validate_generated_paths(
            input_dir,
            input_dir / "working",
            tmp_path / "analysis" / "output",
        )
    with pytest.raises(ValueError, match="Refusing to write"):
        validate_generated_paths(
            input_dir,
            tmp_path / "analysis" / "working",
            input_dir,
        )

    validate_generated_paths(
        input_dir,
        tmp_path / "analysis" / "working",
        tmp_path / "analysis" / "output",
    )
