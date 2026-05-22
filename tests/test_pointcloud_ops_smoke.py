import numpy as np
import pandas as pd
import pytest

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops
from lidar_analysis.pipeline_core import normalize_rssi_by_phi_zscore


def _target(df):
    return AnalysisTarget.from_points(target_id='t1', target_type='plot', scan_id='s1', points_df=df, source_indices=np.array([0,1,2,3]))


def test_op_name_alias_and_enabled_skip_and_diagnostics():
    df = pd.DataFrame({"X":[0,0,0.1,1],"Y":[0,0,0,1],"Z":[0,0.1,0,1],"RSSI":[10,20,30,40]})
    t = _target(df)
    out = apply_pointcloud_ops(t, [
        {"name":"scalar_range_filter","scalar":"RSSI","min":15},
        {"op":"scalar_range_filter","scalar":"RSSI","min":1000,"enabled":False},
        {"op":"voxel_grid","voxel_size":0.05},
    ])
    assert len(out.current_points) == 3
    assert [x['op'] for x in out.op_history] == ['scalar_range_filter','voxel_grid']
    d = out.diagnostics['pointcloud_ops']
    assert d['operation_order'] == ['scalar_range_filter','voxel_grid']


def test_bilateral_on_rssi_default_replace():
    df = pd.DataFrame({"X":[0,0.01,0.02,0.03],"Y":[0,0,0,0],"Z":[0,0,0,0],"RSSI":[1.,100.,1.,100.]})
    t = _target(df)
    out = apply_pointcloud_ops(t,[{"op":"bilateral_scalar_filter","scalar":"RSSI","radius_m":0.05,"spatial_sigma_m":0.03,"scalar_sigma":10.0}])
    assert not np.allclose(out.current_points['RSSI'].to_numpy(), t.raw_points['RSSI'].to_numpy())


def test_bilateral_on_rssi_norm_and_missing_scalar_error():
    df = pd.DataFrame({"X":[0,0.01],"Y":[0,0],"Z":[0,0],"RSSI":[5.,7.],"rssi_norm":[1.0,2.0]})
    out = apply_pointcloud_ops(_target(df),[{"op":"bilateral_scalar_filter","field":"rssi_norm"}])
    assert 'rssi_norm' in out.current_points.columns
    with pytest.raises(ValueError) as e:
        apply_pointcloud_ops(_target(df),[{"op":"scalar_range_filter","input_scalar":"missing","min":0}])
    assert 'Available columns' in str(e.value)


def test_scalar_range_uses_named_scalar_and_voxel_count_current_points():
    df = pd.DataFrame({"X":[0,0.1,0.2,0.3],"Y":[0,0,0,0],"Z":[0,0,0,0],"RSSI":[10,10,10,10],"rssi_norm":[0.1,2.0,0.2,3.0]})
    out = apply_pointcloud_ops(_target(df),[
        {"op":"scalar_range_filter","input_scalar":"rssi_norm","min":1.0},
        {"op":"voxel_grid","voxel_size":0.05},
    ])
    assert len(out.raw_points) == 4
    assert len(out.current_points) == 2
    assert out.traits['voxel_count'] == 2


def test_zscore_normalization_no_clip():
    phi = np.array([0,0,0,0],dtype=np.float32)
    rssi = np.array([1,1,1,10000],dtype=np.float32)
    out = normalize_rssi_by_phi_zscore(phi,rssi)
    assert out.max() > np.exp(4.0)
