import numpy as np
import pandas as pd
import pytest

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.central_runner import append_trait_rows, ensure_results_csv, phenotype_columns
from lidar_analysis.config import AnalysisConfig
from lidar_analysis.plant_geometry import _projection_area, compute_plant_geometry_traits
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops


def _synthetic_fescue_with_clover(*, include_height_agl=True):
    rows = []

    # Low, broad clover-like background carpet.
    for x in np.arange(-0.32, 0.321, 0.025):
        for z in np.arange(-0.32, 0.321, 0.025):
            h = 0.045 + 0.004 * np.sin(8.0 * x) * np.cos(7.0 * z)
            rows.append((x, h, z, 15.0, h))

    # Crown-connected tuft. High returns are concentrated near the crown;
    # lower blade returns spread outward and overlap the clover carpet.
    for angle in np.linspace(0.0, 2.0 * np.pi, 48, endpoint=False):
        for h in np.linspace(0.055, 0.58, 28):
            radius = 0.205 * ((0.58 - h) / 0.525) ** 0.72
            x = radius * np.cos(angle)
            z = 0.80 * radius * np.sin(angle)
            rows.append((x, h, z, 55.0, h))

    # A neighboring tuft lies outside the configured crown radius.
    for h in np.linspace(0.08, 0.46, 24):
        rows.append((0.48, h, 0.0, 52.0, h))

    df = pd.DataFrame(rows, columns=["X", "Y", "Z", "RSSI", "height_agl"])
    df[["X", "Y", "Z", "height_agl"]] *= 1000.0
    if not include_height_agl:
        df = df.drop(columns=["height_agl"])
    return df


def _target(df):
    return AnalysisTarget.from_points(
        target_id="MF2026_R01_P04",
        target_type="plant",
        scan_id="meadow_fescue_fixture",
        points_df=df,
        source_indices=np.arange(len(df), dtype=np.int32),
    )


def _op_config():
    return {
        "op": "plant_geometry_trait",
        "footprint_grid_m": 0.025,
        "profile_grid_m": 0.025,
        "voxel_size_m": 0.025,
        "slice_height_m": 0.025,
        "maximum_crown_radius_m": 0.36,
        "background_inner_radius_m": 0.23,
        "background_outer_radius_m": 0.34,
        "background_margin_m": 0.035,
        "minimum_points_per_footprint_cell": 1,
        "minimum_selected_points": 30,
    }


def test_geometry_separates_tuft_from_low_clover_and_neighbor():
    df = _synthetic_fescue_with_clover()
    traits, diag = compute_plant_geometry_traits(df, _op_config())

    assert 0.50 <= traits["plant_height_m"] <= 0.60
    assert 0.0 < traits["footprint_area_m2"] < 0.20
    assert traits["profile_area_xy_m2"] > 0.0
    assert traits["profile_area_zy_m2"] > 0.0
    assert traits["canopy_envelope_volume_m3"] > 0.0
    assert traits["canopy_occupied_volume_m3"] > 0.0
    assert traits["canopy_envelope_volume_m3"] > traits["canopy_occupied_volume_m3"]
    assert traits["geometry_volume_method"] == "slice_convex_hull_v1"
    assert traits["geometry_footprint_cells"] >= 8
    assert diag["volume_hull_slices"] > 0
    assert diag["background_source"] == "background_annulus"
    assert diag["selected_points"] < diag["input_points"]
    assert abs(diag["crown_center_x_m"]) < 0.05
    assert abs(diag["crown_center_z_m"]) < 0.05


def test_geometry_op_is_non_destructive_and_records_diagnostics():
    df = _synthetic_fescue_with_clover()
    target = _target(df)
    raw_before = target.raw_points.copy(deep=True)

    out = apply_pointcloud_ops(target, [_op_config()])

    pd.testing.assert_frame_equal(out.raw_points, raw_before)
    assert len(out.current_points) == len(df)
    assert "plant_height_m" in out.traits
    assert out.diagnostics["pointcloud_ops"]["operation_order"] == ["plant_geometry_trait"]
    diag = out.diagnostics["pointcloud_ops"]["plant_geometry_trait"][0]
    assert diag["algorithm"] == "crown_connected_projection_v2"
    assert diag["experimental"] is True


def test_dense_returns_in_one_cell_fail_geometry_support_qc():
    n_points = 240
    height_m = np.linspace(0.08, 0.55, n_points)
    df = pd.DataFrame({
        "X": np.linspace(0.002, 0.008, n_points) * 1000.0,
        "Y": height_m * 1000.0,
        "Z": np.linspace(0.002, 0.008, n_points) * 1000.0,
        "RSSI": np.full(n_points, 55.0),
        "height_agl": height_m * 1000.0,
    })
    op = {
        **_op_config(),
        "center_x_m": 0.005,
        "center_z_m": 0.005,
        "background_ceiling_m": 0.05,
    }

    traits, diag = compute_plant_geometry_traits(df, op)

    assert np.isfinite(traits["plant_height_m"])
    assert traits["geometry_selected_points"] == n_points
    assert traits["geometry_footprint_cells"] == 1
    assert traits["geometry_qc_status"] == "fail"
    assert traits["geometry_confidence"] < 0.45
    assert "insufficient_footprint_cells_for_review" in diag["qc_flags"]
    assert "insufficient_height_cells_for_review" in diag["qc_flags"]


def test_five_supported_cells_require_review_instead_of_passing():
    rows = []
    for x_m in (0.005, 0.030, 0.055, 0.080, 0.105):
        for height_m in np.linspace(0.08, 0.50, 50):
            rows.append((x_m, height_m, 0.005, 55.0, height_m))
    df = pd.DataFrame(rows, columns=["X", "Y", "Z", "RSSI", "height_agl"])
    df[["X", "Y", "Z", "height_agl"]] *= 1000.0
    op = {
        **_op_config(),
        "center_x_m": 0.005,
        "center_z_m": 0.005,
        "background_ceiling_m": 0.05,
    }

    traits, diag = compute_plant_geometry_traits(df, op)

    assert traits["geometry_footprint_cells"] == 5
    assert traits["geometry_qc_status"] == "review"
    assert traits["geometry_confidence"] == pytest.approx(0.74)
    assert "few_supported_footprint_cells" in diag["qc_flags"]
    assert "few_supported_height_cells" in diag["qc_flags"]


def test_configured_center_rejects_denser_disconnected_neighbor():
    df = _synthetic_fescue_with_clover()
    distractor = pd.DataFrame({
        "X": np.full(600, 0.30 * 1000.0),
        "Y": np.linspace(0.08, 0.68, 600) * 1000.0,
        "Z": np.zeros(600),
        "RSSI": np.full(600, 60.0),
        "height_agl": np.linspace(0.08, 0.68, 600) * 1000.0,
    })
    df = pd.concat([df, distractor], ignore_index=True)
    op = {
        **_op_config(),
        "center_x_m": 0.0,
        "center_z_m": 0.0,
        "background_ceiling_m": 0.05,
    }

    traits, diag = compute_plant_geometry_traits(df, op)

    assert 0.50 <= traits["plant_height_m"] <= 0.60
    assert diag["crown_center_source"] == "configured"
    assert "weak_background_estimate" not in diag["qc_flags"]


def test_marker_center_z_anchors_geometry_to_the_target_plant():
    df = _synthetic_fescue_with_clover()
    distractor = pd.DataFrame({
        "X": np.zeros(600),
        "Y": np.linspace(0.08, 0.68, 600) * 1000.0,
        "Z": np.full(600, 0.32 * 1000.0),
        "RSSI": np.full(600, 60.0),
        "height_agl": np.linspace(0.08, 0.68, 600) * 1000.0,
    })
    df = pd.concat([df, distractor], ignore_index=True)
    op = {
        **_op_config(),
        "background_ceiling_m": 0.05,
    }

    traits, diag = compute_plant_geometry_traits(
        df,
        op,
        context={"target_center_z_m": 0.0},
    )

    assert 0.50 <= traits["plant_height_m"] <= 0.60
    assert diag["crown_center_z_m"] == pytest.approx(0.0)
    assert diag["crown_center_source"] == "high_point_density_x+marker_center_z"


def test_projection_closing_preserves_boundary_cells():
    axis = np.asarray([0.01, 0.11, 0.21])
    a, b = np.meshgrid(axis, axis, indexing="ij")

    area = _projection_area(a.ravel(), b.ravel(), grid_m=0.10, close_cells=1)

    assert area == pytest.approx(0.09)


def test_geometry_op_adds_ground_height_without_filtering_points():
    df = _synthetic_fescue_with_clover(include_height_agl=False)
    target = _target(df)
    op = _op_config()
    op["ground"] = {
        "x_bin_size_m": 0.05,
        "z_bin_size_m": 0.05,
        "quantile": 0.05,
        "min_points_per_xz_bin": 1,
        "min_x_bins_per_z": 2,
        "smooth_bins": 3,
    }

    out = apply_pointcloud_ops(target, [op])

    assert len(out.current_points) == len(df)
    assert {"ground_Y", "height_agl"}.issubset(out.current_points.columns)
    diag = out.diagnostics["pointcloud_ops"]["plant_geometry_trait"][0]
    assert diag["height_source"] == "height_agl"


def test_empty_geometry_target_returns_explicit_failed_qc():
    df = pd.DataFrame(columns=["X", "Y", "Z", "RSSI", "height_agl"])
    traits, diag = compute_plant_geometry_traits(df, _op_config())

    assert np.isnan(traits["plant_height_m"])
    assert traits["geometry_confidence"] == 0.0
    assert traits["geometry_qc_status"] == "fail"
    assert traits["geometry_qc_flags"] == "empty_target"
    assert traits["geometry_volume_method"] == "slice_convex_hull_v1"
    assert diag["qc_flags"] == ["empty_target"]


def test_invalid_geometry_resolution_fails_clearly():
    with pytest.raises(ValueError, match="footprint_grid_m must be > 0"):
        compute_plant_geometry_traits(
            _synthetic_fescue_with_clover(),
            {**_op_config(), "footprint_grid_m": 0.0},
        )

    with pytest.raises(ValueError, match="slice_envelope_method"):
        compute_plant_geometry_traits(
            _synthetic_fescue_with_clover(),
            {**_op_config(), "slice_envelope_method": "not_a_method"},
        )


def test_geometry_result_columns_only_appear_when_op_enabled():
    base = AnalysisConfig(data_dirs=[], calibration_dir=".", cart_id="CART")
    assert "plant_height_m" not in phenotype_columns(base)

    base.pointcloud_ops = [{"op": "plant_geometry_trait"}]
    cols = phenotype_columns(base)
    assert "plant_height_m" in cols
    assert "profile_area_xy_m2" in cols
    assert "canopy_envelope_volume_m3" in cols
    assert "geometry_qc_status" in cols
    assert "geometry_footprint_cells" in cols
    assert "geometry_qc_flags" in cols
    assert "geometry_volume_method" in cols
    assert "target_center_z_m" in cols


def test_geometry_result_csv_preserves_support_and_exact_marker_center(tmp_path):
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=".", cart_id="CART")
    cfg.pointcloud_ops = [{"op": "plant_geometry_trait"}]
    results_csv = tmp_path / "results.csv"
    ensure_results_csv(results_csv, cfg)

    append_trait_rows(
        results_csv,
        "MeadowFescue_2026",
        "2026_05_14",
        "scan_1",
        [{
            "row": "37",
            "plot": "plant_2",
            "z_min_m": 1.10,
            "z_max_m": 1.48,
            "target_center_z_m": 1.31,
            "geometry_selected_points": 118,
            "geometry_footprint_cells": 1,
            "geometry_height_cells": 1,
            "geometry_boundary_fraction": 0.0,
            "geometry_qc_flags": "insufficient_footprint_cells_for_review",
            "geometry_volume_method": "slice_convex_hull_v1",
        }],
        cfg,
    )

    row = pd.read_csv(results_csv).iloc[0]
    assert row["target_z_min_m"] == pytest.approx(1.10)
    assert row["target_z_max_m"] == pytest.approx(1.48)
    assert row["target_center_z_m"] == pytest.approx(1.31)
    assert row["geometry_footprint_cells"] == 1
    assert row["geometry_qc_flags"] == "insufficient_footprint_cells_for_review"
