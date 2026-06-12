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
    assert analysis["fad_layer_thickness_m"] == 0.10
    assert analysis["fad_include_layer_columns"] is True
