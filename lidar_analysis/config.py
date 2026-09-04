from dataclasses import dataclass, asdict
import math
from pathlib import Path
from typing import List
import warnings

@dataclass
class AnalysisConfig:
    data_dirs: List[Path]
    calibration_dir: Path
    cart_id: str
    split_source: str = "distance"
    mark_target_type: str = "auto"
    mark_z_buffer_u: float = 0.0
    markers_dirname: str = "markers"
    missing_mark_file: str = "error"
    write_marker_pointcloud: bool = False
    write_reference_points: bool = False
    write_window_pointcloud: bool = False
    free_marks_as: str = "none"
    empty_mark_file: str = "skip"
    force_two_sided_targets: bool = False
    additional_scan_side_split: bool = False
    additional_scan_side_axis: str = "x"
    additional_scan_positive_side_label: str = "right"
    additional_scan_negative_side_label: str = "left"
    make_point_cloud: bool = True
    overwrite_outputs: bool = True
    reprocess_scans: bool = True
    use_imu: bool = False
    imu_zero_mode: str = "dense_median"
    imu_zero_fraction: float = 0.5
    use_heading: bool = False
    heading_sign: float = 1.0
    roll_sign: float = -1.0
    pitch_sign: float = -1.0
    normalize_rssi: bool = False
    rssi_norm_mode: str = "percentile"
    rssi_norm_transform: str = "sqrt"
    use_rssi_filter: bool = False
    use_local_ground_filter: bool = False
    local_ground_x_bin_m: float = 0.05
    local_ground_z_bin_m: float = 0.05
    local_ground_quantile: float = 0.05
    local_ground_min_points_per_xz_bin: int = 5
    local_ground_seed_y_min_m: float | None = None
    local_ground_seed_y_max_m: float | None = None
    min_height_agl_m: float = 0.05
    rssi_min: float | None = None
    rssi_max: float | None = None
    fusion_method: str = "interp"
    dim_units: str = "m"
    row_width_u: float = 5.0
    start_u: float = 0.0
    split_u: float = 0.0
    x_min_u: float | None = None
    end_buffer_u: float = 0.5
    n_plots: int | None = None
    max_y_u: float | None = None
    min_radius_u: float | None = None
    run_lai: bool = False
    run_mta: bool = False
    mta_angle_bin_deg: float = 5.0
    mta_diagnostic: bool = False
    mta_lo_deg: float = 25.0
    mta_hi_deg: float = 65.0
    mta_n_bins: int = 8
    mta_min_rays_per_bin: int = 30
    mta_fit_angle_min_deg: float = 25.0
    mta_fit_angle_max_deg: float = 65.0
    mta_min_path_m_per_bin: float = 1.0
    mta_min_valid_fit_bins: int = 3
    mta_min_solid_angle_coverage: float = 0.8
    mta_max_observation_range_m: float | None = 60.0
    run_height: bool = False
    run_fad: bool = False
    fad_height_percentile: float = 99.0
    fad_x_near_m: float = 0.0
    fad_y_min_m: float = 0.03
    fad_height_buffer_m: float = 0.0
    fad_grubbs_alpha: float = 0.01
    fad_g_function: str = "spherical"
    fad_run_layers: bool = False
    fad_layer_thickness_m: float | None = 0.10
    fad_include_layer_columns: bool = True
    run_pai: bool = False
    pai_g_function: str = "spherical"
    pai_g_value: float = 0.5
    pai_height_percentile: float = 99.0
    pai_grubbs_alpha: float = 0.01
    pai_y_min_m: float = 0.10
    pai_x_near_m: float = 0.0
    pai_height_buffer_m: float = 0.0
    pai_diagnostic: bool = False
    pai_run_layers: bool = True
    pai_run_joint_profile: bool = False
    pai_run_conditional_profile: bool = True
    pai_layer_thickness_m: float | None = 0.10
    pai_include_layer_columns: bool = False
    write_lidar_per_plot: bool = True

    # Deprecated compatibility shims.
    # These keep old pipeline_core references from crashing while O3D/topology
    # code is being pruned. They must stay false and should not appear in new
    # experiment configs.
    write_o3d_ply: bool = False
    run_o3d_metrics: bool = False
    run_topology: bool = False
    pointcloud_ops: list[dict] | None = None
    pcl_backend: dict | None = None


def default_analysis_yaml_dict() -> dict:
    d = asdict(AnalysisConfig(data_dirs=[], calibration_dir=Path('.'), cart_id='CART'))
    for k in [
        "data_dirs",
        "calibration_dir",
        "cart_id",
        "reprocess_scans",
        "write_o3d_ply",
        "run_o3d_metrics",
        "run_topology",
        "mta_lo_deg",
        "mta_hi_deg",
        "mta_n_bins",
        "mta_fit_angle_min_deg",
        "mta_fit_angle_max_deg",
        "mta_min_rays_per_bin",
        "mta_min_path_m_per_bin",
        "mta_min_valid_fit_bins",
        "mta_min_solid_angle_coverage",
        "mta_max_observation_range_m",
        "pai_run_layers",
        "pai_run_joint_profile",
        "pai_run_conditional_profile",
    ]:
        d.pop(k,None)
    d["generate_pointclouds"] = d.pop("make_point_cloud")
    d["overwrite_pointclouds"] = d.pop("overwrite_outputs")

    # Backward compatibility:
    # Older configs may use apply_imu, but AnalysisConfig uses use_imu.
    if "apply_imu" in d and "use_imu" not in d:
        d["use_imu"] = d.pop("apply_imu")
    elif "apply_imu" in d:
        d.pop("apply_imu")
    return d


def normalize_rssi_mode(mode: str) -> str:
    m = str(mode).strip().lower()
    if m in {"zscore", "percentile"}:
        return m
    raise ValueError(f"rssi_norm_mode must be 'zscore' or 'percentile'; got {mode!r}")


def normalize_rssi_transform(transform: str) -> str:
    value = str(transform).strip().lower()
    aliases = {"none": "none", "sqrt": "sqrt", "log": "log1p", "log1p": "log1p",
               "exp": "exponential", "exponential": "exponential"}
    if value in aliases:
        return aliases[value]
    raise ValueError(
        "rssi_norm_transform must be one of none, sqrt, log/log1p, or exp/exponential; "
        f"got {transform!r}"
    )


def validate_mta_config(cfg: AnalysisConfig) -> AnalysisConfig:
    numeric = {
        "mta_angle_bin_deg": cfg.mta_angle_bin_deg,
        "mta_fit_angle_min_deg": cfg.mta_fit_angle_min_deg,
        "mta_fit_angle_max_deg": cfg.mta_fit_angle_max_deg,
        "mta_min_path_m_per_bin": cfg.mta_min_path_m_per_bin,
        "mta_min_solid_angle_coverage": cfg.mta_min_solid_angle_coverage,
    }
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in numeric.values()):
        raise ValueError("MTA numeric settings must be finite numbers, not booleans")
    if cfg.mta_angle_bin_deg <= 0.0:
        raise ValueError("mta_angle_bin_deg must be finite and greater than zero")
    if not 0.0 <= cfg.mta_fit_angle_min_deg < cfg.mta_fit_angle_max_deg <= 90.0:
        raise ValueError("MTA fit angles must satisfy 0 <= min < max <= 90 degrees")
    if not (
        math.isclose(cfg.mta_fit_angle_min_deg, 25.0, abs_tol=1e-12)
        and math.isclose(cfg.mta_fit_angle_max_deg, 65.0, abs_tol=1e-12)
    ):
        raise ValueError("bounded_lang_v1 requires the fixed 25-65 degree fitting interval")
    if cfg.mta_min_path_m_per_bin < 0.0:
        raise ValueError("mta_min_path_m_per_bin must be nonnegative")
    if isinstance(cfg.mta_min_rays_per_bin, bool) or cfg.mta_min_rays_per_bin < 1:
        raise ValueError("mta_min_rays_per_bin must be a positive integer")
    if isinstance(cfg.mta_min_valid_fit_bins, bool) or cfg.mta_min_valid_fit_bins < 2:
        raise ValueError("mta_min_valid_fit_bins must be at least 2")
    if not 0.0 < cfg.mta_min_solid_angle_coverage <= 1.0:
        raise ValueError("mta_min_solid_angle_coverage must be in (0, 1]")
    if cfg.mta_max_observation_range_m is not None and (
        isinstance(cfg.mta_max_observation_range_m, bool)
        or not math.isfinite(float(cfg.mta_max_observation_range_m))
        or cfg.mta_max_observation_range_m <= 0.0
    ):
        raise ValueError("mta_max_observation_range_m must be null or a finite positive number")
    return cfg


def map_deprecated_analysis_keys(analysis_cfg: dict) -> dict:
    out = dict(analysis_cfg)
    if "rssi_norm_scope" in out:
        warnings.warn("rssi_norm_scope is deprecated and ignored; normalization runs after global masks.")
        out.pop("rssi_norm_scope", None)
    if "mta_fit_angle_min_deg" not in out and "mta_lo_deg" in out:
        out["mta_fit_angle_min_deg"] = out["mta_lo_deg"]
    if "mta_fit_angle_max_deg" not in out and "mta_hi_deg" in out:
        out["mta_fit_angle_max_deg"] = out["mta_hi_deg"]
    if "mta_angle_bin_deg" not in out and "mta_n_bins" in out:
        lo = float(out.get("mta_fit_angle_min_deg", 25.0))
        hi = float(out.get("mta_fit_angle_max_deg", 65.0))
        n_bins = int(out["mta_n_bins"])
        if n_bins > 0:
            out["mta_angle_bin_deg"] = (hi - lo) / n_bins
    return out
