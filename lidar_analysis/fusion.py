# fusion.py
from __future__ import annotations

import numpy as np


def _unwrap_deg(arr: np.ndarray) -> np.ndarray:
    """Unwrap degrees before interpolation to avoid 359/-1 discontinuities."""
    arr = np.asarray(arr, np.float64)
    return np.rad2deg(np.unwrap(np.deg2rad(arr)))


def _dedupe_average_source(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Sort source timestamps and average duplicate timestamp values."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    if y.ndim == 1:
        y = y[:, None]

    valid = np.isfinite(x) & np.all(np.isfinite(y), axis=1)
    x = x[valid]
    y = y[valid]

    if x.size == 0:
        return x, y

    order = np.argsort(x, kind="mergesort")
    x = x[order]
    y = y[order]

    xu, inverse = np.unique(x, return_inverse=True)
    if xu.size == x.size:
        return x, y

    ysum = np.zeros((xu.size, y.shape[1]), dtype=np.float64)
    counts = np.zeros(xu.size, dtype=np.float64)
    np.add.at(ysum, inverse, y)
    np.add.at(counts, inverse, 1.0)
    return xu, ysum / counts[:, None]


def _interp_columns(
    xq: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    trim_to_overlap: bool = True,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Interpolate columns, returning values, valid query mask, and clamped count."""
    xq = np.asarray(xq, dtype=np.float64)
    x, y = _dedupe_average_source(x, y)

    if y.ndim == 1:
        y = y[:, None]

    out = np.full((xq.size, y.shape[1]), np.nan, dtype=np.float64)
    if x.size < 2:
        return out, np.zeros(xq.size, dtype=bool), 0

    valid_q = np.isfinite(xq)
    outside = valid_q & ((xq < x[0]) | (xq > x[-1]))
    n_clamped = int(np.count_nonzero(outside))

    if trim_to_overlap:
        valid_q &= ~outside

    if not np.any(valid_q):
        return out, valid_q, n_clamped

    for j in range(y.shape[1]):
        out[valid_q, j] = np.interp(xq[valid_q], x, y[:, j])

    return out, valid_q, n_clamped


def _lin_interp(xq: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Safe 1D linear interpolation with x deduped/monotonic.

    - xq: query points
    - x : sample locations
    - y : sample values
    """
    values, _valid, _clamped = _interp_columns(xq, x, y, trim_to_overlap=False)
    return values[:, 0]


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
