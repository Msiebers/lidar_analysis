import numpy as np
import pandas as pd
import pytest

from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops
from lidar_analysis.pipeline_core import normalize_rssi_by_phi_zscore, Plot
from lidar_analysis.topology.stand_count import topology_stand_count


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


def test_height_range_filter_meter_bounds_converted_to_mm_and_diag():
    df = pd.DataFrame({"X":[0.0,0.0,0.0],"Y":[10.0,30.0,60.0],"Z":[0.0,0.0,0.0],"RSSI":[1.0,2.0,3.0]})
    out = apply_pointcloud_ops(_target(df), [{"op":"height_range_filter","axis":"Y","min_m":0.02,"max_m":0.04}])
    assert list(out.current_points["Y"].to_numpy()) == [30.0]
    hr = out.diagnostics["pointcloud_ops"]["height_range_filters"][0]
    assert hr["axis"] == "Y"
    assert hr["min_m"] == 0.02
    assert hr["max_m"] == 0.04
    assert hr["points_before"] == 3
    assert hr["points_after"] == 1


def test_height_range_filter_mutates_current_not_raw_points():
    df = pd.DataFrame({"X":[0.0,0.0],"Y":[20.0,40.0],"Z":[0.0,0.0],"RSSI":[5.0,6.0]})
    t = _target(df)
    raw_before = t.raw_points.copy(deep=True)
    out = apply_pointcloud_ops(t, [{"op":"height_range_filter","min_m":0.03}])
    assert len(out.current_points) == 1
    assert len(out.raw_points) == 2
    pd.testing.assert_frame_equal(out.raw_points.reset_index(drop=True), raw_before.reset_index(drop=True))


def test_voxel_count_after_height_range_filter_uses_filtered_points():
    df = pd.DataFrame({"X":[0.0,0.0,0.0],"Y":[10.0,35.0,80.0],"Z":[0.0,100.0,200.0],"RSSI":[1.0,2.0,3.0]})
    out = apply_pointcloud_ops(_target(df), [
        {"op":"height_range_filter","axis":"Y","min_m":0.03,"max_m":0.06},
        {"op":"voxel_count","voxel_size_m":0.01},
    ])
    assert len(out.current_points) == 1
    assert out.traits["voxel_count"] == 1


def test_zscore_square_root_transform_and_source_has_no_clip_call():
    phi = np.array([0,0,0,0],dtype=np.float32)
    rssi = np.array([1,1,1,10000],dtype=np.float32)
    out = normalize_rssi_by_phi_zscore(phi,rssi)

    mu = np.mean(rssi, dtype=np.float64)
    sd = np.std(rssi, dtype=np.float64)
    z = ((rssi - mu) / sd).astype(np.float32)
    expected = np.maximum(
        1.0 + np.sign(z) * np.sqrt(np.abs(z)),
        0.0
    ).astype(np.float32)

    np.testing.assert_allclose(out, expected)

    import inspect
    src = inspect.getsource(normalize_rssi_by_phi_zscore)
    assert 'np.clip' not in src


def test_topology_stand_count_direct_simple_meter_cloud():
    d = pd.DataFrame({"x":[-0.04,-0.02,0.02,0.04],"y":[0.1,0.1,0.1,0.1],"z":[0.0,0.1,0.0,0.1]})
    count, points = topology_stand_count(d, min_persistence=0.35)
    assert np.isfinite(count)
    assert isinstance(points, list)


def test_topology_trait_non_mutating_writes_topo_count():
    df = pd.DataFrame({"X":[-20.0,20.0],"Y":[100.0,100.0],"Z":[0.0,100.0],"RSSI":[1.0,2.0]})
    t = _target(df)
    cur_before = t.current_points.copy(deep=True)
    out = apply_pointcloud_ops(t, [{"op":"topology_trait","min_persistence":0.35}])
    pd.testing.assert_frame_equal(out.current_points.reset_index(drop=True), cur_before.reset_index(drop=True))
    assert "topo_count" in out.traits


def test_topology_trait_yaml_order_before_height_range_filter():
    df = pd.DataFrame({"X":[0.0,0.0],"Y":[10.0,50.0],"Z":[0.0,100.0],"RSSI":[1.0,2.0]})
    out = apply_pointcloud_ops(_target(df), [
        {"op":"topology_trait"},
        {"op":"height_range_filter","axis":"Y","min_m":0.03},
    ])
    assert out.diagnostics["pointcloud_ops"]["operation_order"] == ["topology_trait", "height_range_filter"]
    assert len(out.current_points) == 1


def test_topology_trait_prefers_travel_scan_position_column():
    df = pd.DataFrame({
        "X":[0.0,20.0],"Y":[100.0,100.0],"Z":[9999.0,9999.0],"RSSI":[1.0,2.0],
        "travel_z_m":[0.0,0.2],
    })
    out = apply_pointcloud_ops(_target(df), [{"op":"topology_trait"}])
    diag = out.diagnostics["pointcloud_ops"]["topology_trait"][0]
    assert diag["z_source"] == "travel_z_m"
    assert diag["warning"] is None


def test_topology_trait_reconstructed_z_fallback_warning():
    df = pd.DataFrame({"X":[0.0,20.0],"Y":[100.0,100.0],"Z":[0.0,200.0],"RSSI":[1.0,2.0]})
    out = apply_pointcloud_ops(_target(df), [{"op":"topology_trait"}])
    diag = out.diagnostics["pointcloud_ops"]["topology_trait"][0]
    assert diag["z_source"] == "Z_mm_fallback"
    assert "reconstructed Z fallback" in diag["warning"]


def test_topology_trait_whole_plot_side_split_traits():
    df = pd.DataFrame({"X":[-20.0,-10.0,10.0,20.0],"Y":[100.0]*4,"Z":[0.0,100.0,0.0,100.0],"RSSI":[1.0,2.0,3.0,4.0]})
    t = AnalysisTarget.from_points(target_id='t2', target_type='plot', scan_id='s1', points_df=df, source_indices=np.array([0,1,2,3]), row=None)
    out = apply_pointcloud_ops(t, [{"op":"topology_trait","split_sides_for_single_plot":True}])
    assert "topo_count_whole" in out.traits
    assert "topo_count_left" in out.traits
    assert "topo_count_right" in out.traits
    assert out.diagnostics["pointcloud_ops"]["topology_trait"][0]["side_split_applied"] is True


def test_topology_trait_side_mean_and_ignore_from_scan_id():
    df = pd.DataFrame({"X":[-20.0,-10.0,10.0,20.0],"Y":[100.0]*4,"Z":[0.0,100.0,0.0,100.0],"RSSI":[1.0,2.0,3.0,4.0]})
    t_both = AnalysisTarget.from_points(target_id='tb', target_type='plot', scan_id='2&1_1_20', points_df=df, source_indices=np.array([0,1,2,3]), row=None)
    out_both = apply_pointcloud_ops(
        t_both,
        [{"op":"topology_trait","split_sides_for_single_plot":True}],
        context={"additional_scan_positive_side_label":"right", "additional_scan_negative_side_label":"left"},
    )
    left = float(out_both.traits["topo_count_left"])
    right = float(out_both.traits["topo_count_right"])
    assert np.isfinite(left) and np.isfinite(right)
    assert out_both.traits["topo_count"] == pytest.approx((left + right) / 2.0)

    t_ignore_right = AnalysisTarget.from_points(target_id='tir', target_type='plot', scan_id='2&0_1_20', points_df=df, source_indices=np.array([0,1,2,3]), row=None)
    out_ignore_right = apply_pointcloud_ops(
        t_ignore_right,
        [{"op":"topology_trait","split_sides_for_single_plot":True}],
        context={"additional_scan_positive_side_label":"right", "additional_scan_negative_side_label":"left"},
    )
    assert np.isfinite(float(out_ignore_right.traits["topo_count_left"]))
    assert np.isnan(float(out_ignore_right.traits["topo_count_right"]))
    assert out_ignore_right.traits["topo_count"] == pytest.approx(float(out_ignore_right.traits["topo_count_left"]))
    assert np.isfinite(float(out_ignore_right.traits["topo_left_count"]))
    assert np.isfinite(float(out_ignore_right.traits["topo_left_per_m"]))


def test_topology_trait_write_objects_diag_shape():
    df = pd.DataFrame({"X":[-20.0,-10.0,10.0,20.0],"Y":[100.0]*4,"Z":[0.0,100.0,0.0,100.0],"RSSI":[1.0,2.0,3.0,4.0]})
    t = AnalysisTarget.from_points(target_id='to', target_type='plot', scan_id='2&1_1_20', points_df=df, source_indices=np.array([0,1,2,3]), row=None)
    out = apply_pointcloud_ops(
        t,
        [{"op":"topology_trait","split_sides_for_single_plot":True, "write_topology_objects":True}],
        context={"additional_scan_positive_side_label":"right", "additional_scan_negative_side_label":"left"},
    )
    d = out.diagnostics["pointcloud_ops"]["topology_trait"][0]
    assert d["write_topology_objects"] is True
    pts = d["topology_object_points_xyz"]
    assert isinstance(pts, list)
    if pts:
        assert len(pts[0]) == 3
        assert pts[0][1] == 0.0
