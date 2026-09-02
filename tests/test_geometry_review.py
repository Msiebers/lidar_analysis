from pathlib import Path

import pandas as pd
import pytest
import yaml

from lidar_analysis.geometry_review import build_geometry_review
from lidar_analysis.plant_geometry import compute_plant_geometry_traits
from tests.test_plant_geometry import _op_config, _synthetic_fescue_with_clover


def _review_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    points = _synthetic_fescue_with_clover()
    operation = {
        **_op_config(),
        "center_x_m": 0.0,
        "center_z_m": 0.0,
        "background_ceiling_m": 0.05,
    }
    context = {
        "target_z_min_m": -0.36,
        "target_z_max_m": 0.36,
        "target_center_z_m": 0.0,
    }
    traits, _ = compute_plant_geometry_traits(points, operation, context=context)

    scan_id = "meadow_fixture"
    pointcloud_dir = tmp_path / "pointclouds"
    pointcloud_dir.mkdir()
    points.to_csv(pointcloud_dir / f"37_plant_1_{scan_id}.csv", index=False)

    result = {
        "date": "2026_05_14",
        "scan_id": scan_id,
        "row": 37,
        "plot": "plant_1",
        **context,
        **traits,
    }
    results_path = tmp_path / "results.csv"
    pd.DataFrame([result]).to_csv(results_path, index=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"analysis": {"pointcloud_ops": [operation]}}),
        encoding="utf-8",
    )
    return results_path, pointcloud_dir, config_path


def test_geometry_review_uses_exact_result_context_and_writes_audit(tmp_path):
    results_path, pointcloud_dir, config_path = _review_fixture(tmp_path)

    image_path, audit_path = build_geometry_review(
        results_path=results_path,
        pointcloud_dir=pointcloud_dir,
        config_path=config_path,
        output_dir=tmp_path / "review",
        max_points=2_000,
    )

    assert image_path.is_file()
    assert image_path.stat().st_size > 0
    audit = pd.read_csv(audit_path)
    assert bool(audit.loc[0, "matches_final_result"])
    assert audit.loc[0, "crown_center_z_m"] == pytest.approx(0.0)
    assert audit.loc[0, "crown_center_source"] == "configured"


def test_geometry_review_refuses_stale_result_mismatch(tmp_path):
    results_path, pointcloud_dir, config_path = _review_fixture(tmp_path)
    results = pd.read_csv(results_path)
    results.loc[0, "plant_height_m"] += 0.05
    results.to_csv(results_path, index=False)

    output_dir = tmp_path / "review"
    with pytest.raises(ValueError, match="does not match the final results"):
        build_geometry_review(
            results_path=results_path,
            pointcloud_dir=pointcloud_dir,
            config_path=config_path,
            output_dir=output_dir,
            max_points=2_000,
        )

    assert (output_dir / "results_geometry_review_audit.csv").is_file()
    assert not (output_dir / "results_geometry_review.png").exists()
