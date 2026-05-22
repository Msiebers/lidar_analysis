#!/usr/bin/env python3
import numpy as np
import pandas as pd

from lidar_analysis.pointcloud_ops import apply_pointcloud_ops


def main() -> None:
    df = pd.DataFrame(
        {
            "X": [0.0, 0.0, 0.1, 0.1, 1.0],
            "Y": [0.0, 0.01, 0.0, 0.01, 1.0],
            "Z": [0.0, 0.01, 0.0, 0.01, 1.0],
            "RSSI": [10.0, 12.0, 8.0, 11.0, 999.0],
            "scan_meta": [1, 1, 1, 1, 1],
        }
    )
    ops = [
        {"op": "scalar_range_filter", "field": "RSSI", "min": 5.0, "max": 100.0},
        {"op": "sor_filter", "mean_k": 2, "stddev_mul_thresh": 1.0},
        {"op": "voxel_grid", "voxel_size": 0.05},
    ]

    out, traits, diag = apply_pointcloud_ops(df, ops, default_backend="scipy")
    assert "scan_meta" in out.columns
    assert len(out) <= 4
    assert traits.get("voxel_count") is not None
    assert diag["operation_order"] == ["scalar_range_filter", "sor_filter", "voxel_grid"]

    # bilateral updates scalar but preserves shape
    out2, _, _ = apply_pointcloud_ops(df, [{"op": "bilateral_scalar_filter", "field": "RSSI"}])
    assert out2.shape == df.shape

    print("PASS")


if __name__ == "__main__":
    main()
