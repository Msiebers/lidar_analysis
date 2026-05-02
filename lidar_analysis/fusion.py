# fusion.py
from __future__ import annotations

import numpy as np


def _unwrap_deg(arr: np.ndarray) -> np.ndarray:
    """Unwrap degrees to avoid 359→-359 discontinuities before interpolation."""
    arr = np.asarray(arr, np.float64)
    return np.rad2deg(np.unwrap(np.deg2rad(arr)))


def _lin_interp(xq: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Safe 1D linear interpolation with x deduped/monotonic.

    - xq: query points
    - x : sample locations
    - y : sample values
    """
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    xq = np.asarray(xq, np.float64)

    if x.size == 0:
        return np.full_like(xq, np.nan, dtype=np.float64)

    xu, idx = np.unique(x, return_index=True)
    yu = y[idx]
    return np.interp(xq, xu, yu)


def fuse_by_time(
    lidar_np: np.ndarray,
    pico_np: np.ndarray,
    lidar_ts_col: int = 0,
    pico_ts_col: int = 0,
    trim_to_overlap: bool = False,
) -> np.ndarray:
    """
    Fuse LiDAR and Pico/IMU streams using the already Pi-normalized `time_s`.

    Assumes:
      - lidar_np[:, lidar_ts_col] is `time_s` from lidar_logger
      - pico_np[:, pico_ts_col]  is `time_s` from serial_logger
      - Both have been aligned to the same shared_start_time on the Pi.

    Returns array with columns:
      [0] time_s          (LiDAR time)
      [1] phi
      [2] theta
      [3] dist_mm
      [4] rssi
      [5] encoder         (interp from Pico)
      [6] roll_deg        (interp from Pico)
      [7] pitch_deg       (interp from Pico)
      [8] yaw_deg         (interp from Pico)
    """
    if lidar_np.size == 0 or pico_np.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    # --- Time axes ---
    tL = lidar_np[:, lidar_ts_col].astype(np.float64)
    tP = pico_np[:, pico_ts_col].astype(np.float64)

    # Optionally keep only the time region covered by Pico
    if trim_to_overlap:
        tP_min, tP_max = np.nanmin(tP), np.nanmax(tP)
        mask = (tL >= tP_min) & (tL <= tP_max)
        if not np.any(mask):
            print("[fusion] No overlapping time between LiDAR and Pico.")
            return np.empty((0, 9), dtype=np.float32)
        tL_use = tL[mask]
        lidar_use = lidar_np[mask]
    else:
        tL_use = tL
        lidar_use = lidar_np

    # --- Allocate output (LiDAR rows preserved or masked) ---
    out = np.empty((lidar_use.shape[0], 9), dtype=np.float32)
    out[:, 0] = tL_use.astype(np.float32)
    out[:, 1:5] = lidar_use[:, 1:5].astype(np.float32)

    # --- Interpolate Pico data onto LiDAR times ---
    enc   = _lin_interp(tL_use, tP, pico_np[:, 1])                 # count
    roll  = _lin_interp(tL_use, tP, _unwrap_deg(pico_np[:, 2]))    # roll_deg
    pitch = _lin_interp(tL_use, tP, _unwrap_deg(pico_np[:, 3]))    # pitch_deg
    yaw   = _lin_interp(tL_use, tP, _unwrap_deg(pico_np[:, 4]))    # yaw_deg

    out[:, 5] = enc.astype(np.float32)
    out[:, 6] = roll.astype(np.float32)
    out[:, 7] = pitch.astype(np.float32)
    out[:, 8] = yaw.astype(np.float32)

    return out
