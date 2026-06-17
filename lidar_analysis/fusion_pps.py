from __future__ import annotations

import numpy as np

try:
    from .fusion import _interp_columns as _shared_interp_columns
    from .fusion import _unwrap_deg, fuse_by_time  # kept for direct import compatibility
except ImportError:
    from fusion import _interp_columns as _shared_interp_columns
    from fusion import _unwrap_deg, fuse_by_time


def _sort_by_pps_time(arr: np.ndarray, ts_col: int, pps_col: int) -> np.ndarray:
    """Stable sort by PPS counter, then timestamp."""
    pps = arr[:, pps_col].astype(np.int64, copy=False)
    ts = arr[:, ts_col].astype(np.float64, copy=False)
    order = np.lexsort((ts, pps))
    return arr[order]


def _pps_bounds(pps_sorted: np.ndarray) -> dict[int, tuple[int, int]]:
    """Return start/end slice bounds for each unique PPS value in a sorted PPS array."""
    uniq, idx, cnts = np.unique(pps_sorted, return_index=True, return_counts=True)
    return {
        int(v): (int(s), int(s + c))
        for v, s, c in zip(uniq, idx, cnts)
    }


def _stream_first_times(
    arr_sorted: np.ndarray,
    ts_col: int,
    pps_col: int,
) -> tuple[np.ndarray, np.ndarray, dict[int, tuple[int, int]]]:
    """
    Return PPS values, first timestamp per PPS bucket, and bounds.
    arr_sorted must already be sorted by PPS then timestamp.
    """
    pps = arr_sorted[:, pps_col].astype(np.int64, copy=False)
    ts = arr_sorted[:, ts_col].astype(np.float64, copy=False)

    bounds = _pps_bounds(pps)
    buckets = np.array(sorted(bounds.keys()), dtype=np.float64)
    first_times = np.array([float(ts[bounds[int(p)][0]]) for p in buckets], dtype=np.float64)

    return buckets, first_times, bounds


def _linear_fit_edges(
    arr_sorted: np.ndarray,
    ts_col: int,
    pps_col: int,
    *,
    min_buckets: int = 3,
    robust_refit: bool = True,
) -> tuple[dict[int, float], dict[str, float]]:
    """
    Estimate PPS edge/proxy timestamps using a smooth linear fit.

    We fit:
        first_sample_time[p] = slope * p + intercept

    and use the fitted line as the per-bucket edge/proxy. This intentionally
    removes per-bucket first-sample jitter. If the PPS structure is too sparse
    for a meaningful fit, this raises ValueError so the caller can return empty
    and the user can intentionally choose imu_interp/interp instead.
    """
    buckets, first_times, _bounds = _stream_first_times(arr_sorted, ts_col, pps_col)

    finite = np.isfinite(buckets) & np.isfinite(first_times)
    buckets = buckets[finite]
    first_times = first_times[finite]

    if buckets.size < min_buckets:
        raise ValueError(
            f"Need at least {min_buckets} PPS buckets for linear-fit PPS fusion; "
            f"got {buckets.size}"
        )

    def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
        A = np.column_stack([x, np.ones_like(x)])
        slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
        return float(slope), float(intercept)

    slope, intercept = fit_line(buckets, first_times)
    pred = slope * buckets + intercept
    resid = first_times - pred

    used = np.ones_like(buckets, dtype=bool)

    if robust_refit and buckets.size >= max(min_buckets + 2, 6):
        med = float(np.median(resid))
        mad = float(np.median(np.abs(resid - med)))

        if mad > 0 and np.isfinite(mad):
            robust_sigma = 1.4826 * mad
            thresh = 4.0 * robust_sigma
            keep = np.abs(resid - med) <= thresh

            if np.count_nonzero(keep) >= min_buckets and np.count_nonzero(keep) < buckets.size:
                used = keep
                slope, intercept = fit_line(buckets[keep], first_times[keep])
                pred = slope * buckets + intercept
                resid = first_times - pred

    edges = {
        int(p): float(slope * float(p) + intercept)
        for p in buckets
    }

    used_resid = resid[used]

    diag = {
        "n_buckets": float(buckets.size),
        "n_used": float(np.count_nonzero(used)),
        "slope": float(slope),
        "intercept": float(intercept),
        "resid_std": float(np.std(used_resid)) if used_resid.size else float("nan"),
        "resid_max_abs": float(np.max(np.abs(used_resid))) if used_resid.size else float("nan"),
    }

    return edges, diag


def _phase_time(
    ts: np.ndarray,
    pps: np.ndarray,
    edges: dict[int, float],
) -> np.ndarray:
    """
    Convert stream timestamps into PPS-phase time:

        phase_time = timestamp - edge[pps] + pps

    Rows whose PPS edge is unavailable become NaN.
    """
    ts = np.asarray(ts, dtype=np.float64)
    pps = np.asarray(pps, dtype=np.int64)

    out = np.full(ts.shape, np.nan, dtype=np.float64)

    for p in np.unique(pps):
        p_int = int(p)
        edge = edges.get(p_int)
        if edge is None:
            continue
        m = pps == p_int
        out[m] = ts[m] - edge + float(p_int)

    return out


def _interp_columns(
    xq: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    trim_to_overlap: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Interpolate y(x) onto xq.

    If trim_to_overlap=True, query rows outside the source range are invalid.
    This avoids silent endpoint clamping.
    """
    out, valid_q, _n_clamped = _shared_interp_columns(xq, x, y, trim_to_overlap=trim_to_overlap)
    return out, valid_q


def _window_from_bucket_map(
    table_sorted: np.ndarray,
    bucket_map: dict[int, tuple[int, int]],
    pps_value: int,
    *,
    neighbor_buckets: int = 1,
) -> np.ndarray:
    """
    Return rows from PPS buckets [p-k, ..., p+k] using precomputed bounds.
    This avoids scanning the whole stream for every LiDAR bucket.
    """
    parts: list[np.ndarray] = []

    for q in range(int(pps_value) - int(neighbor_buckets), int(pps_value) + int(neighbor_buckets) + 1):
        bounds = bucket_map.get(q)
        if bounds is None:
            continue
        s, e = bounds
        parts.append(table_sorted[s:e])

    if not parts:
        return table_sorted[:0]

    return np.vstack(parts)


def _build_value_stream(
    *,
    ts: np.ndarray,
    pps: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    """
    Build sorted stream table:
        timestamp, pps, value_0, value_1, ...
    """
    ts = np.asarray(ts, dtype=np.float64)
    pps = np.asarray(pps, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)

    if values.ndim == 1:
        values = values[:, None]

    valid = (
        np.isfinite(ts)
        & np.isfinite(pps)
        & (pps >= 0)
        & np.all(np.isfinite(values), axis=1)
    )

    if not np.any(valid):
        return np.empty((0, 2 + values.shape[1]), dtype=np.float64)

    table = np.column_stack([
        ts[valid],
        pps[valid].astype(np.int64),
        values[valid],
    ]).astype(np.float64)

    return _sort_by_pps_time(table, ts_col=0, pps_col=1)


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
    Otherwise use Pico time_s for IMU.
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


def _edge_disagreement_stats(
    a: dict[int, float],
    b: dict[int, float],
    shared_pps: np.ndarray,
) -> tuple[float, float]:
    diffs = []

    for p in shared_pps:
        p_int = int(p)
        if p_int in a and p_int in b:
            diffs.append(float(a[p_int] - b[p_int]))

    if not diffs:
        return float("nan"), float("nan")

    d = np.asarray(diffs, dtype=np.float64)
    return float(np.std(d)), float(np.max(np.abs(d - np.mean(d))))


def fuse_by_pps(
    lidar_np: np.ndarray,
    pico_np: np.ndarray,
    lidar_ts_col: int = 0,
    pico_ts_col: int = 0,
    lidar_pps_col: int = 5,
    pico_pps_col: int = 5,
    pico_imu_ts_col: int | None = 6,
    trim_to_overlap: bool = True,
    neighbor_buckets: int = 1,
    min_fit_buckets: int = 3,
    verbose: bool = False,
    min_pico_samples_per_pps: int | None = None,  # accepted for old-call compatibility; not used
) -> np.ndarray:
    """
    Strict PPS-locked fusion of LiDAR and Pico/IMU streams.

    Uses:
      - linear-fit PPS edge/proxy estimates across buckets
      - separate encoder and IMU timestamp streams
      - imu_time_s directly when available
      - adjacent-bucket source windows
      - no silent endpoint clamping by default

    Input assumptions
    -----------------
    LiDAR columns:
      [0] time_s
      [1] phi
      [2] theta
      [3] dist_mm
      [4] rssi
      [5] pps

    Pico columns:
      [0] time_s
      [1] encoder count
      [2] roll_deg
      [3] pitch_deg
      [4] yaw_deg
      [5] pps
      [6] imu_time_s, optional

    Output columns
    --------------
      [0] fused_time_pps_s
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

    if lidar_np.shape[1] <= max(lidar_ts_col, lidar_pps_col, 4):
        return np.empty((0, 9), dtype=np.float32)

    if pico_np.shape[1] <= max(pico_ts_col, pico_pps_col, 4):
        return np.empty((0, 9), dtype=np.float32)

    # LiDAR stream.
    lid_ts = lidar_np[:, lidar_ts_col].astype(np.float64, copy=False)
    lid_pps_float = lidar_np[:, lidar_pps_col].astype(np.float64, copy=False)

    lid_valid = np.isfinite(lid_ts) & np.isfinite(lid_pps_float) & (lid_pps_float >= 0)
    L0 = lidar_np[lid_valid]

    if L0.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    L = _sort_by_pps_time(L0, lidar_ts_col, lidar_pps_col)
    lid_pps = L[:, lidar_pps_col].astype(np.int64, copy=False)
    lid_map = _pps_bounds(lid_pps)

    # Encoder stream: Pico time_s.
    pico_ts = pico_np[:, pico_ts_col].astype(np.float64, copy=False)
    pico_pps = pico_np[:, pico_pps_col].astype(np.float64, copy=False)
    encoder = pico_np[:, 1].astype(np.float64, copy=False)

    enc_table = _build_value_stream(
        ts=pico_ts,
        pps=pico_pps,
        values=encoder,
    )

    # IMU stream: imu_time_s when meaningful, otherwise Pico time_s.
    imu_ts, imu_ts_source = _choose_imu_timestamp(
        pico_np,
        pico_ts_col=pico_ts_col,
        pico_imu_ts_col=pico_imu_ts_col,
    )

    imu_values = np.column_stack([
        _unwrap_deg(pico_np[:, 2]),
        _unwrap_deg(pico_np[:, 3]),
        _unwrap_deg(pico_np[:, 4]),
    ])

    imu_table = _build_value_stream(
        ts=imu_ts,
        pps=pico_pps,
        values=imu_values,
    )

    if enc_table.size == 0 or imu_table.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    enc_pps = enc_table[:, 1].astype(np.int64, copy=False)
    imu_pps = imu_table[:, 1].astype(np.int64, copy=False)

    enc_map = _pps_bounds(enc_pps)
    imu_map = _pps_bounds(imu_pps)

    # Strict linear-fit PPS edge estimates.
    try:
        lid_edges, lid_diag = _linear_fit_edges(
            L,
            ts_col=lidar_ts_col,
            pps_col=lidar_pps_col,
            min_buckets=min_fit_buckets,
        )
        enc_edges, enc_diag = _linear_fit_edges(
            enc_table,
            ts_col=0,
            pps_col=1,
            min_buckets=min_fit_buckets,
        )
        imu_edges, imu_diag = _linear_fit_edges(
            imu_table,
            ts_col=0,
            pps_col=1,
            min_buckets=min_fit_buckets,
        )
    except ValueError as e:
        if verbose:
            print(f"[PPS_FUSION] {e}")
        return np.empty((0, 9), dtype=np.float32)

    shared_pps = np.intersect1d(lid_pps, enc_pps)
    shared_pps = np.intersect1d(shared_pps, imu_pps)

    if shared_pps.size == 0:
        return np.empty((0, 9), dtype=np.float32)

    enc_edge_std, enc_edge_max = _edge_disagreement_stats(lid_edges, enc_edges, shared_pps)
    imu_edge_std, imu_edge_max = _edge_disagreement_stats(lid_edges, imu_edges, shared_pps)

    if verbose:
        print(
            "[PPS_FUSION] "
            f"lidar_buckets={len(lid_map)} "
            f"encoder_buckets={len(enc_map)} "
            f"imu_buckets={len(imu_map)} "
            f"shared_buckets={shared_pps.size} "
            f"imu_ts_source={imu_ts_source} "
            f"trim_to_overlap={trim_to_overlap} "
            f"neighbor_buckets={neighbor_buckets}"
        )
        print(
            "[PPS_FUSION] "
            f"edge_resid_std: lidar={lid_diag['resid_std']:.6g} "
            f"encoder={enc_diag['resid_std']:.6g} "
            f"imu={imu_diag['resid_std']:.6g}; "
            f"edge_disagree_std: lidar-encoder={enc_edge_std:.6g} "
            f"lidar-imu={imu_edge_std:.6g}; "
            f"edge_disagree_max_centered: lidar-encoder={enc_edge_max:.6g} "
            f"lidar-imu={imu_edge_max:.6g}"
        )

    chunks: list[np.ndarray] = []
    dropped_no_overlap = 0

    # Optional boundary diagnostics.
    boundary_yaw_steps: list[float] = []
    prev_last_yaw: float | None = None

    for pps in shared_pps:
        p = int(pps)

        if p not in lid_map or p not in lid_edges:
            continue

        ls, le = lid_map[p]
        Lpps = L[ls:le]

        if Lpps.size == 0:
            continue

        lt = (
            Lpps[:, lidar_ts_col].astype(np.float64, copy=False)
            - lid_edges[p]
            + float(p)
        )

        enc_win = _window_from_bucket_map(
            enc_table,
            enc_map,
            p,
            neighbor_buckets=neighbor_buckets,
        )
        imu_win = _window_from_bucket_map(
            imu_table,
            imu_map,
            p,
            neighbor_buckets=neighbor_buckets,
        )

        if enc_win.size == 0 or imu_win.size == 0:
            dropped_no_overlap += Lpps.shape[0]
            continue

        enc_x = _phase_time(
            enc_win[:, 0],
            enc_win[:, 1].astype(np.int64, copy=False),
            enc_edges,
        )
        imu_x = _phase_time(
            imu_win[:, 0],
            imu_win[:, 1].astype(np.int64, copy=False),
            imu_edges,
        )

        enc_y, enc_valid = _interp_columns(
            lt,
            enc_x,
            enc_win[:, 2],
            trim_to_overlap=trim_to_overlap,
        )
        imu_y, imu_valid = _interp_columns(
            lt,
            imu_x,
            imu_win[:, 2:5],
            trim_to_overlap=trim_to_overlap,
        )

        keep = enc_valid & imu_valid

        if not np.any(keep):
            dropped_no_overlap += Lpps.shape[0]
            continue

        dropped_no_overlap += int(keep.size - np.count_nonzero(keep))

        Luse = Lpps[keep]
        lt_use = lt[keep]
        enc_use = enc_y[keep, 0]
        imu_use = imu_y[keep, :]

        n = Luse.shape[0]
        out = np.empty((n, 9), dtype=np.float32)

        out[:, 0] = lt_use.astype(np.float32, copy=False)
        out[:, 1:5] = Luse[:, 1:5].astype(np.float32, copy=False)
        out[:, 5] = enc_use.astype(np.float32, copy=False)
        out[:, 6] = imu_use[:, 0].astype(np.float32, copy=False)
        out[:, 7] = imu_use[:, 1].astype(np.float32, copy=False)
        out[:, 8] = imu_use[:, 2].astype(np.float32, copy=False)

        if verbose and out.shape[0] > 0:
            first_yaw = float(out[0, 8])
            last_yaw = float(out[-1, 8])
            if prev_last_yaw is not None:
                boundary_yaw_steps.append(first_yaw - prev_last_yaw)
            prev_last_yaw = last_yaw

        chunks.append(out)

    if not chunks:
        return np.empty((0, 9), dtype=np.float32)

    fused = np.vstack(chunks).astype(np.float32, copy=False)

    # Defensive final ordering.
    order = np.argsort(fused[:, 0].astype(np.float64), kind="mergesort")
    fused = fused[order]

    if verbose:
        msg = (
            "[PPS_FUSION] "
            f"out_rows={fused.shape[0]} "
            f"dropped_no_overlap={dropped_no_overlap}"
        )

        if boundary_yaw_steps:
            steps = np.asarray(boundary_yaw_steps, dtype=np.float64)
            msg += (
                f" boundary_yaw_step_std={float(np.std(steps)):.6g}"
                f" boundary_yaw_step_p95_abs={float(np.percentile(np.abs(steps), 95)):.6g}"
            )

        print(msg)

    return fused
