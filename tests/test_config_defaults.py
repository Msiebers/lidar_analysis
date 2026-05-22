from lidar_analysis.config import default_analysis_yaml_dict, normalize_rssi_mode
from lidar_analysis.scaffold_experiments import default_experiment_config

def test_default_config_from_single_source():
    exp = default_experiment_config('exp1')
    assert exp['analysis'] == default_analysis_yaml_dict()

def test_rssi_modes_restricted():
    assert normalize_rssi_mode('zscore') == 'zscore'
    assert normalize_rssi_mode('percentile') == 'percentile'
