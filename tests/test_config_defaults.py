import pytest

from lidar_analysis.config import default_analysis_yaml_dict, normalize_rssi_mode, normalize_rssi_transform
from lidar_analysis.scaffold_experiments import default_experiment_config

def test_default_config_from_single_source():
    exp = default_experiment_config('exp1')
    assert exp['analysis'] == default_analysis_yaml_dict()

def test_rssi_modes_restricted():
    assert normalize_rssi_mode('zscore') == 'zscore'
    assert normalize_rssi_mode('percentile') == 'percentile'
    assert normalize_rssi_transform('sqrt') == 'sqrt'
    assert normalize_rssi_transform('log') == 'log1p'
    assert normalize_rssi_transform('exp') == 'exponential'
    assert default_analysis_yaml_dict()["rssi_norm_transform"] == "sqrt"
    import pytest
    with pytest.raises(ValueError, match="rssi_norm_transform"):
        normalize_rssi_transform('cube')


def test_fad_config_defaults_present():
    analysis = default_analysis_yaml_dict()

    assert analysis["run_fad"] is False
    assert analysis["fad_height_percentile"] == 99.0
    assert analysis["fad_x_near_m"] == 0.0
    assert analysis["fad_y_min_m"] == 0.03
    assert analysis["fad_height_buffer_m"] == 0.0
    assert analysis["fad_grubbs_alpha"] == 0.01
    assert analysis["fad_g_function"] == "spherical"
    assert analysis["fad_run_layers"] is False
    assert analysis["fad_layer_thickness_m"] == 0.10
    assert analysis["fad_include_layer_columns"] is True
    assert analysis["force_two_sided_targets"] is False


def test_mta_config_defaults_validation_and_legacy_mapping(tmp_path):
    from lidar_analysis.central_runner import build_config, phenotype_columns

    defaults = default_analysis_yaml_dict()
    assert defaults["mta_angle_bin_deg"] == 5.0
    assert defaults["mta_diagnostic"] is False
    assert [key for key in defaults if key == "run_mta" or key.startswith("mta_")] == [
        "run_mta", "mta_angle_bin_deg", "mta_diagnostic",
    ]
    assert "mta_fit_angle_min_deg" not in defaults
    assert "mta_fit_angle_max_deg" not in defaults
    assert "mta_n_bins" not in defaults

    for width in (2.5, 5.0, 10.0):
        cfg = build_config({"run_mta": True, "mta_angle_bin_deg": width}, False, "CART", tmp_path)
        assert cfg.mta_angle_bin_deg == width
        assert [name for name in phenotype_columns(cfg) if name.startswith("mta_")] == ["mta_deg", "mta_qc_pass"]
        assert "lai_even" not in phenotype_columns(cfg)

    legacy = build_config({"mta_lo_deg": 25.0, "mta_hi_deg": 65.0, "mta_n_bins": 4}, False, "CART", tmp_path)
    assert legacy.mta_angle_bin_deg == 10.0
    with pytest.raises(ValueError, match="not Boolean"):
        build_config({"mta_angle_bin_deg": True}, False, "CART", tmp_path)
    with pytest.raises(ValueError, match="greater than zero"):
        build_config({"mta_angle_bin_deg": 0.0}, False, "CART", tmp_path)
    with pytest.raises(ValueError, match="fixed 25-65"):
        build_config({"mta_fit_angle_min_deg": 30.0}, False, "CART", tmp_path)
    assert phenotype_columns(build_config({"run_mta": True, "mta_diagnostic": True}, False, "CART", tmp_path)) == phenotype_columns(
        build_config({"run_mta": True, "mta_diagnostic": False}, False, "CART", tmp_path)
    )


def test_fad_phenotype_columns_are_minimal_by_default():
    from pathlib import Path

    from lidar_analysis.central_runner import build_config, phenotype_columns

    cfg = build_config({"run_fad": True}, force=False, cart_id="CART", data_dir=Path("."))
    cols = phenotype_columns(cfg)

    assert "fad_app_m2_m3" in cols
    assert "fad_x_min_m" in cols
    assert "fad_x_max_m" in cols
    assert "fad_lai_from_layers" not in cols
    assert "fad_n_layers" not in cols
    assert not any(c.startswith("fad_height_") for c in cols)
    assert not any(c.startswith("fad_layer_") for c in cols)
    assert not any(c.startswith("fad_n_") for c in cols)


def test_fad_phenotype_columns_include_layer_summaries_when_enabled():
    from pathlib import Path

    from lidar_analysis.central_runner import build_config, phenotype_columns

    cfg = build_config(
        {"run_fad": True, "fad_run_layers": True, "fad_include_layer_columns": True},
        force=False,
        cart_id="CART",
        data_dir=Path("."),
    )
    cols = phenotype_columns(cfg)

    assert cfg.fad_run_layers is True
    assert "fad_app_m2_m3" in cols
    assert "fad_lai_from_layers" in cols
    assert "fad_integrated_m2_m2" in cols
    assert "fad_n_layers" in cols
    assert not any(c.startswith("fad_layer_") for c in cols)


def test_results_csv_adds_dynamic_fad_layer_columns(tmp_path):
    import csv

    from lidar_analysis.central_runner import append_trait_rows, build_config, ensure_results_csv

    cfg = build_config(
        {"run_fad": True, "fad_run_layers": True, "fad_include_layer_columns": True},
        force=False,
        cart_id="CART",
        data_dir=tmp_path,
    )
    path = tmp_path / "results.csv"
    ensure_results_csv(path, cfg)
    append_trait_rows(path, "experiment", "2026_06_18", "scan", [{
        "scan": "scan",
        "fad_lai_from_layers": 2.345,
        "fad_integrated_m2_m2": 2.344,
        "point_density_m2": 12.346,
        "plot_length_m": 1.2192,
        "points": 2.0,
        "lidar_scans": 3.0,
        "fad_layer_010_035_m2_m3": 3.0,
        "fad_layer_035_060_m2_m3": 4.0,
        "fad_layer_010_035_hits": 99,
    }], cfg)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)

    assert "fad_layer_010_035_m2_m3" in reader.fieldnames
    assert "fad_layer_035_060_m2_m3" in reader.fieldnames
    assert row["fad_lai_from_layers"] == "2.35"
    assert row["fad_integrated_m2_m2"] == "2.34"
    assert row["point_density_m2"] == "12.35"
    assert row["plot_length_m"] == "1.22"
    assert row["fad_layer_010_035_m2_m3"] == "3.00"
    assert row["points"] == "2"
    assert row["lidar_scans"] == "3"


def test_results_csv_contains_bounded_mta_summary(tmp_path):
    import csv

    from lidar_analysis.central_runner import append_trait_rows, build_config, ensure_results_csv

    cfg = build_config({"run_mta": True}, force=False, cart_id="CART", data_dir=tmp_path)
    path = tmp_path / "results.csv"
    ensure_results_csv(path, cfg)
    append_trait_rows(path, "experiment", "2026_06_18", "scan", [{
        "scan_name": "scan_007_multi02",
        "side": "right",
        "plot": "1",
        "target_type": "plot",
        "target_id": "plot_1_right",
        "mta_deg": 42.5,
        "mta_method": "bounded_lang_v1",
        "mta_g_slope_per_rad": -0.25,
        "mta_y_min_m": 0.03,
        "mta_y_max_m": 0.82,
        "mta_qc_pass": True,
        "mta_status": "ok",
    }], cfg)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)

    assert [name for name in reader.fieldnames if name.startswith("mta_")] == ["mta_deg", "mta_qc_pass"]
    assert row["scan_name"] == "scan_007_multi02"
    assert row["scan_number"] == "7"
    assert row["side"] == "right"
    assert row["mta_deg"] == "42.50"
    assert row["mta_qc_pass"] == "True"


def test_pai_main_schema_is_layer_integrated_and_compact(tmp_path):
    from lidar_analysis.central_runner import build_config, phenotype_columns

    defaults = default_analysis_yaml_dict()
    assert not {"pai_run_layers", "pai_run_joint_profile", "pai_run_conditional_profile"} & defaults.keys()
    cfg = build_config({"run_pai": True}, force=False, cart_id="CART", data_dir=tmp_path)
    assert cfg.pai_run_conditional_profile is True
    assert cfg.pai_include_layer_columns is False
    assert cfg.pai_diagnostic is False
    assert [name for name in phenotype_columns(cfg) if name.startswith("pai_")] == [
        "pai_m2_m2", "pai_height_m", "pai_layer_thickness_m", "pai_n_layers",
    ]


def test_build_config_maps_local_ground_grid_settings(tmp_path):
    from lidar_analysis.central_runner import build_config

    cfg = build_config({"use_local_ground_filter": True, "local_ground_x_bin_m": .05,
                        "local_ground_z_bin_m": .05}, force=False, cart_id="CART", data_dir=tmp_path)
    assert cfg.use_local_ground_filter is True
    assert cfg.local_ground_x_bin_m == cfg.local_ground_z_bin_m == .05


def test_build_config_maps_force_two_sided_targets(tmp_path):
    from lidar_analysis.central_runner import build_config

    cfg = build_config(
        {"force_two_sided_targets": True},
        force=False,
        cart_id="CART",
        data_dir=tmp_path,
    )

    assert cfg.force_two_sided_targets is True


def test_canopy_volume_2p5d_result_columns_when_enabled(tmp_path):
    from lidar_analysis.central_runner import build_config, phenotype_columns

    cfg = build_config(
        {"pointcloud_ops": [{"name": "canopy_volume_2p5d", "enabled": True}]},
        force=False, cart_id="CART", data_dir=tmp_path,
    )
    cols = phenotype_columns(cfg)
    assert "canopy_volume_2p5d_m3" in cols
    assert "canopy_volume_2p5d_m3_m2" in cols
    assert "canopy_volume_2p5d_occupied_cells" in cols
    assert "canopy_volume_2p5d_total_cells" in cols
    assert "canopy_volume_2p5d_observed_area_m2" in cols
    assert "canopy_volume_2p5d_coverage_fraction" in cols


def test_full_experiment_config_template_loads(tmp_path):
    from pathlib import Path

    import yaml

    from lidar_analysis.central_runner import build_config, extract_analysis_cfg

    template_path = Path("lidar_analysis/example_configs/full_experiment_config_template.yaml")
    with open(template_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    analysis = extract_analysis_cfg(raw)
    cfg = build_config(analysis, force=False, cart_id="CART", data_dir=tmp_path)

    assert cfg.force_two_sided_targets is False
    assert cfg.additional_scan_side_split is False
    assert cfg.additional_scan_side_axis == "x"
    assert cfg.markers_dirname == "markers"
    assert cfg.run_pai is False
    assert cfg.pai_g_function == "spherical"
    assert cfg.pai_g_value == 0.5
    assert cfg.pai_height_percentile == 99.0
    assert cfg.pai_grubbs_alpha == 0.01
    assert cfg.pai_x_near_m == 0.0
    assert cfg.pai_y_min_m == 0.1
    assert cfg.pai_run_layers is True
    assert cfg.pai_run_joint_profile is False
    assert cfg.pai_run_conditional_profile is True
    assert cfg.pai_diagnostic is False
    assert cfg.pai_include_layer_columns is False

    ops = cfg.pointcloud_ops or []
    op_names = [str(op.get("op", op.get("name", ""))).strip().lower() for op in ops]
    assert op_names == [
        "scalar_range_filter",
        "sor_filter",
        "bilateral_scalar_filter",
        "height_range_filter",
        "voxel_count",
        "topology_trait",
        "slice_structure_trait",
        "canopy_volume_2p5d",
    ]
    assert "voxel_grid" not in op_names
    assert "voxel_volume" not in op_names
    assert all(op.get("enabled") is False for op in ops)
