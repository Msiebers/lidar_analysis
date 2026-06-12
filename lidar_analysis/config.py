from dataclasses import dataclass, asdict
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
    use_rssi_filter: bool = False
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
    run_height: bool = False
    run_fad: bool = False
    fad_height_percentile: float = 99.0
    fad_y_min_m: float = 0.03
    fad_height_buffer_m: float = 0.0
    fad_grubbs_alpha: float = 0.01
    fad_g_function: str = "spherical"
    fad_run_layers: bool = False
    fad_layer_thickness_m: float | None = 0.10
    fad_include_layer_columns: bool = True
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
    ]:
        d.pop(k,None)
    d["generate_pointclouds"] = d.pop("make_point_cloud")
    d["overwrite_pointclouds"] = d.pop("overwrite_outputs")
    d# Backward compatibility:
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


def map_deprecated_analysis_keys(analysis_cfg: dict) -> dict:
    out = dict(analysis_cfg)
    if "rssi_norm_scope" in out:
        warnings.warn("rssi_norm_scope is deprecated and ignored; normalization runs after global masks.")
        out.pop("rssi_norm_scope", None)
    return out
