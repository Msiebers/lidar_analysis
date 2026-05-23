import numpy as np
import pandas as pd

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops
from lidar_analysis.topology import topology_stand_count


def _target(df, target_type='plot', row=None):
    return AnalysisTarget.from_points(
        target_id='t1', target_type=target_type, scan_id='s1', points_df=df, source_indices=np.arange(len(df)), row=row
    )


def test_topology_stand_count_meter_input_direct():
    pts = np.array([[0.01, 0.1, 0.0], [0.02, 0.15, 0.2], [0.10, 0.2, 0.4]], dtype=float)
    out = topology_stand_count(pts, min_persistence=0.35)
    assert 'count' in out and 'count_raw' in out and 'points' in out


def test_topology_trait_non_mutating_and_writes_traits():
    df = pd.DataFrame({'X':[10.0,20.0],'Y':[40.0,80.0],'Z':[0.0,50.0],'RSSI':[1.0,2.0]})
    tgt = _target(df)
    raw0 = tgt.raw_points.copy(deep=True)
    cur0 = tgt.current_points.copy(deep=True)
    out = apply_pointcloud_ops(tgt, [{'name':'topology_trait'}])
    assert out.current_points.equals(cur0)
    assert out.raw_points.equals(raw0)
    assert 'topo_count' in out.traits


def test_topology_order_before_height_then_voxel():
    df = pd.DataFrame({'X':[0,0,100],'Y':[10,60,80],'Z':[0,20,40],'RSSI':[1,1,1]})
    out = apply_pointcloud_ops(_target(df), [
        {'name':'topology_trait'},
        {'name':'height_range_filter','min_m':0.05},
        {'name':'voxel_count','voxel_size_m':0.05},
    ])
    order = out.diagnostics['pointcloud_ops']['operation_order']
    assert order == ['topology_trait', 'height_range_filter', 'voxel_count']


def test_topology_fallback_reconstructed_z_mm_to_m_warning():
    df = pd.DataFrame({'X':[1000.0,2000.0],'Y':[500.0,800.0],'Z':[0.0,1000.0],'RSSI':[1,1]})
    out = apply_pointcloud_ops(_target(df), [{'name':'topology_trait'}])
    diags = out.diagnostics['pointcloud_ops']['op_diagnostics'][0]
    assert diags['topology_z_source'] == 'reconstructed_Z'
    assert 'warning' in diags


def test_topology_uses_travel_z_or_scan_position():
    df1 = pd.DataFrame({'X':[0.0,0.0],'Y':[100.0,200.0],'Z':[999.0,999.0],'travel_z_m':[0.0,0.5],'RSSI':[1,1]})
    d1 = apply_pointcloud_ops(_target(df1), [{'name':'topology_trait'}]).diagnostics['pointcloud_ops']['op_diagnostics'][0]
    assert d1['topology_z_source'] == 'travel_z_m'

    df2 = pd.DataFrame({'X':[0.0,0.0],'Y':[100.0,200.0],'Z':[999.0,999.0],'scan_position_m':[0.0,0.5],'RSSI':[1,1]})
    d2 = apply_pointcloud_ops(_target(df2), [{'name':'topology_trait'}]).diagnostics['pointcloud_ops']['op_diagnostics'][0]
    assert d2['topology_z_source'] == 'scan_position_m'


def test_row_specific_no_side_split_and_whole_plot_side_split():
    row_df = pd.DataFrame({'X':[-10.0,10.0],'Y':[40.0,45.0],'Z':[0.0,50.0],'RSSI':[1,1]})
    row_out = apply_pointcloud_ops(_target(row_df, target_type='plant', row='R1'), [{'name':'topology_trait','split_sides_for_single_plot':True}])
    assert np.isnan(row_out.traits['topo_count_left'])
    assert np.isnan(row_out.traits['topo_count_right'])

    plot_df = pd.DataFrame({'X':[-10.0,10.0,12.0],'Y':[40.0,45.0,55.0],'Z':[0.0,50.0,70.0],'RSSI':[1,1,1]})
    plot_out = apply_pointcloud_ops(_target(plot_df, target_type='plot', row=None), [{'name':'topology_trait','split_sides_for_single_plot':True}])
    assert not np.isnan(plot_out.traits['topo_count_whole'])
    assert not np.isnan(plot_out.traits['topo_count_left'])
    assert not np.isnan(plot_out.traits['topo_count_right'])
