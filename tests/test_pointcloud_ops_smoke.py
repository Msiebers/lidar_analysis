import numpy as np
import pandas as pd
from lidar_analysis.analysis_target import AnalysisTarget
from lidar_analysis.pointcloud_ops import apply_pointcloud_ops


def test_pointcloud_ops_target_lifecycle():
    df = pd.DataFrame({"X":[0.0,0.0,0.1,1.0],"Y":[0,0.01,0,1.0],"Z":[0,0.01,0,1.0],"RSSI":[10.0,12.0,8.0,999.0],"scan_meta":[1,1,1,1]})
    target = AnalysisTarget.from_points(target_id='t1', target_type='plot', scan_id='s1', points_df=df, source_indices=np.array([0,1,2,3]))
    out = apply_pointcloud_ops(target, [
        {"op":"scalar_range_filter","field":"RSSI","max":100},
        {"op":"voxel_grid","voxel_size":0.05},
    ])
    assert len(out.raw_points) == 4
    assert len(out.current_points) == 3
    assert [x['op'] for x in out.op_history] == ['scalar_range_filter','voxel_grid']
    assert out.traits['voxel_count'] >= 1
    assert out.source_indices.shape[0] == 4
