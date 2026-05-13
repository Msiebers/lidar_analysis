import math
import os
import sys
from warnings import warn

import numpy as np
import open3d as o3d
import pandas as pd
import yaml
from scipy import stats
from scipy.spatial.transform import Rotation as R

try:
    from .config import AnalysisConfig
    from .fusion import fuse_by_time
    from .fusion_pps import fuse_by_pps
    from .topology import topology_stand_count
    from .mark_splitting import (
        build_mark_segments,
        find_marker_file_for_scan,
        marker_buffer_mm,
    )
except Exception:
    from config import AnalysisConfig
    from fusion import fuse_by_time
    from fusion_pps import fuse_by_pps
    from topology import topology_stand_count
    from mark_splitting import (
        build_mark_segments,
        find_marker_file_for_scan,
        marker_buffer_mm,
    )

# ----------------------
# Load calibration file (STRICT)
# ----------------------
def load_calibration(cart_id: str, calib_dir: str) -> dict:
    path = os.path.join(calib_dir, f"{cart_id}.yaml")
    if not os.path.exists(path):
        print(f"[Calib][ERROR] Missing: {path}")
        sys.exit(1)
    try:
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[Calib][ERROR] Could not read {path}\n{e}")
        sys.exit(1)

    required_top = ["m_per_click", "lidar_height_m", "imu_offset_m", "tilt_bias_deg"]
    missing = [k for k in required_top if k not in raw]
    if missing:
        print(f"[Calib][ERROR] Missing key(s) {missing} in {path}")
        sys.exit(1)

    try:
        m_per_click = float(raw["m_per_click"])
        lidar_height_m = float(raw["lidar_height_m"])
        lidar_wheel_offset_m = float(raw.get("lidar_wheel_offset_m", 0.0))
    except Exception as e:
        print(f"[Calib][ERROR] Non-numeric calibration values in {path}: {e}")
        sys.exit(1)

    if not (1e-6 <= m_per_click <= 5e-2):
        print(f"[Calib][ERROR] m_per_click={m_per_click} looks invalid.")
        sys.exit(1)
    if not (0.05 <= lidar_height_m <= 3.0):
        print(f"[Calib][ERROR] lidar_height_m={lidar_height_m} looks invalid.")
        sys.exit(1)

    imu = raw.get("imu_offset_m") or {}
    try:
        dx = float(imu.get("dx", 0.0))
        dy = float(imu.get("dy", 0.0))
        dz = float(imu.get("dz", 0.0))
    except Exception as e:
        print(f"[Calib][ERROR] Non-numeric imu_offset_m.{{dx,dy,dz}} in {path}: {e}")
        sys.exit(1)

    imu_offset_mm = np.array([dx, dy, dz], dtype=np.float64) * 1000.0

    tilt = raw.get("tilt_bias_deg") or {}
    if ("roll_offset_deg" not in tilt) or ("pitch_offset_deg" not in tilt):
        print(f"[Calib][ERROR] Missing tilt_bias_deg.roll_offset_deg or .pitch_offset_deg in {path}")
        sys.exit(1)
    try:
        roll_yaml = float(tilt["roll_offset_deg"])
        pitch_yaml = float(tilt["pitch_offset_deg"])
    except Exception as e:
        print(f"[Calib][ERROR] Non-numeric tilt_bias_deg values in {path}: {e}")
        sys.exit(1)

    roll_offset_deg = -roll_yaml
    pitch_offset_deg = -pitch_yaml

    calib = {
        "step_mm": m_per_click * 1000.0,
        "lidar_height_mm": lidar_height_m * 1000.0,
        "lidar_wheel_offset_mm": lidar_wheel_offset_m * 1000.0,
        "imu_offset_mm": imu_offset_mm.astype(np.float32, copy=False),
        "roll_offset_deg": float(roll_offset_deg),
        "pitch_offset_deg": float(pitch_offset_deg),
        "source_path": os.path.abspath(path),
        "_raw": {
            "roll_yaml_deg": roll_yaml,
            "pitch_yaml_deg": pitch_yaml,
        },
    }

    print(f"[Calib] Loaded {calib['source_path']}")
    print(f"   step_mm               : {calib['step_mm']:.3f} mm/click")
    print(f"   lidar_height_m        : {lidar_height_m:.3f} m")
    print(f"   lidar_wheel_offset_m  : {lidar_wheel_offset_m:.4f} m")
    print(f"   imu_offset_m          : (dx={dx:.5f}, dy={dy:.5f}, dz={dz:.5f})")
    print(f"   tilt_bias_deg (YAML, saved as opposite sign): roll={roll_yaml:.2f}, pitch={pitch_yaml:.2f}")
    print(f"   applied offsets       : roll={roll_offset_deg:.2f} deg, pitch={pitch_offset_deg:.2f} deg")
    return calib

# ======================================================================
# LiDAR-only trait helpers: LAI + height
# ======================================================================

EVEN_ZENITH_BREAKS = np.array((0, 15, 30, 45, 60, 90), dtype=float) / 180 * math.pi
UNEVEN_ZENITH_BREAKS = np.array((0, 13, 28, 43, 58, 90), dtype=float) / 180 * math.pi

def lai(lidar_data: dict, zenith_breaks: np.ndarray) -> float | None:
    """Compute LAI using the legacy gap-fraction routine."""
    distance_scans = lidar_data.get("distances")
    if distance_scans is None:
        return None
    n_scans = len(distance_scans)
    if n_scans == 0:
        return None

    mean_zenith_breaks = ((zenith_breaks[:-1] + zenith_breaks[1:]) / 2)[::-1]
    coefs = np.sin(mean_zenith_breaks) * np.cos(mean_zenith_breaks) * np.diff(zenith_breaks)

    lidar_zeniths = np.abs(lidar_data["zeniths"])

    gap_matrix = np.empty([n_scans, len(mean_zenith_breaks)])

    zen_group_inds: list[np.ndarray] = []
    for j in range(len(zenith_breaks) - 1):
        mask = (lidar_zeniths >= zenith_breaks[j]) & (lidar_zeniths < zenith_breaks[j + 1])
        inds = np.flatnonzero(mask)
        zen_group_inds.append(inds)

    for i in range(n_scans):
        scan = np.asarray(distance_scans[i], dtype=float)
        is_gap = scan > 30  # meters

        for zen_ind, group in enumerate(zen_group_inds):
            if group.size == 0:
                gap_matrix[i, zen_ind] = np.nan
            else:
                vals = is_gap[group]
                gap_matrix[i, zen_ind] = float(np.nanmean(vals.astype(float)))

    gap_fraction = np.nanmean(gap_matrix, axis=0)

    zero_inds = np.logical_or(gap_fraction == 0, np.isnan(gap_fraction))
    if np.all(zero_inds):
        return float("inf")

    if np.any(zero_inds):
        valid = ~zero_inds
        if np.any(valid):
            warn("Correcting LAI.")
            mean_thing = -np.nanmean(
                np.log(gap_fraction[valid]) * np.cos(mean_zenith_breaks)[valid]
            )
            gap_fraction[zero_inds] = np.exp(
                -mean_thing / np.cos(mean_zenith_breaks)[zero_inds]
            )
        else:
            return float("inf")

    temp = -np.log(gap_fraction) * coefs
    return float(2 * np.nansum(temp))


def height_from_world_y(data_mm: np.ndarray, alpha: float = 0.01) -> float:
    """Legacy canopy-height metric (99th percentile of Y, robust to outliers)."""
    if data_mm.size == 0:
        return float("nan")

    y_m = np.asarray(data_mm[:, 1], dtype=float) / 1000.0
    y_m = y_m[np.isfinite(y_m) & (y_m > 0.0)]
    if y_m.size == 0:
        return float("nan")

    try:
        from outliers import smirnov_grubbs as grubbs  # type: ignore[import-not-found]
    except Exception:
        med = np.median(y_m)
        mad = np.median(np.abs(y_m - med))
        if mad > 0:
            z = 0.6745 * (y_m - med) / mad
            y_use = y_m[np.abs(z) < 3.5]
        else:
            y_use = y_m
    else:
        y_use = grubbs.test(y_m, alpha=alpha) if y_m.size >= 3 else y_m

    return float(np.percentile(y_use, 99.0))
    

def _compute_plot_width(points_mm: np.ndarray, fallback_width_m: float | None) -> float:
    """Estimate plot width in meters, falling back to config if provided."""
    if fallback_width_m is not None:
        return float(fallback_width_m)
    if points_mm.size == 0:
        return float("nan")
    x_vals = points_mm[:, 0].astype(np.float32)
    width_mm = np.nanmax(x_vals) - np.nanmin(x_vals)
    if not np.isfinite(width_mm) or width_mm <= 0:
        return float("nan")
    return width_mm / 1000.0

# ======================================================================
# Utility
# ======================================================================

def _lidar_dict_from_plot_indices(
    fused_np: np.ndarray,
    plot_idx: np.ndarray,
    lidar_height_mm: float,
) -> dict | None:
    """
    Build lidar_data dict for LAI from a set of fused rows belonging to one plot.
    Treat the entire plot as a single 'scan' (1 x N distances).

    NOTE: fused_np[:, 3] is distance in millimeters; we convert to meters here.
    """
    if plot_idx.size == 0:
        return None

    rows = fused_np[plot_idx]
    # Columns in fused_np: [0]=shared_time, [1]=phi (rad), [2]=theta (rad),
    #                      [3]=dist_mm, [4]=rssi
    phi = rows[:, 1].astype(np.float64, copy=False)
    dist_mm = rows[:, 3].astype(np.float64, copy=False)
    dist_m = dist_mm / 1000.0

    # Convert azimuth-like phi to zenith (0 = up), ensure non-negative
    zeniths = (0.5 * math.pi) - phi
    zeniths = np.where(zeniths < 0, -zeniths, zeniths)

    # Single "scan": shape (1, N_angles), in meters
    distances = dist_m[None, :]

    return {
        "zeniths": zeniths,
        "distances": distances,
        "height_above_ground": float(lidar_height_mm) / 1000.0,
    }

def _to_cartesian_mm(phi, theta, r_mm):
    x = r_mm * np.cos(phi) * np.sin(theta)
    y = r_mm * np.cos(phi) * np.cos(theta)
    z = r_mm * np.sin(phi)
    return np.stack([x, -y, -z], axis=-1).astype(np.float32, copy=False)

def letter_range(start, end):
    if start <= end:
        return [chr(c) for c in range(ord(start), ord(end) + 1)]
    else:
        return [chr(c) for c in range(ord(start), ord(end) - 1, -1)]

def inclusive_range(a, b, step=1):
    if step == 0:
        raise ValueError("step cannot be zero")
    if a > b and step > 0:
        step = -step
    elif a < b and step < 0:
        step = -step
    return range(a, b + (1 if step > 0 else -1), step)

def parse_scan_name(scan_base: str) -> dict:
    """
    Supported examples
    ------------------
    1_7
    1_1_20
    1&2_7
    1&2_1_20
    2&1_20_1
    1&2_1_5_multi02_2026_03_23_hallway

    Meaning
    -------
    - Single-row:
        <row>_<plot>
        <row>_<plot_start>_<plot_end>

    - Two-row:
        <left_row>&<right_row>_<plot>
        <left_row>&<right_row>_<plot_start>_<plot_end>

    Returns
    -------
    {
        "rows": ["1"] or ["1", "2"],
        "plot_numbers": [7] or [1,2,...,20] or [20,...,1],
        "is_two_row": bool,
        "is_single_plot": bool,
    }
    """
    parts = scan_base.split("_")
    if len(parts) < 2:
        raise ValueError(f"Unexpected scan name format: {scan_base}")

    row_spec = parts[0]
    numeric_parts: list[int] = []
    for token in parts[1:]:
        try:
            numeric_parts.append(int(token))
        except ValueError:
            break
        if len(numeric_parts) == 2:
            break

    if len(numeric_parts) == 1:
        start_plot = numeric_parts[0]
        end_plot = numeric_parts[0]
    elif len(numeric_parts) >= 2:
        start_plot = numeric_parts[0]
        end_plot = numeric_parts[1]
    else:
        raise ValueError(f"Unexpected scan name format: {scan_base}")

    if "&" in row_spec:
        rows = [x.strip() for x in row_spec.split("&", 1)]
        if len(rows) != 2 or (not rows[0]) or (not rows[1]):
            raise ValueError(f"Bad two-row scan name: {scan_base}")
    else:
        rows = [row_spec.strip()]
        if not rows[0]:
            raise ValueError(f"Bad single-row scan name: {scan_base}")

    plot_numbers = list(inclusive_range(int(start_plot), int(end_plot)))

    return {
        "rows": rows,
        "plot_numbers": plot_numbers,
        "is_two_row": len(rows) == 2,
        "is_single_plot": len(plot_numbers) == 1,
    }

def expected_plot_numbers_from_scan(scan_base: str) -> list[int]:
    return parse_scan_name(scan_base)["plot_numbers"]


def expected_plot_count_from_scan(scan_base: str) -> int:
    return len(expected_plot_numbers_from_scan(scan_base))

def load_csv(path, usecols=None, dtypes=None):
    try:
        df = pd.read_csv(path, usecols=usecols, dtype=dtypes)
        return df.to_numpy()
    except Exception as e:
        print(f"[Error loading] {path}: {e}")
        return np.empty((0, len(usecols) if usecols else 0))

def load_files_from_paths(lidar_path, pico_path):
    """Read LiDAR and Pico CSVs (Euler format) and return as NumPy arrays."""
    # LiDAR CSV columns
    lidar_cols = ["time_s", "phi", "theta", "dist", "rssi", "pps_pi"]
    lidar_dtypes = {
        "time_s": np.float64, "phi": np.float32, "theta": np.float32,
        "dist": np.float32, "rssi": np.uint16, "pps_pi": np.int32
    }
    lidar_np = load_csv(lidar_path, usecols=lidar_cols, dtypes=lidar_dtypes)

    # Pico CSV columns (Euler, degrees)
    # time_s,count,roll_deg,pitch_deg,yaw_deg,pps
    pico_cols = ["time_s", "count", "roll_deg", "pitch_deg", "yaw_deg", "pps"]
    pico_dtypes = {
        "time_s": np.float64, "count": np.int32,
        "roll_deg": np.float32, "pitch_deg": np.float32, "yaw_deg": np.float32,
        "pps": np.int32
    }
    pico_np = load_csv(pico_path, usecols=pico_cols, dtypes=pico_dtypes)
    return lidar_np, pico_np

# ======================================================================
# Plot object (CSV + optional PLY)
# ======================================================================
class Plot:
    def __init__(self, row, letter, z_bounds, out_dir, scan_base=None):
        self.row = row
        self.letter = letter
        self.name = f"{row}_{letter}"
        self.scan_base = scan_base
        self.min_z, self.max_z = z_bounds
        self.out_dir = out_dir

        if not self.scan_base or self.scan_base == self.name:
            file_stem = self.name
        elif self.scan_base.startswith(f"{self.name}_"):
            file_stem = self.scan_base
        else:
            file_stem = f"{self.name}_{self.scan_base}"

        self.csv_out = os.path.join(self.out_dir, f"{file_stem}.csv")
        self.ply_out = os.path.join(self.out_dir, f"{file_stem}.ply")
        self.cloud = []
        self.side_label = None
        self.side_sign = None

    def range_match(self, z):
        return (z > self.min_z) & (z < self.max_z)

    def row_match(self, x, row_options):
        left_row, right_row = row_options

        # If your cloud is mirrored, keep this version.
        left = x >= 0
        right = x < 0

        return (left & (self.row == left_row)) | (right & (self.row == right_row))

    def _write_csv(self, arr_m):
        df = pd.DataFrame(arr_m[:, :4], columns=["X", "Y", "Z", "RSSI"])
        df.to_csv(self.csv_out, index=False)

    def _write_ply(self, arr_m):
        if arr_m.size == 0:
            return
        pts = o3d.geometry.PointCloud()
        pts.points = o3d.utility.Vector3dVector(arr_m[:, :3])
        if arr_m.shape[1] >= 4:
            rssi = arr_m[:, 3].astype(np.float32)
            if rssi.size:
                rmin = np.nanmin(rssi)
                rmax = np.nanmax(rssi)
                span = (rmax - rmin) if (rmax > rmin) else 1.0
                gray = ((rssi - rmin) / span).clip(0, 1)
                rgb = np.stack([gray, gray, gray], axis=1)
                pts.colors = o3d.utility.Vector3dVector(rgb)
        o3d.io.write_point_cloud(self.ply_out, pts, write_ascii=True)

    def write(self, make_point_cloud: bool, overwrite_outputs: bool, write_o3d_ply: bool):
        """
        Write per-plot CSV (and optional PLY) if enabled.

        - make_point_cloud: master on/off
        - overwrite_outputs: overwrite existing files or skip
        - write_o3d_ply: also write a PLY file
        """
        if not make_point_cloud or len(self.cloud) == 0:
            return

        arr = np.array(self.cloud)
        if arr.ndim != 2 or arr.shape[1] < 4:
            print(f"[Warning] Bad cloud shape: {arr.shape} in {self.name}")
            return

        # Convert mm -> m for output
        arr_m = arr.copy()
        arr_m[:, :3] /= 1000.0

        if (not overwrite_outputs) and os.path.exists(self.csv_out):
            return

        self._write_csv(arr_m)
        if write_o3d_ply:
            self._write_ply(arr_m)


# ======================================================================
# Core process
# ======================================================================

def normalize_rssi_by_phi_zscore(phi: np.ndarray, rssi: np.ndarray, decimals: int = 3) -> np.ndarray:
    """
    Per-phi z-score, followed by an exponential transform.

    Output is positive:
      exp(0) = 1
      positive z -> > 1
      negative z -> between 0 and 1

    This makes bright-above-average returns stand out more strongly.
    """
    phi = np.asarray(phi, dtype=np.float32)
    rssi = np.asarray(rssi, dtype=np.float32)
    out = np.zeros_like(rssi, dtype=np.float32)

    phi_key = np.round(phi, decimals=decimals)

    EXP_ALPHA = 1.0   # try 0.75, 1.0, or 1.25
    Z_CLIP = 4.0      # prevents huge blowups

    for ph in np.unique(phi_key):
        m = (phi_key == ph)
        vals = rssi[m]

        if vals.size == 0:
            continue

        mu = np.mean(vals, dtype=np.float64)
        sd = np.std(vals, dtype=np.float64)

        if sd == 0.0:
            z = np.zeros_like(vals, dtype=np.float32)
        else:
            z = ((vals - mu) / sd).astype(np.float32)

        z = np.clip(z, -Z_CLIP, Z_CLIP)
        out[m] = np.exp(EXP_ALPHA * z).astype(np.float32)

    return out


def normalize_rssi_by_phi_percentile(phi: np.ndarray, rssi: np.ndarray, decimals: int = 3) -> np.ndarray:
    phi = np.asarray(phi, dtype=np.float32)
    rssi = np.asarray(rssi, dtype=np.float32)
    out = np.zeros_like(rssi, dtype=np.float32)

    phi_key = np.round(phi, decimals=decimals)

    for ph in np.unique(phi_key):
        m = (phi_key == ph)
        vals = rssi[m]

        n = vals.size
        if n == 0:
            continue
        if n == 1:
            out[m] = 0.5
            continue

        order = np.argsort(vals, kind="mergesort")
        ranks = np.empty(n, dtype=np.float32)
        ranks[order] = np.arange(n, dtype=np.float32)
        ranks /= float(n - 1)
        out[m] = ranks

    return out


def choose_fusion_method(cfg: AnalysisConfig, lidar_np: np.ndarray, pico_np: np.ndarray) -> np.ndarray:
    if cfg.fusion_method == "pps":
        return fuse_by_pps(
            lidar_np,
            pico_np,
            lidar_ts_col=0,
            pico_ts_col=0,
            lidar_pps_col=5,
            pico_pps_col=5,
        ).astype(np.float32, copy=False)
    if cfg.fusion_method == "interp":
        return fuse_by_time(
            lidar_np,
            pico_np,
            lidar_ts_col=0,
            pico_ts_col=0,
            trim_to_overlap=False,
        ).astype(np.float32, copy=False)
    raise ValueError(f"Unknown fusion_method: {cfg.fusion_method}")


def dense_median(values: np.ndarray, fraction: float = 0.6) -> float:
    vals = np.asarray(values, dtype=np.float32)
    vals = vals[np.isfinite(vals)]
    n = vals.size

    if n == 0:
        return 0.0
    if n == 1:
        return float(vals[0])

    fraction = float(fraction)
    if not (0.0 < fraction <= 1.0):
        raise ValueError(f"imu_zero_fraction must be in (0, 1], got {fraction}")

    vals = np.sort(vals)
    k = max(1, int(np.ceil(fraction * n)))
    if k >= n:
        return float(np.median(vals))

    widths = vals[k - 1:] - vals[: n - k + 1]
    i = int(np.argmin(widths))
    window = vals[i : i + k]

    return float(np.median(window))


def reconstruct_world_points(
    fused_np: np.ndarray,
    cfg: AnalysisConfig,
    step_mm: float,
    lidar_height_mm: float,
    roll_offset: float,
    pitch_offset: float,
    min_radius_mm: float | None = None,
    lidar_wheel_offset_mm: float = 0.0,  # kept in signature if you want, but unused here
) -> tuple[np.ndarray, np.ndarray]:
    phi = fused_np[:, 1]
    theta = fused_np[:, 2]
    dist = fused_np[:, 3]
    rssi = fused_np[:, 4].astype(np.float32, copy=False)
    count = fused_np[:, 5]
    roll_deg = fused_np[:, 6]
    pitch_deg = fused_np[:, 7]
    yaw_deg = fused_np[:, 8]

    r_mm = dist.astype(np.float32, copy=False)
    beam_pts_lidar = _to_cartesian_mm(phi, theta, r_mm)

    keep_idx = np.arange(fused_np.shape[0], dtype=np.int32)

    if min_radius_mm is not None and min_radius_mm > 0:
        sensor_r_xz = np.hypot(beam_pts_lidar[:, 0], beam_pts_lidar[:, 2])
        mask = sensor_r_xz >= min_radius_mm

        phi = phi[mask]
        theta = theta[mask]
        dist = dist[mask]
        rssi = rssi[mask]
        count = count[mask]
        roll_deg = roll_deg[mask]
        pitch_deg = pitch_deg[mask]
        yaw_deg = yaw_deg[mask]
        beam_pts_lidar = beam_pts_lidar[mask]
        keep_idx = keep_idx[mask]

    rssi_used = rssi

    roll_apply = np.zeros_like(roll_deg, dtype=np.float32)
    pitch_apply = np.zeros_like(pitch_deg, dtype=np.float32)
    yaw_apply = np.zeros_like(yaw_deg, dtype=np.float32)

    if cfg.use_imu:
        imu_zero_mode = str(getattr(cfg, "imu_zero_mode", "dense_median")).strip().lower()
        imu_zero_fraction = float(getattr(cfg, "imu_zero_fraction", 0.6))

        if imu_zero_mode == "dense_median":
            roll_zero = dense_median(roll_deg, imu_zero_fraction)
            pitch_zero = dense_median(pitch_deg, imu_zero_fraction)
        elif imu_zero_mode == "calibration":
            roll_zero = float(roll_offset)
            pitch_zero = float(pitch_offset)
        else:
            raise ValueError(f"Unknown imu_zero_mode: {imu_zero_mode}")

        roll_apply = (roll_deg - roll_zero) * cfg.roll_sign
        pitch_apply = (pitch_deg - pitch_zero) * cfg.pitch_sign

    if cfg.use_heading:
        yaw_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(yaw_deg)))
        yaw_zero = np.median(yaw_unwrapped[:50]) if yaw_unwrapped.size >= 50 else yaw_unwrapped[0]
        yaw_apply = (yaw_unwrapped - yaw_zero) * cfg.heading_sign

    angles = np.stack([roll_apply, pitch_apply, yaw_apply], axis=1)
    rot = R.from_euler("ZXY", angles, degrees=True)

    # Travel distance along the row.
    # This is not a wheel-origin coordinate system; it is just how far the cart has moved.
    d_mm = count.astype(np.float32) * float(step_mm)
    cart_translation = np.stack(
        [
            np.zeros_like(d_mm, dtype=np.float32),
            np.zeros_like(d_mm, dtype=np.float32),
            d_mm,
        ],
        axis=1,
    )

    # Keep the cloud lidar-centered in Z.
    # Only vertical mounting height belongs here.
    lidar_offset_body = np.array(
        [0.0, float(lidar_height_mm), 0.0],
        dtype=np.float32,
    )

    lidar_offset_world = rot.apply(
        np.repeat(lidar_offset_body[None, :], len(d_mm), axis=0)
    ).astype(np.float32, copy=False)

    beam_pts_world_rel = rot.apply(beam_pts_lidar).astype(np.float32, copy=False)

    lidar_center_world = cart_translation + lidar_offset_world
    world_pts = lidar_center_world + beam_pts_world_rel

    data = np.column_stack([world_pts, rssi_used]).astype(np.float32, copy=False)
    return data, keep_idx


def apply_global_filters(
    scan_base: str,
    data: np.ndarray,
    keep_idx: np.ndarray,
    width_mm: float,
    x_min_mm: float | None,
    y_max_mm: float | None,
    min_radius_mm: float | None,
    cfg: AnalysisConfig,
) -> tuple[np.ndarray, np.ndarray]:
    if data.size == 0:
        print(f"[Warning] No points entering global filters for {scan_base}")
        return data, keep_idx

    x_mm = data[:, 0]
    print(f"[DEBUG] X range (mm): {np.nanmin(x_mm):.1f} to {np.nanmax(x_mm):.1f}")
    print(f"[DEBUG] X range (m): {np.nanmin(x_mm)/1000.0:.3f} to {np.nanmax(x_mm)/1000.0:.3f}")

    # Outer row-width mask
    if width_mm is not None and width_mm > 0:
        mask = np.abs(data[:, 0]) <= width_mm
        data = data[mask]
        keep_idx = keep_idx[mask]

        if data.size > 0:
            x_mm2 = data[:, 0]
            print(f"[DEBUG] After x_max filter: X range (mm): {np.nanmin(x_mm2):.1f} to {np.nanmax(x_mm2):.1f}")
            print(f"[DEBUG] After x_max filter: X range (m): {np.nanmin(x_mm2)/1000.0:.3f} to {np.nanmax(x_mm2)/1000.0:.3f}")

    if x_min_mm is not None and x_min_mm > 0 and data.size > 0:
        before = data.shape[0]
        mask = np.abs(data[:, 0]) >= x_min_mm
        data = data[mask]
        keep_idx = keep_idx[mask]
        print(f"[DEBUG] After x_min filter: kept {data.shape[0]} / {before} points with x_min_mm={x_min_mm:.1f}")

    if y_max_mm is not None and data.size > 0:
        mask = data[:, 1] <= y_max_mm
        data = data[mask]
        keep_idx = keep_idx[mask]

    # min_radius_mm is intentionally NOT applied here anymore.
    # It is applied in sensor coordinates inside reconstruct_world_points().

    if data.size > 0:
        mask = data[:, 2] >= 0
        data = data[mask]
        keep_idx = keep_idx[mask]

    if data.size == 0:
        print(f"[Warning] No points remaining after filters for {scan_base}")

    return data, keep_idx


def build_plot_ranges(
    cfg: AnalysisConfig,
    z0: float,
    zmax: float,
    start_mm_global: float,
    end_buffer_mm: float,
    expected_plot_count: int | None = None,
) -> tuple[list[tuple[float, float]], bool, float, float]:
    usable_zmax = max(z0, zmax - end_buffer_mm)

    def _build_distance_ranges_auto(
        z_start: float,
        z_end: float,
        start_pad_mm: float,
        split_len_mm: float,
        plot_count_cap: int | None = None,
    ) -> list[tuple[float, float]]:
        if split_len_mm == 0:
            lo = z_start + start_pad_mm
            return [] if lo >= z_end else [(lo, z_end)]

        ranges: list[tuple[float, float]] = []
        st = z_start + start_pad_mm
        eps = 1e-6

        while (st + eps) < z_end:
            fi = min(st + split_len_mm, z_end)
            if fi <= st + eps:
                break

            ranges.append((st, fi))
            st = fi

            if plot_count_cap is not None and len(ranges) >= int(plot_count_cap):
                break

        return ranges

    # Distinguish None from 0 explicitly
    if cfg.split_u is None:
        split_len_mm = None
        do_distance = False
        ranges = [(z0, usable_zmax)] if z0 < usable_zmax else []
        print(
            f"[RANGES] z0={z0:.1f} mm, zmax={zmax:.1f} mm, usable_zmax={usable_zmax:.1f} mm, "
            f"start_pad=IGNORED, split_len_mm=None, do_distance=False, n_cap={expected_plot_count}"
        )
        print(f"[RANGES] built {len(ranges)} distance range(s)")
        return ranges, do_distance, usable_zmax, 0.0

    split_len_m = _to_m_units(cfg.split_u, cfg.dim_units)
    split_len_mm = split_len_m * 1000.0 if split_len_m > 0 else 0.0
    do_distance = split_len_mm > 0.0

    n_cap = expected_plot_count
    if n_cap is None:
        cfg_n_plots = getattr(cfg, "n_plots", None)
        n_cap = int(cfg_n_plots) if (cfg_n_plots and cfg_n_plots > 0) else None

    if do_distance and n_cap is not None and n_cap > 0:
        intended_end_mm = z0 + start_mm_global + (n_cap * split_len_mm)
        usable_zmax = min(usable_zmax, intended_end_mm)

    print(
        f"[RANGES] z0={z0:.1f} mm, zmax={zmax:.1f} mm, usable_zmax={usable_zmax:.1f} mm, "
        f"start_pad={start_mm_global:.1f} mm, split_len_mm={split_len_mm:.1f}, "
        f"do_distance={do_distance}, n_cap={n_cap}"
    )

    ranges = _build_distance_ranges_auto(
        z_start=z0,
        z_end=usable_zmax,
        start_pad_mm=start_mm_global,
        split_len_mm=split_len_mm,
        plot_count_cap=n_cap,
    )

    print(f"[RANGES] built {len(ranges)} distance range(s)")
    return ranges, do_distance, usable_zmax, split_len_mm


def build_plot_objects(
    scan_base: str,
    cfg: AnalysisConfig,
    ranges: list[tuple[float, float]],
    do_distance: bool,
    out_dir: str,
) -> tuple[list[Plot], list[str]]:
    parsed = parse_scan_name(scan_base)
    rows = parsed["rows"]
    plot_numbers = [str(x) for x in parsed["plot_numbers"]]

    plots: list[Plot] = []

    # row_options meaning:
    #   row_options[0] = left row
    #   row_options[1] = right row
    if parsed["is_two_row"]:
        row_options = [rows[0], rows[1]]
    else:
        row_options = [rows[0], rows[0]]

    # Single-plot scan: use the full usable range as one plot
    if parsed["is_single_plot"]:
        if len(ranges) == 0:
            return [], row_options

        full_st = ranges[0][0]
        full_fi = ranges[-1][1]
        label = plot_numbers[0]

        for row in rows:
            plots.append(Plot(row, label, (full_st, full_fi), out_dir, scan_base=scan_base))

        return plots, row_options

    # Continuous scan: one distance bin per plot label
    for i, (st, fi) in enumerate(ranges):
        plot_num = plot_numbers[i] if i < len(plot_numbers) else str(i + 1)

        for row in rows:
            plots.append(Plot(row, plot_num, (st, fi), out_dir, scan_base=scan_base))

    return plots, row_options

def build_plot_objects_from_mark_segments(
    scan_base: str,
    segments,
    out_dir: str,
) -> tuple[list[Plot], list[str]]:
    parsed = parse_scan_name(scan_base)
    rows = parsed["rows"]

    if parsed["is_two_row"]:
        row_options = [rows[0], rows[1]]
    else:
        row_options = [rows[0], rows[0]]

    plots: list[Plot] = []

    for seg in segments:
        for row in rows:
            p = Plot(
                row=row,
                letter=str(seg.label),
                z_bounds=(float(seg.min_z), float(seg.max_z)),
                out_dir=out_dir,
                scan_base=scan_base,
            )
            p.split_source = "marks"
            p.target_type = str(seg.target_type)
            p.target_number = str(seg.target_number)
            plots.append(p)

    return plots, row_options


def write_scan_outputs(scan_base: str, cfg: AnalysisConfig, plot: Plot) -> None:
    if cfg.make_point_cloud:
        plot.write(
            make_point_cloud=cfg.make_point_cloud,
            overwrite_outputs=cfg.overwrite_outputs,
            write_o3d_ply=cfg.write_o3d_ply,
        )

def is_additional_scan_name(scan_base: str) -> bool:
    s = str(scan_base).strip().lower()
    return s.startswith("scan_")


def with_side_suffix(plot: Plot, side_label: str, side_sign: str) -> Plot:
    p2 = Plot(
        row=plot.row,
        letter=plot.letter,
        z_bounds=(plot.min_z, plot.max_z),
        out_dir=plot.out_dir,
        scan_base=plot.scan_base,
    )
    p2.split_source = getattr(plot, "split_source", "distance")
    p2.target_type = getattr(plot, "target_type", "plot")
    p2.target_number = getattr(plot, "target_number", plot.letter)
    p2.side_label = side_label
    p2.side_sign = side_sign

    if is_additional_scan_name(str(plot.scan_base)):
        file_stem = f"{plot.scan_base}_{side_label}"
    else:
        file_stem = os.path.splitext(os.path.basename(p2.csv_out))[0] + f"_{side_label}"
    p2.csv_out = os.path.join(p2.out_dir, f"{file_stem}.csv")
    p2.ply_out = os.path.join(p2.out_dir, f"{file_stem}.ply")
    return p2


def analyze_plot(
    p: Plot,
    data: np.ndarray,
    keep_idx: np.ndarray,
    fused_np: np.ndarray,
    scan_base: str,
    cfg: AnalysisConfig,
    row_options: list[str],
    lidar_height_mm: float,
    step_mm: float,
) -> dict:
    z_mask = p.range_match(data[:, 2])

    is_two_row_scan = row_options[0] != row_options[1]

    if not is_two_row_scan:
        x_mask = np.ones_like(z_mask, dtype=bool)
    else:
        x_mask = p.row_match(data[:, 0], row_options)

    mask = z_mask & x_mask

    if getattr(p, "side_sign", None) == "positive":
        mask = mask & (data[:, 0] > 0)
    elif getattr(p, "side_sign", None) == "negative":
        mask = mask & (data[:, 0] < 0)

    p.cloud = np.empty((0, 4), dtype=np.float32)
    n_points = 0
    height_m = float("nan")
    lai_even = float("nan")
    lai_uneven = float("nan")
    n_scans = 0
    n_angles = 0
    density = float("nan")
    stand_topo_per_m = float("nan")
    stand_topo_left_count = float("nan")
    stand_topo_right_count = float("nan")
    n_points_o3d = 0
    voxel_count_o3d = float("nan")
    plot_idx = np.empty((0,), dtype=np.int32)

    if not np.any(mask):
        goto_open3d = False
    else:
        goto_open3d = True
        p.cloud = data[mask]
        n_points = int(p.cloud.shape[0])
        if cfg.run_height:
            height_m = height_from_world_y(p.cloud, alpha=0.01)
        plot_idx = keep_idx[mask]
        lidar_dict = _lidar_dict_from_plot_indices(fused_np, plot_idx, lidar_height_mm)
        if cfg.run_lai and lidar_dict is not None:
            distances = lidar_dict["distances"]
            n_scans, n_angles = distances.shape
            lai_even_val = lai(lidar_dict, EVEN_ZENITH_BREAKS)
            lai_uneven_val = lai(lidar_dict, UNEVEN_ZENITH_BREAKS)
            lai_even = float(lai_even_val) if lai_even_val is not None else float("nan")
            lai_uneven = float(lai_uneven_val) if lai_uneven_val is not None else float("nan")

    topo_input = np.empty((0, 3), dtype=float)
    if goto_open3d:
        if cfg.run_o3d_metrics:
            scan_index_plot = fused_np[plot_idx, 5].astype(np.float64)
            n_points_o3d = int(p.cloud.shape[0])
            voxel_count_o3d = float("nan")
        else:
            n_points_o3d = 0
            voxel_count_o3d = float("nan")

        if cfg.run_topology:
            topo_input = p.cloud[:, :3].astype(float, copy=False)
    else:
        n_points_o3d = 0
        voxel_count_o3d = float("nan")
        topo_input = np.empty((0, 3), dtype=float)

    z_min, z_max = p.min_z, p.max_z
    plot_length_m = max((float(z_max) - float(z_min)) / 1000.0, 0.0)
    plot_width_m = _compute_plot_width(p.cloud, 2.0 * _to_m_units(cfg.row_width_u, cfg.dim_units))
    if np.isfinite(plot_width_m) and plot_length_m > 0:
        area_m2 = plot_width_m * plot_length_m
    else:
        area_m2 = float("nan")
    density = n_points / area_m2 if (np.isfinite(area_m2) and area_m2 > 0) else float("nan")

    if (not cfg.run_topology) or topo_input.size == 0:
        stand_topo_per_m = float("nan")
        stand_topo_left_count = float("nan")
        stand_topo_right_count = float("nan")
    else:
        try:
            is_two_row_scan = row_options[0] != row_options[1]

            if is_two_row_scan:
                left_input = topo_input[topo_input[:, 0] >= 0]
                right_input = topo_input[topo_input[:, 0] < 0]
                stand_topo_left_per_m = float("nan")
                stand_topo_right_per_m = float("nan")

                if left_input.size > 0:
                    topo_left = topology_stand_count(
                        left_input, step_mm,
                        min_persistence=cfg.topo_min_persistence,
                        background_cut=cfg.topo_background_cut,
                        x_bin_m=cfg.topo_x_bin_m,
                        z_bin_m=cfg.topo_z_bin_m,
                    )
                    stand_topo_left_count = float(topo_left.get("count_raw", float("nan")))
                    stand_topo_left_per_m = float(topo_left.get("count", float("nan")))

                if right_input.size > 0:
                    topo_right = topology_stand_count(
                        right_input, step_mm,
                        min_persistence=cfg.topo_min_persistence,
                        background_cut=cfg.topo_background_cut,
                        x_bin_m=cfg.topo_x_bin_m,
                        z_bin_m=cfg.topo_z_bin_m,
                    )
                    stand_topo_right_count = float(topo_right.get("count_raw", float("nan")))
                    stand_topo_right_per_m = float(topo_right.get("count", float("nan")))

                vals = [stand_topo_left_per_m, stand_topo_right_per_m]
                stand_topo_per_m = float("nan") if np.all(np.isnan(vals)) else float(np.nansum(vals))
            else:
                topo_total = topology_stand_count(
                    topo_input, step_mm,
                    min_persistence=cfg.topo_min_persistence,
                    background_cut=cfg.topo_background_cut,
                    x_bin_m=cfg.topo_x_bin_m,
                    z_bin_m=cfg.topo_z_bin_m,
                )
                stand_topo_per_m = float(topo_total.get("count", float("nan")))
                total_raw = float(topo_total.get("count_raw", float("nan")))
                stand_topo_left_count = total_raw
                stand_topo_right_count = float("nan")
        except Exception as e:
            print(f"[Topology][ERROR] scan={scan_base} plot={p.name}: {e}")
            stand_topo_per_m = float("nan")
            stand_topo_left_count = float("nan")
            stand_topo_right_count = float("nan")

    result = {
        "scan": scan_base if not getattr(p, "side_label", None) else f"{scan_base}_{p.side_label}",
        "row": p.row,
        "plot": p.letter,
        "split_source": getattr(p, "split_source", "distance"),
        "target_type": getattr(p, "target_type", "plot"),
        "target_number": getattr(p, "target_number", p.letter),
        "z_min_m": float(p.min_z) / 1000.0,
        "z_max_m": float(p.max_z) / 1000.0,
        "points": n_points,
        "height_m": height_m,
        "lai_even": lai_even,
        "lai_uneven": lai_uneven,
        "lidar_scans": n_scans,
        "lidar_angles": n_angles,
        "point_density_m2": density,
        "plot_length_m": plot_length_m,
        "plot_width_m": plot_width_m,
        "stand_topo_per_m": stand_topo_per_m,
        "stand_topo_left_count": stand_topo_left_count,
        "stand_topo_right_count": stand_topo_right_count,
        "o3d_points": n_points_o3d,
        "o3d_voxels": voxel_count_o3d,
    }

    print(
        f"[Traits] scan={scan_base}, plot={p.name}, "
        f"height={height_m:.3f} m, LAI_even={lai_even:.3f}, LAI_uneven={lai_uneven:.3f}, "
        f"stand_topo_per_m={stand_topo_per_m:.3f}, "
        f"count_left={stand_topo_left_count:.2f}, count_right={stand_topo_right_count:.2f}, "
        f"o3d_points={n_points_o3d}, o3d_voxels={voxel_count_o3d}, "
        f"points={n_points}, scans={n_scans}, angles={n_angles}"
    )
    return result


def apply_rssi_normalization_after_masks(
    data: np.ndarray,
    keep_idx: np.ndarray,
    fused_np: np.ndarray,
    cfg: AnalysisConfig,
) -> np.ndarray:
    """
    Recompute RSSI normalization using only points that survived the global masks.

    Modes:
    - percentile: phi-only percentile
    - zscore:     phi-only z-score
    """
    if data.size == 0 or not cfg.normalize_rssi:
        return data

    phi_kept = fused_np[keep_idx, 1].astype(np.float32, copy=False)
    theta_kept = fused_np[keep_idx, 2].astype(np.float32, copy=False)  # kept for symmetry/debug
    dist_kept = fused_np[keep_idx, 3].astype(np.float32, copy=False)
    rssi_kept = fused_np[keep_idx, 4].astype(np.float32, copy=False)

    valid = np.isfinite(phi_kept) & np.isfinite(theta_kept) & np.isfinite(dist_kept) & np.isfinite(rssi_kept)
    valid &= (dist_kept > 0)
    valid &= (rssi_kept > 0)

    out = np.array(data, copy=True)

    if not np.any(valid):
        out[:, 3] = 0.0
        return out

    mode = str(cfg.rssi_norm_mode).strip().lower()
    rssi_norm = np.zeros_like(rssi_kept, dtype=np.float32)

    if mode == "percentile":
        print("[RSSI_NORM] using PHI-only percentile")
        rssi_norm[valid] = normalize_rssi_by_phi_percentile(
            phi_kept[valid],
            rssi_kept[valid],
            decimals=3,
        ).astype(np.float32, copy=False)

    elif mode == "zscore":
        print("[RSSI_NORM] using PHI-only zscore")
        rssi_norm[valid] = normalize_rssi_by_phi_zscore(
            phi_kept[valid],
            rssi_kept[valid],
            decimals=3,
        ).astype(np.float32, copy=False)

    else:
        raise ValueError(f"Unknown rssi_norm_mode: {mode}")

    out[:, 3] = rssi_norm
    return out


def apply_rssi_filter(
    data: np.ndarray,
    keep_idx: np.ndarray,
    cfg: AnalysisConfig,
) -> tuple[np.ndarray, np.ndarray]:
    if data.size == 0 or not cfg.use_rssi_filter:
        return data, keep_idx

    rssi_vals = data[:, 3]
    mask = np.ones(rssi_vals.shape[0], dtype=bool)

    if cfg.rssi_min is not None:
        mask &= rssi_vals >= float(cfg.rssi_min)

    if cfg.rssi_max is not None:
        mask &= rssi_vals <= float(cfg.rssi_max)

    print(
        f"[RSSI_FILTER] min={cfg.rssi_min} max={cfg.rssi_max} "
        f"kept={int(mask.sum())}/{int(mask.size)}"
    )

    return data[mask], keep_idx[mask]


def process_scan(
    scan_base: str,
    lidar_path: str,
    pico_path: str,
    out_dir: str,
    cfg: AnalysisConfig,
    width_mm: float,
    start_mm_global: float,
    end_buffer_mm: float,
    y_max_mm: float | None,
    x_min_mm: float | None,
    min_radius_mm: float | None,
    step_mm: float,
    lidar_height_mm: float,
    lidar_wheel_offset_mm: float = 0.0,
    roll_offset: float = 0.0,
    pitch_offset: float = 0.0,
    imu_offset_mm: np.ndarray | None = None,
):
    if imu_offset_mm is None:
        imu_offset_mm = np.zeros(3, dtype=float)

    print(f"[Processing] {scan_base}")

    lidar_np, pico_np = load_files_from_paths(lidar_path, pico_path)
    if lidar_np.size == 0 or pico_np.size == 0:
        print(f"[Skip] {scan_base} due to missing data.")
        return []

    fused_np = choose_fusion_method(cfg, lidar_np, pico_np)
    if fused_np.size == 0:
        print(f"[Warning] No matched lidar-pico rows for {scan_base}")
        return []

    data, keep_idx = reconstruct_world_points(
        fused_np,
        cfg,
        step_mm=step_mm,
        lidar_height_mm=lidar_height_mm,
        roll_offset=roll_offset,
        pitch_offset=pitch_offset,
        min_radius_mm=min_radius_mm,
        lidar_wheel_offset_mm=lidar_wheel_offset_mm,
    )
    if data.size == 0:
        print(f"[Warning] No points reconstructed for {scan_base}")
        return []

    data, keep_idx = apply_global_filters(
        scan_base,
        data,
        keep_idx,
        width_mm=width_mm,
        x_min_mm=x_min_mm,
        y_max_mm=y_max_mm,
        min_radius_mm=min_radius_mm,
        cfg=cfg,
    )
    if data.size == 0:
        return []

    data = apply_rssi_normalization_after_masks(
        data=data,
        keep_idx=keep_idx,
        fused_np=fused_np,
        cfg=cfg,
    )
    if data.size == 0:
        return []

    data, keep_idx = apply_rssi_filter(
        data=data,
        keep_idx=keep_idx,
        cfg=cfg,
    )
    if data.size == 0:
        return []

    z0 = float(np.nanmin(data[:, 2]))
    zmax = float(np.nanmax(data[:, 2]))

    # Convert the user’s wheel-based field start to lidar-based start.
    effective_start_mm = start_mm_global - lidar_wheel_offset_mm
    if effective_start_mm < 0:
        effective_start_mm = 0.0

    if not np.isfinite(z0) or not np.isfinite(zmax):
        print(f"[Warning] NaN z stats for {scan_base}; skipping.")
        return []

    if cfg.run_height:
        h99_m = height_from_world_y(data, alpha=0.01)
        print(f"[Height] Scan={scan_base}, 99th percentile height = {h99_m:.3f} m")

    split_source = str(getattr(cfg, "split_source", "distance")).strip().lower()
    if split_source not in ("distance", "marks"):
        raise ValueError(f"Unknown split_source={split_source!r}; use 'distance' or 'marks'.")

    if split_source == "marks":
        raw_dir = os.path.dirname(lidar_path)

        marker_path = find_marker_file_for_scan(
            raw_dir=raw_dir,
            scan_base=scan_base,
            markers_dirname=str(getattr(cfg, "markers_dirname", "markers")),
        )

        if marker_path is None:
            missing_mode = str(getattr(cfg, "missing_mark_file", "error")).strip().lower()

            if missing_mode == "distance":
                print(f"[MARKS][WARN] No marker file for {scan_base}; falling back to distance splitting.")
                split_source = "distance"
            elif missing_mode == "skip":
                print(f"[MARKS][WARN] No marker file for {scan_base}; skipping.")
                return []
            else:
                raise FileNotFoundError(
                    f"No marker file found for {scan_base}. "
                    f"Expected markers/{scan_base}_markers.csv or similar."
                )

    if split_source == "marks":
        z_buffer_mm = marker_buffer_mm(
            getattr(cfg, "mark_z_buffer_u", 0.0),
            cfg.dim_units,
        )

        segments = build_mark_segments(
            marker_path=marker_path,
            step_mm=step_mm,
            lidar_wheel_offset_mm=lidar_wheel_offset_mm,
            z_buffer_mm=z_buffer_mm,
            target_type=str(getattr(cfg, "mark_target_type", "auto")),
            zmax_clip=zmax,
        )

        if len(segments) == 0:
            print(f"[MARKS][WARN] No usable marker segments for {scan_base}; skipping.")
            return []

        print(
            f"[MARKS] {scan_base}: using {len(segments)} segment(s) "
            f"from {marker_path}, z_buffer={z_buffer_mm:.1f} mm"
        )
        for seg in segments:
            print(
                f"[MARKS] {seg.target_type} {seg.target_number}: "
                f"{seg.min_z:.1f} -> {seg.max_z:.1f} mm"
            )

        plots, row_options = build_plot_objects_from_mark_segments(
            scan_base=scan_base,
            segments=segments,
            out_dir=out_dir,
        )

    else:
        expected_plot_count = None
        try:
            expected_plot_count = expected_plot_count_from_scan(scan_base)
        except Exception:
            expected_plot_count = None

        ranges, do_distance, usable_zmax, split_len_mm = build_plot_ranges(
            cfg,
            z0=0.0,
            zmax=zmax,
            start_mm_global=effective_start_mm,
            end_buffer_mm=end_buffer_mm,
            expected_plot_count=expected_plot_count,
        )

        if not np.isfinite(usable_zmax):
            print(f"[Warning] NaN z stats for {scan_base}; skipping.")
            return []

        start_check_mm = 0.0 if cfg.split_u is None else effective_start_mm

        if (z0 + start_check_mm) >= usable_zmax:
            print(
                f"[Warning] start>=end for {scan_base} "
                f"({z0 + start_check_mm:.1f} >= {usable_zmax:.1f}); skipping."
            )
            return []

        if len(ranges) == 0:
            print(f"[Warning] No plot ranges built for {scan_base}; skipping.")
            return []

        parsed_scan = parse_scan_name(scan_base)

        if parsed_scan["is_single_plot"] and len(ranges) > 0:
            ranges = [(ranges[0][0], ranges[-1][1])]
            do_distance = False

        plots, row_options = build_plot_objects(
            scan_base,
            cfg,
            ranges,
            do_distance=do_distance,
            out_dir=out_dir,
        )

    trait_records = []
    additional_side_split = (
        bool(getattr(cfg, "additional_scan_side_split", False))
        and str(getattr(cfg, "additional_scan_side_axis", "x")).strip().lower() == "x"
        and is_additional_scan_name(scan_base)
    )
    if additional_side_split:
        pos_label = str(getattr(cfg, "additional_scan_positive_side_label", "right")).strip() or "right"
        neg_label = str(getattr(cfg, "additional_scan_negative_side_label", "left")).strip() or "left"
        sided_plots: list[Plot] = []
        for p in plots:
            sided_plots.append(with_side_suffix(p, pos_label, "positive"))
            sided_plots.append(with_side_suffix(p, neg_label, "negative"))
        plots = sided_plots

    for p in plots:
        rec = analyze_plot(
            p,
            data,
            keep_idx,
            fused_np,
            scan_base,
            cfg,
            row_options,
            lidar_height_mm,
            step_mm,
        )
        trait_records.append(rec)
        write_scan_outputs(scan_base, cfg, p)

    print(f"Scan {scan_base} completed")
    return trait_records


# ======================================================================
# Directory runner
# ======================================================================
def run_for_directory(
    dir_path,
    out_dir,
    cfg: AnalysisConfig,
    width_mm,
    start_mm_global,
    end_buffer_mm,
    y_max_mm,
    x_min_mm,
    min_radius_mm,
    step_mm,
    lidar_height_mm,
    lidar_wheel_offset_mm,
    roll_offset,
    pitch_offset,
    imu_offset_mm,
):
    dir_path = os.path.abspath(dir_path)
    print(f"\n=== Processing directory: {dir_path} ===")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    try:
        entries = [f for f in os.listdir(dir_path)
                   if os.path.isfile(os.path.join(dir_path, f))]
    except FileNotFoundError:
        print(f"[Error] Directory not found: {dir_path}")
        return

    lidar_files = [f for f in entries if f.endswith("_lidar.csv")]
    bases = set()
    scan_triples = []
    all_trait_records = []

    for lf in lidar_files:
        base = lf[:-10]  # strip "_lidar.csv"
        pf   = base + "_pico.csv"
        if pf in entries:
            if base in bases:
                continue
            bases.add(base)
            lidar_path = os.path.abspath(os.path.join(dir_path, lf))
            pico_path  = os.path.abspath(os.path.join(dir_path, pf))
            if not lidar_path.startswith(dir_path + os.sep):
                continue
            if not pico_path.startswith(dir_path + os.sep):
                continue
            scan_triples.append((base, lidar_path, pico_path))

    if not scan_triples:
        print("[Info] No lidar/pico pairs found.")
        return

    # ---- per-scan loop ----
    for scan_base, lidar_path, pico_path in sorted(scan_triples, key=lambda t: t[0]):
        print(f"[Process] base={scan_base}\n"
              f"          lidar={lidar_path}\n"
              f"          pico ={pico_path}\n"
              f"          out  ={out_dir}")

        try:
            recs = process_scan(
                scan_base=scan_base,
                lidar_path=lidar_path,
                pico_path=pico_path,
                out_dir=out_dir,
                cfg=cfg,
                width_mm=width_mm,
                start_mm_global=start_mm_global,
                end_buffer_mm=end_buffer_mm,
                y_max_mm=y_max_mm,
                x_min_mm=x_min_mm,
                min_radius_mm=min_radius_mm,
                step_mm=step_mm,
                lidar_height_mm=lidar_height_mm,
                lidar_wheel_offset_mm=lidar_wheel_offset_mm,
                roll_offset=roll_offset,
                pitch_offset=pitch_offset,
                imu_offset_mm=imu_offset_mm,
            )
        except Exception as e:
            print(f"[SCAN][ERROR] {scan_base}: {e}")
            continue

        if recs:
            all_trait_records.extend(recs)

    # ---- AFTER the loop: one summary for the whole directory ----
    if all_trait_records:
        traits_df = pd.DataFrame.from_records(all_trait_records)
        traits_df = traits_df.round(2)
        traits_path = os.path.join(dir_path, "lidar_traits_summary.csv")
        traits_df.to_csv(traits_path, index=False, na_rep="NA")
        print(f"[Traits] Wrote summary to {traits_path}")


# ================================================================
# Public entry from analysis.py
# ================================================================
from pathlib import Path

_FT_TO_M = 0.3048
def _to_m_units(x: float, dim_units: str) -> float:
    return x if dim_units == "m" else x * _FT_TO_M


def run_experiment(cfg: AnalysisConfig) -> None:
    """
    High-level entry point called by analysis.py.
    Converts user config into derived mm/m units,
    loads calibration, and then runs directory processing.
    """

    print("\n=== PIPELINE START ===")

    # ---- convert dimension settings ----
    row_width_m  = _to_m_units(cfg.row_width_u, cfg.dim_units)
    x_min_m = None if getattr(cfg, "x_min_u", None) is None else _to_m_units(cfg.x_min_u, cfg.dim_units)
    start_m      = _to_m_units(cfg.start_u, cfg.dim_units)
    split_m      = _to_m_units(cfg.split_u, cfg.dim_units)
    end_buffer_m = _to_m_units(cfg.end_buffer_u, cfg.dim_units)
    max_y_m      = None if cfg.max_y_u is None else _to_m_units(cfg.max_y_u, cfg.dim_units)
    min_radius_m = None if cfg.min_radius_u is None else _to_m_units(cfg.min_radius_u, cfg.dim_units)

    width_mm        = row_width_m * 1000.0
    start_mm_global = start_m * 1000.0
    end_buffer_mm   = end_buffer_m * 1000.0
    y_max_mm        = None if max_y_m is None else max_y_m * 1000.0
    min_radius_mm   = None if min_radius_m is None else min_radius_m * 1000.0
    x_min_mm = None if x_min_m is None else x_min_m * 1000.0

    # ---- load calibration ----
    calib = load_calibration(cfg.cart_id, str(cfg.calibration_dir))
    step_mm         = calib["step_mm"]
    lidar_height_mm = calib["lidar_height_mm"]
    lidar_wheel_offset_mm = calib["lidar_wheel_offset_mm"]
    roll_offset     = calib["roll_offset_deg"]
    pitch_offset    = calib["pitch_offset_deg"]
    imu_offset_mm   = calib["imu_offset_mm"]

    # ---- run each directory ----
    run_for_directory(
        dir_path=str(Path(d)),
        out_dir=str(Path(d)),
        cfg=cfg,
        width_mm=width_mm,
        start_mm_global=start_mm_global,
        end_buffer_mm=end_buffer_mm,
        y_max_mm=y_max_mm,
        x_min_mm=x_min_mm,

        min_radius_mm=min_radius_mm,
        step_mm=step_mm,
        lidar_height_mm=lidar_height_mm,
        lidar_wheel_offset_mm=lidar_wheel_offset_mm,
        roll_offset=roll_offset,
        pitch_offset=pitch_offset,
        imu_offset_mm=imu_offset_mm,
    )

    print("\n=== PIPELINE COMPLETE ===")
