from __future__ import annotations

import numpy as np

try:
    from .fusion import _lin_interp, _unwrap_deg, fuse_by_time
except ImportError:
    from fusion import _lin_interp, _unwrap_deg, fuse_by_time


def fuse_by_imu_interp(
    lidar_np: np.ndarray,
    pico_np: np.ndarray,
    lidar_ts_col: int = 0,
    pico_ts_col: int = 0,
    pico_imu_ts_col: int = 6,
    trim_to_overlap: bool = False,
) -> np.ndarray:
    """
    Two-stage fusion:
      1) interpolate IMU angles (roll/pitch/yaw) from imu_time_s -> pico time_s
      2) interpolate encoder+IMU state from pico time_s -> lidar time_s
    Falls back safely to fuse_by_time if imu_time_s is unavailable/invalid.
    """
    if lidar_np.size == 0 or pico_np.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    if pico_np.shape[1] <= pico_imu_ts_col:
        return fuse_by_time(lidar_np, pico_np, lidar_ts_col=lidar_ts_col, pico_ts_col=pico_ts_col, trim_to_overlap=trim_to_overlap)

    tP = pico_np[:, pico_ts_col].astype(np.float64, copy=False)
    tI = pico_np[:, pico_imu_ts_col].astype(np.float64, copy=False)

    valid = np.isfinite(tI)
    if np.count_nonzero(valid) < 2:
        return fuse_by_time(lidar_np, pico_np, lidar_ts_col=lidar_ts_col, pico_ts_col=pico_ts_col, trim_to_overlap=trim_to_overlap)

    if np.nanmax(np.abs(tI[valid] - tP[valid])) < 1e-9:
        return fuse_by_time(lidar_np, pico_np, lidar_ts_col=lidar_ts_col, pico_ts_col=pico_ts_col, trim_to_overlap=trim_to_overlap)

    roll_src = _unwrap_deg(pico_np[:, 2])
    pitch_src = _unwrap_deg(pico_np[:, 3])
    yaw_src = _unwrap_deg(pico_np[:, 4])

    roll_on_tp = _lin_interp(tP, tI[valid], roll_src[valid])
    pitch_on_tp = _lin_interp(tP, tI[valid], pitch_src[valid])
    yaw_on_tp = _lin_interp(tP, tI[valid], yaw_src[valid])

    pico_stage = np.array(pico_np[:, :6], copy=True)
    pico_stage[:, 2] = roll_on_tp
    pico_stage[:, 3] = pitch_on_tp
    pico_stage[:, 4] = yaw_on_tp

    return fuse_by_time(lidar_np, pico_stage, lidar_ts_col=lidar_ts_col, pico_ts_col=pico_ts_col, trim_to_overlap=trim_to_overlap)
