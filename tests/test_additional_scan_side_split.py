#!/usr/bin/env python3
import numpy as np

from lidar_analysis.pipeline_core import Plot, analyze_plot
from lidar_analysis.config import AnalysisConfig


def test_additional_scan_side_split_smoke() -> None:
    cfg = AnalysisConfig(
        data_dirs=[],
        calibration_dir='.',
        cart_id='test',
        run_height=False,
        run_lai=False,
        run_topology=False,
        run_o3d_metrics=False,
    )

    data = np.array([
        [1.0, 0.0, 10.0, 5.0],
        [-1.0, 0.0, 10.0, 5.0],
        [2.0, 0.0, 10.0, 5.0],
        [-2.0, 0.0, 10.0, 5.0],
    ], dtype=np.float32)
    keep_idx = np.arange(data.shape[0], dtype=np.int32)
    fused_np = np.zeros((data.shape[0], 6), dtype=np.float32)

    p_left = Plot(row='scan', letter='1', z_bounds=(0.0, 20.0), out_dir='.', scan_base='scan_001')
    p_left.side_sign = 'positive'
    p_left.side_label = 'left'
    p_right = Plot(row='scan', letter='1', z_bounds=(0.0, 20.0), out_dir='.', scan_base='scan_001')
    p_right.side_sign = 'negative'
    p_right.side_label = 'right'

    rec_l = analyze_plot(p_left, data, keep_idx, fused_np, 'scan_001', cfg, ['scan', 'scan'], 1000.0, 1.0)
    rec_r = analyze_plot(p_right, data, keep_idx, fused_np, 'scan_001', cfg, ['scan', 'scan'], 1000.0, 1.0)

    assert rec_l['points'] == 2, rec_l
    assert rec_r['points'] == 2, rec_r
    assert rec_l['scan'] == 'scan_001_left', rec_l
    assert rec_r['scan'] == 'scan_001_right', rec_r

if __name__ == '__main__':
    test_additional_scan_side_split_smoke()
    print('PASS')
