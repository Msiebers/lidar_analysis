import math
import os
import sys
from warnings import warn

import numpy as np
import pandas as pd
import yaml
from scipy import stats
from scipy.spatial.transform import Rotation as R

if __package__:
    from .lai import compute_lai_trait_from_beam_rows, compute_lai_trait_from_target
else:
    from lai import compute_lai_trait_from_beam_rows, compute_lai_trait_from_target

try:
    from .config import AnalysisConfig
    from .fusion import fuse_by_time
    from .fusion_pps import fuse_by_pps
    from .fusion_imu_interp import fuse_by_imu_interp
    from .mark_splitting import (
        build_mark_segments,
        find_marker_file_for_scan,
        marker_buffer_mm,
        marker_count_to_z_mm,
    )
    from .pointcloud_ops import apply_pointcloud_ops
    from .analysis_target import AnalysisTarget
    from .beam_diagnostics import compute_beam_diagnostics, write_beam_diagnostics_csv
    from .fad import (
        Box3D,
        compute_fad_traits,
        estimate_fad_height_from_points,
        height_result_to_traits,
        make_fad_box_from_footprint_and_height,
    )
except Exception:
    from config import AnalysisConfig
    from fusion import fuse_by_time
    from fusion_pps import fuse_by_pps
    from fusion_imu_interp import fuse_by_imu_interp
    from mark_splitting import (
        build_mark_segments,
        find_marker_file_for_scan,
        marker_buffer_mm,
        marker_count_to_z_mm,
    )
    from pointcloud_ops import apply_pointcloud_ops
    from analysis_target import AnalysisTarget
    from beam_diagnostics import compute_beam_diagnostics, write_beam_diagnostics_csv
    from fad import (
        Box3D,
        compute_fad_traits,
        estimate_fad_height_from_points,
        height_result_to_traits,
        make_fad_box_from_footprint_and_height,
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

EVEN_ZENITH_BREAKS = np.array((0, 15, 30, 45, 60, 75), dtype=float) / 180 * math.pi
UNEVEN_ZENITH_BREAKS = np.array((0, 13, 28, 43, 58, 75), dtype=float) / 180 * math.pi

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
    Build lidar_data dict for legacy LAI from emitted fused rows in one plot.

    NOTE: fused_np[:, 3] is distance in millimeters; we convert to meters here.
    SICK distance zero is a no-return beam, so convert it to the legacy gap
    sentinel before passing the dict to old-style LAI callers.
    """
    if plot_idx.size == 0:
        return None

    rows = fused_np[plot_idx]
    # Columns in fused_np: [0]=shared_time, [1]=phi (rad), [2]=theta (rad),
    #                      [3]=dist_mm, [4]=rssi
    theta = rows[:, 2].astype(np.float64, copy=False)
    dist_mm = rows[:, 3].astype(np.float64, copy=False)
    dist_m = dist_mm / 1000.0

    # Physical cap orientation: theta=0 is down, +/-pi is sky.  Keep the
    # sky-facing half and express it as legacy zenith (0=sky, pi/2=horizon).
    theta = ((theta + math.pi) % (2.0 * math.pi)) - math.pi
    zeniths = math.pi - np.abs(theta)
    valid = np.isfinite(dist_m) & np.isfinite(zeniths) & (zeniths >= 0.0) & (zeniths <= math.radians(75.0))
    if not np.any(valid):
        return None

    dist_m = dist_m[valid].copy()
    gap_distance_m = 30.0
    dist_m[dist_m <= 0.0] = gap_distance_m + 1.0

    # Single "scan": shape (1, N_angles), in meters
    distances = dist_m[None, :]

    return {
        "zeniths": zeniths[valid],
        "distances": distances,
        "height_above_ground": float(lidar_height_mm) / 1000.0,
    }


def _plot_interval_indices_from_fused(
    fused_np: np.ndarray,
    plot: "Plot",
    step_mm: float,
) -> np.ndarray:
    """Return emitted fused beam rows whose scanner travel lies in a plot interval."""
    if fused_np.size == 0:
        return np.empty((0,), dtype=np.int32)

    travel_z_mm = fused_np[:, 5].astype(np.float64, copy=False) * float(step_mm)
    mask = plot.range_match(travel_z_mm)
    return np.flatnonzero(mask).astype(np.int32, copy=False)

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
    pico_cols_with_imu = pico_cols + ["imu_time_s"]
    pico_dtypes = {
        "time_s": np.float64, "count": np.int32,
        "roll_deg": np.float32, "pitch_deg": np.float32, "yaw_deg": np.float32,
        "pps": np.int32, "imu_time_s": np.float64
    }
    pico_np = load_csv(pico_path, usecols=pico_cols_with_imu, dtypes=pico_dtypes)
    if pico_np.size == 0:
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
        self.analysis_target = None

    def range_match(self, z):
        return (z > self.min_z) & (z < self.max_z)

    def row_match(self, x, row_options):
        left_row, right_row = row_options

        # If your cloud is mirrored, keep this version.
        left = x >= 0
        right = x < 0

        return (left & (self.row == left_row)) | (right & (self.row == right_row))

    def _write_csv(self, df_m: pd.DataFrame):
        df_m.to_csv(self.csv_out, index=False)

    def _write_ply(self, arr_m):
        return

    def write(self, make_point_cloud: bool, overwrite_outputs: bool, write_o3d_ply: bool):
        if not make_point_cloud:
            return
        if (not overwrite_outputs) and os.path.exists(self.csv_out):
            return

        if self.analysis_target is not None:
            df = self.analysis_target.current_points.copy()
            if df.empty:
                return
            for c in ["X", "Y", "Z", "RSSI"]:
                if c not in df.columns:
                    raise ValueError(f"analysis_target.current_points missing required column {c!r}")
            df.loc[:, ["X", "Y", "Z"]] = df[["X", "Y", "Z"]] / 1000.0
            self._write_csv(df)
            return

        if len(self.cloud) == 0:
            return
        arr = np.array(self.cloud)
        if arr.ndim != 2 or arr.shape[1] < 4:
            print(f"[Warning] Bad cloud shape: {arr.shape} in {self.name}")
            return
        arr_m = arr.copy()
        arr_m[:, :3] /= 1000.0
        df = pd.DataFrame(arr_m[:, :4], columns=["X", "Y", "Z", "RSSI"])
        self._write_csv(df)


# ======================================================================
# Core process
# ======================================================================



def normalize_rssi_by_phi_zscore(phi: np.ndarray, rssi: np.ndarray, decimals: int = 3) -> np.ndarray:
    """
    Per-phi RSSI normalization.

    Pick ONE transform below:
      1. exponential transform
      2. square-root transform
      3. no transform, just z-score

    Current active option: square-root transform.
    """
    phi = np.asarray(phi, dtype=np.float32)
    rssi = np.asarray(rssi, dtype=np.float32)
    out = np.zeros_like(rssi, dtype=np.float32)

    phi_key = np.round(phi, decimals=decimals)

    for ph in np.unique(phi_key):
        m = phi_key == ph
        vals = rssi[m]

        if vals.size == 0:
            continue

        mu = np.mean(vals, dtype=np.float64)
        sd = np.std(vals, dtype=np.float64)

        if not np.isfinite(sd) or sd == 0.0:
            z = np.zeros_like(vals, dtype=np.float32)
        else:
            z = ((vals - mu) / sd).astype(np.float32)

        # ============================================================
        # PICK ONE RSSI TRANSFORM
        # Leave exactly one transformed = ... block uncommented.
        # ============================================================

        # Option 1: exponential transform
        # Strongly emphasizes unusually bright returns.
        # Output is positive; z = 0 becomes 1.
        # transformed = np.exp(3.0 * z).astype(np.float32)

        # Option 2: square-root transform
        # Softer than exponential. Output is clipped at 0.
        # z = 0 becomes 1; positive z becomes >1; negative z becomes <1.
        transformed = np.maximum(
            1.0 + np.sign(z) * np.sqrt(np.abs(z)),
            0.0
        ).astype(np.float32)

        # Option 3: no transform
        # Plain per-phi z-score. Can be negative.
        # transformed = z.astype(np.float32)

        out[m] = transformed

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
    if cfg.fusion_method == "imu_interp":
        return fuse_by_imu_interp(
            lidar_np,
            pico_np,
            lidar_ts_col=0,
            pico_ts_col=0,
            pico_imu_ts_col=6,
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


def reconstruct_world_rays(
    fused_np: np.ndarray,
    cfg: AnalysisConfig,
    step_mm: float,
    lidar_height_mm: float,
    roll_offset: float,
    pitch_offset: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return LiDAR beam origins and directions in reconstructed-cloud coordinates.

    This mirrors ``reconstruct_world_points`` for FAD ray-path traits, but uses
    a unit-length beam vector instead of the measured return distance so
    no-return rows still contribute valid gap rays.
    """
    if fused_np.size == 0:
        empty = np.empty((0, 3), dtype=np.float32)
        return empty, empty

    phi = fused_np[:, 1]
    theta = fused_np[:, 2]
    count = fused_np[:, 5]
    roll_deg = fused_np[:, 6]
    pitch_deg = fused_np[:, 7]
    yaw_deg = fused_np[:, 8]

    unit_r = np.ones(fused_np.shape[0], dtype=np.float32)
    beam_dirs_lidar = _to_cartesian_mm(phi, theta, unit_r)

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

    d_mm = count.astype(np.float32) * float(step_mm)
    cart_translation = np.stack(
        [
            np.zeros_like(d_mm, dtype=np.float32),
            np.zeros_like(d_mm, dtype=np.float32),
            d_mm,
        ],
        axis=1,
    )

    lidar_offset_body = np.array(
        [0.0, float(lidar_height_mm), 0.0],
        dtype=np.float32,
    )
    lidar_offset_world = rot.apply(
        np.repeat(lidar_offset_body[None, :], len(d_mm), axis=0)
    ).astype(np.float32, copy=False)

    origins_mm = cart_translation + lidar_offset_world
    directions = rot.apply(beam_dirs_lidar).astype(np.float32, copy=False)

    return origins_mm / 1000.0, directions


def _fad_x_bounds_for_plot(
    plot: "Plot",
    row_options: list[str],
    row_width_m: float,
) -> tuple[float, float]:
    side_sign = getattr(plot, "side_sign", None)

    if side_sign == "positive":
        return 0.0, float(row_width_m)
    if side_sign == "negative":
        return -float(row_width_m), 0.0

    if row_options[0] != row_options[1]:
        if plot.row == row_options[0]:
            return 0.0, float(row_width_m)
        if plot.row == row_options[1]:
            return -float(row_width_m), 0.0

    return -float(row_width_m), float(row_width_m)


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
    should_write = bool(cfg.make_point_cloud)
    if (not should_write) and getattr(plot, "split_source", "distance") == "marks":
        should_write = bool(getattr(cfg, "write_window_pointcloud", False))

    if should_write:
        plot.write(
            make_point_cloud=should_write,
            overwrite_outputs=cfg.overwrite_outputs,
            write_o3d_ply=cfg.write_o3d_ply,
        )
        if getattr(plot, "split_source", "distance") == "marks" and bool(getattr(cfg, "write_window_pointcloud", False)):
            print(f"[MARKS] wrote marker window pointcloud: {plot.csv_out}")



def write_marker_reference_points(scan_base: str, marker_path: str, out_dir: str, step_mm: float, lidar_wheel_offset_mm: float) -> None:
    try:
        df = pd.read_csv(marker_path)
    except pd.errors.EmptyDataError:
        print(f"[MARKS][WARN] Empty marker file for {scan_base}; no marker reference points written.")
        return

    df = df.rename(columns={c: str(c).strip() for c in df.columns})

    # Only encoder_count is needed: marker Z is derived from it. The marker
    # reference file is intentionally minimal -- exactly three columns
    # (X, Y, Z), one row per mark. X = left/right (always 0 for a mark),
    # Y = height (always 0), Z = encoder/travel distance in metres.
    if "encoder_count" not in df.columns:
        df["encoder_count"] = ""

    if df.empty:
        print(f"[MARKS][WARN] Empty marker rows for {scan_base}; no marker reference points written.")
        return

    enc = pd.to_numeric(df["encoder_count"], errors="coerce")
    z_mm = enc.apply(lambda c: marker_count_to_z_mm(c, step_mm=step_mm, lidar_wheel_offset_mm=lidar_wheel_offset_mm))
    out = pd.DataFrame({
        "X": 0.0,
        "Y": 0.0,
        "Z": z_mm / 1000.0,
    })
    out_path = os.path.join(out_dir, f"{scan_base}_marker_points.csv")
    out.to_csv(out_path, index=False)
    print(f"[MARKS] wrote marker reference points: {out_path}")

def is_additional_scan_name(scan_base: str) -> bool:
    s = str(scan_base).strip().lower()
    return s.startswith("scan_")


def _safe_filename_token(value) -> str:
    token = str(value).strip()
    token = token.replace(os.sep, "_")
    if os.altsep:
        token = token.replace(os.altsep, "_")
    token = token.replace(" ", "_")
    token = "".join(
        ch if (ch.isalnum() or ch in {"_", "-", "&"}) else "_"
        for ch in token
    )
    token = token.strip("_")
    return token or "unknown"


def _additional_scan_target_suffix(plot: Plot) -> str:
    target_type = _safe_filename_token(getattr(plot, "target_type", "plot"))
    target_number = _safe_filename_token(getattr(plot, "target_number", getattr(plot, "letter", "target")))
    letter = _safe_filename_token(getattr(plot, "letter", target_number))

    if target_type.lower() in {"none", "nan", "unknown", ""}:
        return letter

    if target_number.lower() in {"none", "nan", "unknown", ""}:
        return f"{target_type}_{letter}"

    if target_number.lower().startswith(target_type.lower() + "_"):
        return target_number

    return f"{target_type}_{target_number}"


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

    side_token = _safe_filename_token(side_label)

    if is_additional_scan_name(str(plot.scan_base)):
        scan_token = _safe_filename_token(plot.scan_base)
        target_suffix = _additional_scan_target_suffix(plot)
        file_stem = f"{scan_token}_{side_token}_{target_suffix}"
    else:
        file_stem = os.path.splitext(os.path.basename(p2.csv_out))[0] + f"_{side_token}"

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
    beam_diag=None,
    roll_offset: float = 0.0,
    pitch_offset: float = 0.0,
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
    lai_traits = {}
    lai_even = float("nan")
    lai_uneven = float("nan")
    n_scans = 0
    n_angles = 0
    density = float("nan")
    stand_topo_per_m = float("nan")
    stand_topo_left_count = float("nan")
    stand_topo_right_count = float("nan")
    stand_topo_left_per_m = float("nan")
    stand_topo_right_per_m = float("nan")
    plot_idx = np.empty((0,), dtype=np.int32)
    lai_plot_idx = np.empty((0,), dtype=np.int32)
    fad_traits = {}
    op_traits = {}
    topo_object_points = []
    write_topology_objects = False

    if np.any(mask):
        p.cloud = data[mask]

        plot_idx = keep_idx[mask]
        fused_plot = fused_np[plot_idx]
        def _fused_col(idx: int, default: float = 0.0) -> np.ndarray:
            if fused_plot.ndim == 2 and fused_plot.shape[1] > idx:
                return fused_plot[:, idx]
            return np.full(plot_idx.shape[0], default, dtype=np.float32)
        points_df = pd.DataFrame(p.cloud[:, :4], columns=["X", "Y", "Z", "RSSI"])
        if p.cloud.shape[1] > 4:
            points_df["rssi_norm"] = p.cloud[:, 4]
        points_df["source_index"] = plot_idx
        points_df["time_s"] = _fused_col(0)
        points_df["phi"] = _fused_col(1)
        points_df["theta"] = _fused_col(2)
        points_df["dist_mm"] = _fused_col(3)
        points_df["range_m"] = _fused_col(3) / 1000.0
        points_df["encoder"] = _fused_col(5)
        points_df["roll_deg"] = _fused_col(6)
        points_df["pitch_deg"] = _fused_col(7)
        points_df["yaw_deg"] = _fused_col(8)
        if beam_diag is None:
            beam_id_plot = np.zeros(plot_idx.shape[0], dtype=np.int32)
        else:
            beam_id_plot = beam_diag.beam_id_by_row[plot_idx]
        points_df["beam_id"] = beam_id_plot.astype(np.int32, copy=False)

        ops_cfg = getattr(cfg, "pointcloud_ops", None) or []
        if ops_cfg:
            target = AnalysisTarget.from_points(
                target_id=p.name,
                target_type=str(getattr(p, "target_type", "plot")),
                scan_id=scan_base,
                points_df=points_df,
                source_indices=keep_idx[mask],
                row=p.row,
                plot=p.letter,
                side=getattr(p, "side_label", None),
            )
            target = apply_pointcloud_ops(
                target,
                ops_cfg,
                default_backend="scipy",
                context={
                    "pcl_backend_name": ((getattr(cfg, "pcl_backend", {}) or {}).get("name")),
                    "additional_scan_positive_side_label": str(getattr(cfg, "additional_scan_positive_side_label", "right")),
                    "additional_scan_negative_side_label": str(getattr(cfg, "additional_scan_negative_side_label", "left")),
                },
            )
            op_traits = dict(target.traits)
            p.analysis_target = target
            p.cloud = target.current_points[["X", "Y", "Z", "RSSI"]].to_numpy(dtype=np.float32, copy=False)
            op_diag = dict(target.diagnostics.get("pointcloud_ops", {}))
            topo_diags = op_diag.get("topology_trait") or []
            if topo_diags:
                topo_d0 = topo_diags[0]
                topo_object_points = list(topo_d0.get("topology_object_points_xyz", []) or [])
                write_topology_objects = bool(topo_d0.get("write_topology_objects", False))
                if write_topology_objects:
                    obj_rows = []
                    for pt in topo_object_points:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 3:
                            obj_rows.append((float(pt[0]), float(pt[1]), float(pt[2])))
                    obj_count = len(obj_rows)
                    if obj_count > 0:
                        base = str(scan_base)
                        parts = base.split("_")
                        if len(parts) >= 4:
                            date_part = "_".join(parts[:3])
                            exp_part = "_".join(parts[3:])
                        else:
                            date_part = base
                            exp_part = "experiment"
                        plot_id = str(p.name)
                        topo_name = f"topology_count_{plot_id}_{obj_count}_{date_part}_{exp_part}.csv"
                        topo_path = os.path.join(p.out_dir, topo_name)
                        pd.DataFrame(obj_rows, columns=["X", "Y", "Z"]).to_csv(topo_path, index=False)
                        print(f"[Topology] wrote counted objects: {topo_path}")
            print(f"[PC_OPS] target={target.target_id} before={op_diag.get('points_before_ops')} after={op_diag.get('points_after_ops')} order={op_diag.get('operation_order')} scalars_before={op_diag.get('available_scalar_columns_before')} scalars_after={op_diag.get('available_scalar_columns_after')}")
        else:
            op_traits = {}
            p.analysis_target = AnalysisTarget.from_points(
                target_id=p.name,
                target_type=str(getattr(p, "target_type", "plot")),
                scan_id=scan_base,
                points_df=points_df,
                source_indices=keep_idx[mask],
                row=p.row,
                plot=p.letter,
                side=getattr(p, "side_label", None),
            )

        n_points = int(p.analysis_target.current_points.shape[0])
        if cfg.run_height:
            h_arr = p.analysis_target.current_points[["X", "Y", "Z", "RSSI"]].to_numpy(dtype=np.float32, copy=False)
            height_m = height_from_world_y(h_arr, alpha=0.01)

    if cfg.run_lai:
        lai_plot_idx = _plot_interval_indices_from_fused(fused_np, p, step_mm)
                # Debug: prove whether LAI is using X-bounded point rows or raw fused rows.
        if bool(getattr(cfg, "debug_lai_bounds", False)):
            lai_idx_debug = np.asarray(lai_plot_idx, dtype=np.int64)
            plot_idx_debug = np.asarray(plot_idx, dtype=np.int64)

            if lai_idx_debug.size and plot_idx_debug.size:
                overlap = np.intersect1d(lai_idx_debug, plot_idx_debug).size
                overlap_pct = 100.0 * overlap / lai_idx_debug.size
            else:
                overlap = 0
                overlap_pct = 0.0

            print(
                f"[LAI_DEBUG] target={p.name} "
                f"lai_fused_rows={lai_idx_debug.size} "
                f"x_filtered_plot_rows={plot_idx_debug.size} "
                f"overlap={overlap} "
                f"overlap_pct_of_lai={overlap_pct:.1f}% "
                f"plot_z=({p.min_z:.1f},{p.max_z:.1f})"
            )
        if lai_plot_idx.size > 0:
            lai_rows = fused_np[lai_plot_idx]
            lai_traits = compute_lai_trait_from_beam_rows(
                distances_m=lai_rows[:, 3].astype(np.float64, copy=False) / 1000.0,
                theta_rad=lai_rows[:, 2].astype(np.float64, copy=False),
                gap_distance_m=30.0,
                distance_column="dist_mm",
                run_mta=bool(getattr(cfg, "run_mta", False)),
                mta_lo_deg=float(getattr(cfg, "mta_lo_deg", 25.0)),
                mta_hi_deg=float(getattr(cfg, "mta_hi_deg", 65.0)),
                mta_n_bins=int(getattr(cfg, "mta_n_bins", 8)),
                mta_min_rays_per_bin=int(getattr(cfg, "mta_min_rays_per_bin", 30)),
            )
        elif hasattr(p, "analysis_target"):
            lai_traits = compute_lai_trait_from_target(
                p.analysis_target,
                gap_distance_m=30.0,
                run_mta=bool(getattr(cfg, "run_mta", False)),
                mta_lo_deg=float(getattr(cfg, "mta_lo_deg", 25.0)),
                mta_hi_deg=float(getattr(cfg, "mta_hi_deg", 65.0)),
                mta_n_bins=int(getattr(cfg, "mta_n_bins", 8)),
                mta_min_rays_per_bin=int(getattr(cfg, "mta_min_rays_per_bin", 30)),
            )
        else:
            lai_traits = compute_lai_trait_from_beam_rows(
                distances_m=np.empty((0,), dtype=np.float64),
                theta_rad=np.empty((0,), dtype=np.float64),
                gap_distance_m=30.0,
                distance_column="dist_mm",
                run_mta=bool(getattr(cfg, "run_mta", False)),
                mta_lo_deg=float(getattr(cfg, "mta_lo_deg", 25.0)),
                mta_hi_deg=float(getattr(cfg, "mta_hi_deg", 65.0)),
                mta_n_bins=int(getattr(cfg, "mta_n_bins", 8)),
                mta_min_rays_per_bin=int(getattr(cfg, "mta_min_rays_per_bin", 30)),
            )

        if hasattr(p, "analysis_target"):
            p.analysis_target.traits.update(lai_traits)
        lai_even = float(lai_traits.get("lai_even", float("nan")))
        lai_uneven = float(lai_traits.get("lai_uneven", float("nan")))
        n_scans = int(lai_traits.get("lai_n_scans", 0) or 0)
        n_angles = int(lai_traits.get("lai_n_angles", 0) or 0)

    if cfg.run_fad:
        row_width_m = _to_m_units(cfg.row_width_u, cfg.dim_units)
        x_min_m, x_max_m = _fad_x_bounds_for_plot(p, row_options, row_width_m)
        z_min_m = float(p.min_z) / 1000.0
        z_max_m = float(p.max_z) / 1000.0

        if p.analysis_target is not None:
            fad_points_m = (
                p.analysis_target.current_points[["X", "Y", "Z"]]
                .to_numpy(dtype=np.float64, copy=False)
                / 1000.0
            )
        else:
            fad_points_m = np.empty((0, 3), dtype=np.float64)

        height_result = estimate_fad_height_from_points(
            fad_points_m,
            percentile=cfg.fad_height_percentile,
            y_min_m=cfg.fad_y_min_m,
            buffer_m=cfg.fad_height_buffer_m,
            grubbs_alpha=cfg.fad_grubbs_alpha,
        )
        fad_traits.update(height_result_to_traits(height_result))

        fad_box: Box3D = make_fad_box_from_footprint_and_height(
            x_min_m=x_min_m,
            x_max_m=x_max_m,
            z_min_m=z_min_m,
            z_max_m=z_max_m,
            height=height_result,
            y_min_m=cfg.fad_y_min_m,
        )

        fad_plot_idx = _plot_interval_indices_from_fused(fused_np, p, step_mm)
        fad_rows = fused_np[fad_plot_idx]
        origins_m, directions_m = reconstruct_world_rays(
            fad_rows,
            cfg,
            step_mm=step_mm,
            lidar_height_mm=lidar_height_mm,
            roll_offset=roll_offset,
            pitch_offset=pitch_offset,
        )
        dist_mm = fad_rows[:, 3].astype(np.float64, copy=False) if fad_rows.size else np.empty((0,), dtype=np.float64)
        raw_hit_mask = dist_mm > 0.0
        ranges_m = dist_mm / 1000.0
        ranges_m = ranges_m.astype(np.float64, copy=True)
        ranges_m[~raw_hit_mask] = np.inf

        fad_traits.update(
            compute_fad_traits(
                origins_m=origins_m,
                directions_m=directions_m,
                ranges_m=ranges_m,
                raw_hit_mask=raw_hit_mask,
                box=fad_box,
                g_function=cfg.fad_g_function,
                layer_thickness_m=cfg.fad_layer_thickness_m if cfg.fad_run_layers else None,
                include_layer_columns=cfg.fad_include_layer_columns if cfg.fad_run_layers else False,
            )
        )
        if "fad_lai_from_layers" in fad_traits:
            fad_traits["fad_integrated_m2_m2"] = fad_traits["fad_lai_from_layers"]

        fad_value = float(fad_traits.get("fad_app_m2_m3", float("nan")))
        returns = int(np.sum(raw_hit_mask))
        no_returns = int(raw_hit_mask.size - returns)
        target_id = p.analysis_target.target_id if p.analysis_target is not None else p.name
        print(
            f"[FAD] target={target_id} rays={int(fad_plot_idx.size)} "
            f"returns={returns} no_returns={no_returns} "
            f"height={height_result.height_m:.3f} fad={fad_value:.3f}"
        )

    z_min, z_max = p.min_z, p.max_z
    plot_length_m = max((float(z_max) - float(z_min)) / 1000.0, 0.0)
    plot_width_m = _compute_plot_width(p.cloud, 2.0 * _to_m_units(cfg.row_width_u, cfg.dim_units))
    if np.isfinite(plot_width_m) and plot_length_m > 0:
        area_m2 = plot_width_m * plot_length_m
    else:
        area_m2 = float("nan")
    density = n_points / area_m2 if (np.isfinite(area_m2) and area_m2 > 0) else float("nan")

    stand_topo_per_m = float("nan")
    stand_topo_left_count = float("nan")
    stand_topo_right_count = float("nan")
    if op_traits:
        stand_topo_per_m = float(op_traits.get("topo_avg_per_m", op_traits.get("topo_count", float("nan"))))
        stand_topo_left_count = float(op_traits.get("topo_left_count", float("nan")))
        stand_topo_right_count = float(op_traits.get("topo_right_count", float("nan")))
        stand_topo_left_per_m = float(op_traits.get("topo_left_per_m", op_traits.get("topo_count_left", float("nan"))))
        stand_topo_right_per_m = float(op_traits.get("topo_right_per_m", op_traits.get("topo_count_right", float("nan"))))

    side_label = getattr(p, "side_label", None)

    result = {
        "scan": scan_base if not side_label else f"{scan_base}_{side_label}",
        "row": side_label if side_label else p.row,
        "side": side_label,
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
        "stand_topo_left_per_m": stand_topo_left_per_m,
        "stand_topo_right_per_m": stand_topo_right_per_m,
        "voxel_count": op_traits.get("voxel_count", float("nan")),
        "stacked_hull_volume_m3": op_traits.get("stacked_hull_volume_m3", float("nan")),
        "max_spread_m": op_traits.get("max_spread_m", float("nan")),
        "spread_at_50_m": op_traits.get("spread_at_50_m", float("nan")),
    }
    result.update(lai_traits)
    if not bool(getattr(cfg, "run_mta", False)):
        for key in ("lai_mta_deg", "lai_mta_sem_deg", "lai_mta_slope", "lai_mta_n_bins"):
            result.pop(key, None)
    result.update(fad_traits)

    mta_msg = ""
    if bool(getattr(cfg, "run_mta", False)):
        mta_msg = (
            f", MTA={float(lai_traits.get('lai_mta_deg', float('nan'))):.1f} deg "
            f"({int(lai_traits.get('lai_mta_n_bins', 0) or 0)} bins)"
        )

    print(
        f"[Traits] scan={scan_base}, plot={p.name}, "
        f"height={height_m:.3f} m, LAI_even={lai_even:.3f}, LAI_uneven={lai_uneven:.3f}"
        f"{mta_msg}, "
        f"stand_topo_per_m={stand_topo_per_m:.3f}, "
        f"count_left={stand_topo_left_count:.2f}, count_right={stand_topo_right_count:.2f}, "
        f"points={n_points}, scans={n_scans}, angles={n_angles}"
    )
    return result


def trait_summary_row(rec: dict, cfg: AnalysisConfig) -> dict:
    row = {
        "scan": rec.get("scan"),
        "row": rec.get("row"),
        "plot": rec.get("plot"),
        "split_source": rec.get("split_source"),
        "target_type": rec.get("target_type"),
        "target_number": rec.get("target_number"),
        "z_min_m": rec.get("z_min_m", float("nan")),
        "z_max_m": rec.get("z_max_m", float("nan")),
        "points": rec.get("points", float("nan")),
        "height_m": rec.get("height_m", float("nan")),
        "lai_even": rec.get("lai_even", float("nan")),
        "lai_uneven": rec.get("lai_uneven", float("nan")),
        "point_density_m2": rec.get("point_density_m2", float("nan")),
        "plot_length_m": rec.get("plot_length_m", float("nan")),
        "plot_width_m": rec.get("plot_width_m", float("nan")),
        "stand_topo_per_m": rec.get("stand_topo_per_m", float("nan")),
        "stand_topo_left_count": rec.get("stand_topo_left_count", float("nan")),
        "stand_topo_right_count": rec.get("stand_topo_right_count", float("nan")),
        "stand_topo_left_per_m": rec.get("stand_topo_left_per_m", float("nan")),
        "stand_topo_right_per_m": rec.get("stand_topo_right_per_m", float("nan")),
        "voxel_count": rec.get("voxel_count", float("nan")),
        "stacked_hull_volume_m3": rec.get("stacked_hull_volume_m3", float("nan")),
        "max_spread_m": rec.get("max_spread_m", float("nan")),
        "spread_at_50_m": rec.get("spread_at_50_m", float("nan")),
    }
    if bool(getattr(cfg, "run_mta", False)):
        row.update({
            "lai_mta_deg": rec.get("lai_mta_deg", float("nan")),
            "lai_mta_sem_deg": rec.get("lai_mta_sem_deg", float("nan")),
            "lai_mta_slope": rec.get("lai_mta_slope", float("nan")),
            "lai_mta_n_bins": rec.get("lai_mta_n_bins", 0),
        })
    return row


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

    # Preserve raw RSSI in column 3; add normalized scalar as column 4
    if out.shape[1] == 4:
        out = np.concatenate([out, rssi_norm.reshape(-1, 1)], axis=1)
    else:
        out[:, 4] = rssi_norm
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

    beam_diag = compute_beam_diagnostics(fused_np, rounding_decimals=6)

    # Beam diagnostics are kept in memory because beam_id is used downstream in
    # AnalysisTarget metadata. Do not write the diagnostics CSV during routine runs.
    #
    # beam_diag_csv = write_beam_diagnostics_csv(out_dir, scan_base, beam_diag)
    # print(f"[BeamDiag] wrote {beam_diag_csv}")
    # print(
    #     "[BeamDiag] "
    #     f"rows={beam_diag.summary.get('n_fused_rows')} "
    #     f"unique_beams={beam_diag.summary.get('n_unique_beams')} "
    #     f"unique_phi={beam_diag.summary.get('n_unique_phi')} "
    #     f"unique_theta={beam_diag.summary.get('n_unique_theta')} "
    #     f"rows_per_beam(min/median/max/mean)="
    #     f"{beam_diag.summary.get('rows_per_beam_min')}/"
    #     f"{beam_diag.summary.get('rows_per_beam_median')}/"
    #     f"{beam_diag.summary.get('rows_per_beam_max')}/"
    #     f"{beam_diag.summary.get('rows_per_beam_mean'):.2f} "
    #     f"stable={beam_diag.summary.get('beam_count_stable')} "
    #     f"rotation={beam_diag.summary.get('rotation_inference')}: {beam_diag.summary.get('rotation_note')}"
    # )

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
            free_marks_as=str(getattr(cfg, "free_marks_as", "none")),
            zmax_clip=zmax,
        )

        if len(segments) == 0:
            empty_mode = str(getattr(cfg, "empty_mark_file", "skip")).strip().lower()
            if empty_mode == "distance":
                print(f"[MARKS][WARN] No usable marker segments for {scan_base}; falling back to distance splitting.")
                split_source = "distance"
            elif empty_mode == "error":
                raise ValueError(f"No usable marker segments for {scan_base} from {marker_path}")
            else:
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

    if split_source == "distance":
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

    if bool(getattr(cfg, "write_reference_points", False)) and split_source == "marks" and marker_path is not None:
        write_marker_reference_points(
            scan_base=scan_base,
            marker_path=str(marker_path),
            out_dir=out_dir,
            step_mm=step_mm,
            lidar_wheel_offset_mm=lidar_wheel_offset_mm,
        )

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
            beam_diag,
            roll_offset=roll_offset,
            pitch_offset=pitch_offset,
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
        traits_rows = []
        for rec in all_trait_records:
            traits_rows.append(trait_summary_row(rec, cfg))
        traits_df = pd.DataFrame.from_records(traits_rows)
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
