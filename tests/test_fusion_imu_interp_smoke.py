#!/usr/bin/env python3
import numpy as np

from lidar_analysis.fusion import fuse_by_time
from lidar_analysis.fusion_imu_interp import fuse_by_imu_interp


def main() -> None:
    lidar = np.array([
        [0.0, 0.1, 0.2, 1000.0, 50.0, 1.0],
        [1.0, 0.1, 0.2, 1000.0, 50.0, 1.0],
        [2.0, 0.1, 0.2, 1000.0, 50.0, 1.0],
    ], dtype=np.float32)

    pico_base = np.array([
        [0.0, 10.0, 0.0, 0.0, 0.0, 1.0],
        [1.0, 20.0, 10.0, 0.0, 0.0, 1.0],
        [2.0, 30.0, 20.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)

    # imu_time_s offset should change orientation interpolation
    pico_imu = np.column_stack([pico_base, np.array([0.5, 1.5, 2.5], dtype=np.float64)])
    out_interp = fuse_by_time(lidar, pico_base)
    out_imu = fuse_by_imu_interp(lidar, pico_imu)
    assert out_interp.shape[1] == out_imu.shape[1] == 9
    assert not np.allclose(out_interp[:, 6:9], out_imu[:, 6:9])

    # missing imu_time_s falls back safely
    out_fallback_missing = fuse_by_imu_interp(lidar, pico_base)
    assert np.allclose(out_fallback_missing, out_interp, equal_nan=True)

    # imu_time_s identical to time_s falls back to interp-equivalent behavior
    pico_same = np.column_stack([pico_base, pico_base[:, 0]])
    out_fallback_same = fuse_by_imu_interp(lidar, pico_same)
    assert np.allclose(out_fallback_same, out_interp, equal_nan=True)

    print('PASS')


if __name__ == '__main__':
    main()
