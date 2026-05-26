from __future__ import annotations

import warnings

import numpy as np

try:
    from .fusion import fuse_by_time  # kept for import compatibility, not normally used here
except ImportError:
    from fusion import fuse_by_time


_CLAMP_WARNED = False


def _unwrap_deg(arr: np.ndarray) -> np.ndarray:
    """Unwrap degrees before interpolation to avoid 359/-1 discontinuities."""
    arr = np.asarray(arr, dtype=np.float64)
    return np.rad2deg(np.unwrap(np.deg2rad(arr)))


def _dedupe_average_source(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Sort source timestamps and average duplicate timestamp values.

    This avoids silently keeping only the first duplicate timestamp.
    """
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

    yu = ysum / counts[:, None]
    return xu, yu


def _interp_columns(
    xq: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    trim_to_overlap: bool = False,
    warn_on_clamp: bool = True,
) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Interpolate y(x) onto xq.

    If trim_to_overlap=True:
        query rows outside source timestamp range are invalid/dropped.

    If trim_to_overlap=False:
        np.interp endpoint clamping is allowed for legacy compatibility, but
        this function returns the number of clamped rows and can warn once.

    Returns:
        values, valid_query_mask, n_clamped
    """
    global _CLAMP_WARNED

    xq = np.asarray(xq, dtype=np.float64)
    x, y = _dedupe_average_source(x, y)

    if y.ndim == 1:
        y = y[:, None]

    out = np.full((xq.size, y.shape[1]), np.nan, dtype=np.float64)

    # One source sample is not a real interpolation interval. Treat as invalid
    # in both trim and non-trim modes rather than broadcasting one frozen value.
    if x.size < 2:
        return out, np.zeros(xq.size, dtype=bool), 0

    valid_q = np.isfinite(xq)
    outside = valid_q & ((xq < x[0]) | (xq > x[-1]))
    n_clamped = int(np.count_nonzero(outside))

    if trim_to_overlap:
        valid_q &= ~outside
    elif n_clamped > 0 and warn_on_clamp and not _CLAMP_WARNED:
        warnings.warn(
            "fuse_by_imu_interp used endpoint clamping because trim_to_overlap=False. "
            f"Clamped {n_clamped} query rows in this interpolation call. "
            "Set trim_to_overlap=True to drop out-of-overlap rows instead.",
            RuntimeWarning,
            stacklevel=2,
        )
        _CLAMP_WARNED = True

    if not np.any(valid_q):
        return out, valid_q, n_clamped

    for j in range(y.shape[1]):
        out[valid_q, j] = np.interp(xq[valid_q], x, y[:, j])

    return out, valid_q, n_clamped


def _choose_imu_timestamp(
    pico_np: np.ndarray,
    *,
    pico_ts_col: int,
    pico_imu_ts_col: int | None,
    min_valid: int = 2,
    meaningful_delta_s: float = 1e-3,
) -> tuple[np.ndarray, str]:
    """
    Use imu_time_s if present, finite, and meaningfully different from Pico row time.

    Otherwise use Pico time_s for IMU. This preserves legacy compatibility for
    files that do not have imu_time_s.
    """
    pico_ts = pico_np[:, pico_ts_col].astype(np.float64, copy=False)

    if pico_imu_ts_col is None or pico_np.shape[1] <= pico_imu_ts_col:
        return pico_ts, "pico_time_s"

    imu_ts = pico_np[:, pico_imu_ts_col].astype(np.float64, copy=False)
    valid = np.isfinite(imu_ts) & np.isfinite(pico_ts)

    if np.count_nonzero(valid) < min_valid:
        return pico_ts, "pico_time_s"

    max_delta = float(np.nanmax(np.abs(imu_ts[valid] - pico_ts[valid])))

    if max_delta <= meaningful_delta_s:
        return pico_ts, "pico_time_s"

    return imu_ts, "imu_time_s"


def _sorted_imu_source(
    pico_np: np.ndarray,
    imu_t: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Sort IMU samples by their chosen timestamp before unwrapping roll/pitch/yaw.

    This avoids unwrapping in row order and then reordering by imu_time_s later.
    """
    imu_t = np.asarray(imu_t, dtype=np.float64)
    valid = (
        np.isfinite(imu_t)
        & np.isfinite(pico_np[:, 2])
        & np.isfinite(pico_np[:, 3])
        & np.isfinite(pico_np[:, 4])
    )

    if not np.any(valid):
        return np.empty((0,), dtype=np.float64), np.empty((0, 3), dtype=np.float64)

    idx = np.flatnonzero(valid)
    order = np.argsort(imu_t[idx], kind="mergesort")
    idx = idx[order]

    t_sorted = imu_t[idx]

    roll_sorted = _unwrap_deg(pico_np[idx, 2])
    pitch_sorted = _unwrap_deg(pico_np[idx, 3])
    yaw_sorted = _unwrap_deg(pico_np[idx, 4])

    values_sorted = np.column_stack([roll_sorted, pitch_sorted, yaw_sorted])
    return t_sorted, values_sorted


def _sorted_encoder_source(
    pico_np: np.ndarray,
    pico_t: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Sort encoder samples by Pico timestamp."""
    pico_t = np.asarray(pico_t, dtype=np.float64)
    encoder = pico_np[:, 1].astype(np.float64, copy=False)

    valid = np.isfinite(pico_t) & np.isfinite(encoder)

    if not np.any(valid):
        return np.empty((0,), dtype=np.float64), np.empty((0,), dtype=np.float64)

    idx = np.flatnonzero(valid)
    order = np.argsort(pico_t[idx], kind="mergesort")
    idx = idx[order]

    return pico_t[idx], encoder[idx]


def fuse_by_imu_interp(
    lidar_np: np.ndarray,
    pico_np: np.ndarray,
    lidar_ts_col: int = 0,
    pico_ts_col: int = 0,
    pico_imu_ts_col: int = 6,
    trim_to_overlap: bool = False,
    verbose: bool = False,
) -> np.ndarray:
    """
    Direct-stream IMU interpolation fusion.

    Old behavior was two-stage:
      1) IMU angles: imu_time_s -> Pico time_s
      2) encoder + IMU: Pico time_s -> LiDAR time_s

    This version avoids the double interpolation:
      - encoder uses Pico time_s -> LiDAR time_s
      - roll/pitch/yaw use imu_time_s -> LiDAR time_s when available
      - if imu_time_s is unavailable/invalid, IMU falls back to Pico time_s

    Output columns remain:
      [0] fused_time_s
      [1] phi
      [2] theta
      [3] dist_mm
      [4] rssi
      [5] encoder
      [6] roll_deg
      [7] pitch_deg
      [8] yaw_deg

    Note:
      Column 0 is the LiDAR stream time basis. In PPS fusion, column 0 is
      PPS-phase time. Downstream code should treat column 0 mainly as an
      ordering/interpolation time unless it explicitly knows the fusion method.
    """
    if lidar_np.size == 0 or pico_np.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    if lidar_np.shape[1] <= max(lidar_ts_col, 4):
        return np.empty((0, 9), dtype=np.float32)

    # Need at least time_s, encoder, roll, pitch, yaw.
    # Missing imu_time_s is okay; missing roll/pitch/yaw is not useful here.
    if pico_np.shape[1] <= max(pico_ts_col, 4):
        return np.empty((0, 9), dtype=np.float32)

    lidar_t = lidar_np[:, lidar_ts_col].astype(np.float64, copy=False)
    pico_t = pico_np[:, pico_ts_col].astype(np.float64, copy=False)

    imu_t, imu_ts_source = _choose_imu_timestamp(
        pico_np,
        pico_ts_col=pico_ts_col,
        pico_imu_ts_col=pico_imu_ts_col,
    )

    enc_t, enc_values = _sorted_encoder_source(pico_np, pico_t)
    imu_t_sorted, imu_values = _sorted_imu_source(pico_np, imu_t)

    enc_y, enc_valid, enc_clamped = _interp_columns(
        lidar_t,
        enc_t,
        enc_values,
        trim_to_overlap=trim_to_overlap,
    )

    imu_y, imu_valid, imu_clamped = _interp_columns(
        lidar_t,
        imu_t_sorted,
        imu_values,
        trim_to_overlap=trim_to_overlap,
    )

    keep = enc_valid & imu_valid & np.isfinite(lidar_t)

    if not np.any(keep):
        return np.empty((0, 9), dtype=np.float32)

    Luse = lidar_np[keep]
    t_use = lidar_t[keep]
    enc_use = enc_y[keep, 0]
    imu_use = imu_y[keep, :]

    out = np.empty((Luse.shape[0], 9), dtype=np.float32)

    out[:, 0] = t_use.astype(np.float32, copy=False)
    out[:, 1:5] = Luse[:, 1:5].astype(np.float32, copy=False)
    out[:, 5] = enc_use.astype(np.float32, copy=False)
    out[:, 6] = imu_use[:, 0].astype(np.float32, copy=False)
    out[:, 7] = imu_use[:, 1].astype(np.float32, copy=False)
    out[:, 8] = imu_use[:, 2].astype(np.float32, copy=False)

    # Defensive final sort so imu_interp and PPS fusion both return ordered rows.
    order = np.argsort(out[:, 0].astype(np.float64), kind="mergesort")
    out = out[order]

    if verbose:
        dropped = int(lidar_np.shape[0] - out.shape[0])
        print(
            "[IMU_INTERP] "
            f"imu_ts_source={imu_ts_source} "
            f"trim_to_overlap={trim_to_overlap} "
            f"in_rows={lidar_np.shape[0]} "
            f"out_rows={out.shape[0]} "
            f"dropped={dropped} "
            f"enc_clamped={enc_clamped} "
            f"imu_clamped={imu_clamped}"
        )

    return out