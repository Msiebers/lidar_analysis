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


def _pps_bounds(arr: np.ndarray) -> dict[int, tuple[int, int]]:
    """Return start/end slice bounds for each unique PPS value in a sorted array."""
    uniq, idx, cnts = np.unique(arr, return_index=True, return_counts=True)
    return {int(v): (int(s), int(s + c)) for v, s, c in zip(uniq, idx, cnts)}


def fuse_by_pps(
    lidar_np: np.ndarray,
    pico_np: np.ndarray,
    lidar_ts_col: int = 0,
    pico_ts_col: int = 0,
    lidar_pps_col: int = 5,
    pico_pps_col: int = 5,
) -> np.ndarray:
    """
    Fuse LiDAR and Pico/IMU streams within shared PPS buckets.

    Assumes:
      - lidar_np[:, lidar_ts_col] is lidar time_s
      - pico_np[:, pico_ts_col]  is pico time_s
      - lidar_np[:, lidar_pps_col] and pico_np[:, pico_pps_col] are PPS counters
      - LiDAR columns 1:5 are [phi, theta, dist_mm, rssi]
      - Pico columns:
          [1] count
          [2] roll_deg
          [3] pitch_deg
          [4] yaw_deg

    For each shared PPS bucket:
      - time is re-anchored within the bucket
      - encoder is linearly interpolated onto LiDAR times
      - roll/pitch/yaw are linearly interpolated onto LiDAR times

    Returns array with columns:
      [0] fused_time
      [1] phi
      [2] theta
      [3] dist_mm
      [4] rssi
      [5] encoder
      [6] roll_deg
      [7] pitch_deg
      [8] yaw_deg
    """
    if lidar_np.size == 0 or pico_np.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    lid_pps = lidar_np[:, lidar_pps_col].astype(np.int32, copy=False)
    pic_pps = pico_np[:, pico_pps_col].astype(np.int32, copy=False)

    shared_pps = np.intersect1d(np.unique(lid_pps), np.unique(pic_pps))
    if shared_pps.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    lid_ord = np.argsort(lid_pps, kind="mergesort")
    pic_ord = np.argsort(pic_pps, kind="mergesort")

    L = lidar_np[lid_ord]
    P = pico_np[pic_ord]

    lid_pps_sorted = lid_pps[lid_ord]
    pic_pps_sorted = pic_pps[pic_ord]

    lid_map = _pps_bounds(lid_pps_sorted)
    pic_map = _pps_bounds(pic_pps_sorted)

    total_rows = sum(lid_map[p][1] - lid_map[p][0] for p in shared_pps)
    out = np.empty((total_rows, 9), dtype=np.float32)
    w = 0

    for pps in shared_pps:
        ls, le = lid_map[pps]
        ps, pe = pic_map[pps]

        Lpps = L[ls:le]
        Ppps = P[ps:pe]

        if Lpps.size == 0 or Ppps.size == 0:
            continue

        # Re-anchor time within each PPS bucket
        lt = Lpps[:, lidar_ts_col].astype(np.float64) - float(Lpps[0, lidar_ts_col]) + float(pps)
        pt = Ppps[:, pico_ts_col].astype(np.float64)  - float(Ppps[0, pico_ts_col]) + float(pps)

        enc = _lin_interp(lt, pt, Ppps[:, 1])
        roll = _lin_interp(lt, pt, _unwrap_deg(Ppps[:, 2]))
        pitch = _lin_interp(lt, pt, _unwrap_deg(Ppps[:, 3]))
        yaw = _lin_interp(lt, pt, _unwrap_deg(Ppps[:, 4]))

        n = Lpps.shape[0]
        out[w:w + n, 0] = lt.astype(np.float32, copy=False)
        out[w:w + n, 1:5] = Lpps[:, 1:5].astype(np.float32, copy=False)
        out[w:w + n, 5] = enc.astype(np.float32, copy=False)
        out[w:w + n, 6] = roll.astype(np.float32, copy=False)
        out[w:w + n, 7] = pitch.astype(np.float32, copy=False)
        out[w:w + n, 8] = yaw.astype(np.float32, copy=False)
        w += n

    if w == 0:
        return np.empty((0, 9), dtype=np.float32)

    return out[:w]