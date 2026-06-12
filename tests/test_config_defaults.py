from lidar_analysis.config import default_analysis_yaml_dict, normalize_rssi_mode
from lidar_analysis.scaffold_experiments import default_experiment_config

def test_default_config_from_single_source():
    exp = default_experiment_config('exp1')
    assert exp['analysis'] == default_analysis_yaml_dict()

def test_rssi_modes_restricted():
    assert normalize_rssi_mode('zscore') == 'zscore'
    assert normalize_rssi_mode('percentile') == 'percentile'


def test_fad_config_defaults_present():
    analysis = default_analysis_yaml_dict()

    assert analysis["run_fad"] is False
    assert analysis["fad_height_percentile"] == 99.0
    assert analysis["fad_y_min_m"] == 0.03
    assert analysis["fad_height_buffer_m"] == 0.0
    assert analysis["fad_grubbs_alpha"] == 0.01
    assert analysis["fad_g_function"] == "spherical"
    assert analysis["fad_run_layers"] is False
    assert analysis["fad_layer_thickness_m"] == 0.10
    assert analysis["fad_include_layer_columns"] is True


def test_fad_phenotype_columns_are_minimal_by_default():
    from pathlib import Path

    from lidar_analysis.central_runner import build_config, phenotype_columns

    cfg = build_config({"run_fad": True}, force=False, cart_id="CART", data_dir=Path("."))
    cols = phenotype_columns(cfg)

    assert "fad_app_m2_m3" in cols
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
    assert "fad_n_layers" in cols
    assert not any(c.startswith("fad_layer_") for c in cols)
