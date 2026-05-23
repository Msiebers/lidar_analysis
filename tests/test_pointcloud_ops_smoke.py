import numpy as np
import pandas as pd
import pytest

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops
from lidar_analysis.pipeline_core import normalize_rssi_by_phi_zscore, Plot


def _target(df, **kw):
    return AnalysisTarget.from_points(target_id='t1', target_type=kw.get('target_type','plot'), scan_id='s1', points_df=df, source_indices=np.array([0,1,2,3]), row=kw.get('row'))


def test_height_range_filter_mm_and_raw_unchanged():
    df = pd.DataFrame({"X":[0,0],"Y":[10.0,40.0],"Z":[0,0],"RSSI":[1,1]})  # mm
    out = apply_pointcloud_ops(_target(df), [{"op":"height_range_filter","axis":"Y","min_m":0.03}])
    assert len(out.current_points) == 1
    assert len(out.raw_points) == 2


def test_topology_trait_non_mutating_and_writes_traits_order():
    df = pd.DataFrame({"X":[-10.0,10.0,10.0],"Y":[50,50,70],"Z":[0.0,0.0,20.0],"RSSI":[1,1,1]})
    out = apply_pointcloud_ops(_target(df, target_type='plot', row=None), [
        {"name":"topology_trait","split_sides_for_single_plot":True},
        {"name":"height_range_filter","min_m":0.06},
        {"name":"voxel_count","voxel_size_m":0.05},
    ])
    assert len(out.current_points) == 1  # mutated by height filter
    assert out.traits.get('topo_count_whole') is not None
    assert out.traits.get('topo_count_left') is not None
    assert out.diagnostics['pointcloud_ops']['operation_order'] == ['topology_trait','height_range_filter','voxel_count']


def test_voxel_after_height_filter_not_greater_than_before():
    df = pd.DataFrame({"X":[0,0,100],"Y":[10,100,100],"Z":[0,0,0],"RSSI":[1,1,1]})
    pre = apply_pointcloud_ops(_target(df), [{"op":"voxel_count","voxel_size_m":0.05}]).traits['voxel_count']
    post = apply_pointcloud_ops(_target(df), [{"op":"height_range_filter","min_m":0.05},{"op":"voxel_count","voxel_size_m":0.05}]).traits['voxel_count']
    assert post <= pre


def test_two_row_target_no_side_split_again():
    df = pd.DataFrame({"X":[-10,10],"Y":[50,50],"Z":[0,10],"RSSI":[1,1]})
    out = apply_pointcloud_ops(_target(df, target_type='plant', row='R1'), [{"op":"topology_trait","split_sides_for_single_plot":True,"two_row_mode":"target_only"}])
    assert np.isnan(out.traits['topo_count_left'])
    assert np.isnan(out.traits['topo_count_right'])


def test_missing_scalar_error_and_zscore_no_clip_and_plot_write(tmp_path):
    df = pd.DataFrame({"X":[1000.0],"Y":[2000.0],"Z":[3000.0],"RSSI":[4.0],"rssi_norm":[1.2],"rssi_norm_bilateral":[1.1]})
    with pytest.raises(ValueError):
        apply_pointcloud_ops(_target(df), [{"op":"scalar_range_filter","scalar":"missing","min":0}])
    phi = np.array([0,0,0,0],dtype=np.float32)
    rssi = np.array([1,1,1,10000],dtype=np.float32)
    outz = normalize_rssi_by_phi_zscore(phi,rssi)
    assert outz.max() > np.exp(4.0)
    plot = Plot('R1','1',(0,1),str(tmp_path),'scan_a')
    plot.analysis_target = AnalysisTarget.from_points(target_id='t', target_type='plot', scan_id='s', points_df=df, source_indices=np.array([0]))
    plot.write(make_point_cloud=True, overwrite_outputs=True, write_o3d_ply=False)
    written = pd.read_csv(plot.csv_out)
    assert 'rssi_norm_bilateral' in written.columns
