import numpy as np
import pandas as pd
import pytest

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops
from lidar_analysis.pipeline_core import normalize_rssi_by_phi_zscore, Plot


def _target(df):
    return AnalysisTarget.from_points(target_id='t1', target_type='plot', scan_id='s1', points_df=df, source_indices=np.array([0,1,2,3]))


def test_ops_alias_enabled_and_named_scalar_filter():
    df = pd.DataFrame({"X":[0,0,0.1,1],"Y":[0,0,0,1],"Z":[0,0.1,0,1],"RSSI":[10,20,30,40],"rssi_norm":[0.1,1.1,2.1,3.1]})
    out = apply_pointcloud_ops(_target(df), [
        {"name":"scalar_range_filter","input_scalar":"rssi_norm","min":1.0},
        {"op":"scalar_range_filter","scalar":"rssi_norm","min":1000,"enabled":False},
        {"op":"voxel_grid","voxel_size":0.05},
    ])
    assert len(out.current_points) == 3
    assert len(out.raw_points) == 4
    assert out.traits['voxel_count'] == 3
    assert out.diagnostics['pointcloud_ops']['operation_order'] == ['scalar_range_filter','voxel_grid']


def test_bilateral_rssi_norm_columns_and_missing_scalar_error():
    df = pd.DataFrame({"X":[0,0.01],"Y":[0,0],"Z":[0,0],"RSSI":[5.,7.],"rssi_norm":[1.0,2.0]})
    out = apply_pointcloud_ops(_target(df),[{"op":"bilateral_scalar_filter","field":"rssi_norm","output_scalar":"rssi_norm_bilateral","replace_scalar":False}])
    assert set(["RSSI","rssi_norm","rssi_norm_bilateral"]).issubset(set(out.current_points.columns))
    with pytest.raises(ValueError) as e:
        apply_pointcloud_ops(_target(df),[{"op":"scalar_range_filter","input_scalar":"missing","min":0}])
    assert 'Available columns' in str(e.value)


def test_plot_write_uses_analysis_target_all_columns(tmp_path):
    df = pd.DataFrame({"X":[1000.0],"Y":[2000.0],"Z":[3000.0],"RSSI":[4.0],"rssi_norm":[1.2],"rssi_norm_bilateral":[1.1]})
    plot = Plot('R1','1',(0,1),str(tmp_path),'scan_a')
    plot.analysis_target = AnalysisTarget.from_points(target_id='t', target_type='plot', scan_id='s', points_df=df, source_indices=np.array([0]))
    plot.write(make_point_cloud=True, overwrite_outputs=True, write_o3d_ply=False)
    written = pd.read_csv(plot.csv_out)
    assert list(written.columns) == ["X","Y","Z","RSSI","rssi_norm","rssi_norm_bilateral"]
    assert float(written.loc[0,'X']) == 1.0
    assert float(written.loc[0,'Y']) == 2.0
    assert float(written.loc[0,'Z']) == 3.0
    assert float(written.loc[0,'RSSI']) == 4.0
    assert float(written.loc[0,'rssi_norm']) == 1.2
    assert float(written.loc[0,'rssi_norm_bilateral']) == 1.1


def test_analysis_target_raw_unchanged_current_mutated_by_ops():
    df = pd.DataFrame({"X":[0.0,100.0],"Y":[0.0,0.0],"Z":[0.0,0.0],"RSSI":[1.0,9.0],"rssi_norm":[0.0,2.0]})
    t = _target(df)
    raw_before = t.raw_points.copy(deep=True)
    out = apply_pointcloud_ops(t, [{"op":"scalar_range_filter","input_scalar":"rssi_norm","min":1.0}])
    assert len(out.current_points) == 1
    assert len(out.raw_points) == 2
    pd.testing.assert_frame_equal(out.raw_points.reset_index(drop=True), raw_before.reset_index(drop=True))


def test_voxel_count_uses_post_filter_current_points():
    df = pd.DataFrame({
        "X":[0.0,10.0,20.0],
        "Y":[0.0,0.0,0.0],
        "Z":[0.0,0.0,0.0],
        "RSSI":[1.0,2.0,3.0],
        "rssi_norm":[0.1,1.1,2.1],
    })
    out = apply_pointcloud_ops(_target(df), [
        {"op":"scalar_range_filter","input_scalar":"rssi_norm","min":1.0},
        {"op":"voxel_count","voxel_size_m":0.001},
    ])
    assert len(out.current_points) == 2
    assert out.traits["voxel_count"] == 2


def test_zscore_no_clip_and_source_has_no_clip_call():
    phi = np.array([0,0,0,0],dtype=np.float32)
    rssi = np.array([1,1,1,10000],dtype=np.float32)
    out = normalize_rssi_by_phi_zscore(phi,rssi)
    assert out.max() > np.exp(4.0)
    import inspect
    src = inspect.getsource(normalize_rssi_by_phi_zscore)
    assert 'np.clip' not in src
