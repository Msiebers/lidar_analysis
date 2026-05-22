from dataclasses import dataclass
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# SINGLE SOURCE OF TRUTH FOR DEFAULTS
#
# Every default below is the value that actually runs today (previously these
# lived as duplicated literals inside central_runner.build_config). build_config
# now reads its defaults from this dataclass instead of carrying its own copy,
# so the two can no longer drift, and the experiment scaffold can be generated
# from here. To change what a new experiment gets by default, change it HERE
# and nowhere else.
# ---------------------------------------------------------------------------


@dataclass
class AnalysisConfig:
    # Core paths (always supplied by the runner; no meaningful default)
    data_dirs: List[Path]
    calibration_dir: Path
    cart_id: str

    # Splitting source
    split_source: str = "distance"      # "distance" or "marks"

    # Marker splitting
    mark_target_type: str = "auto"      # "auto", "plot", or "plant"
    mark_z_buffer_u: float = 0.0        # uses dim_units
    markers_dirname: str = "markers"
    missing_mark_file: str = "error"    # "error", "distance", or "skip"
    write_marker_pointcloud: bool = False  # legacy alias
    write_reference_points: bool = False
    write_window_pointcloud: bool = False
    free_marks_as: str = "none"         # "none" or "plant"
    empty_mark_file: str = "skip"       # "error", "distance", or "skip"
    additional_scan_side_split: bool = False
    additional_scan_side_axis: str = "x"
    additional_scan_positive_side_label: str = "right"
    additional_scan_negative_side_label: str = "left"

    # Output / processing switches
    make_point_cloud: bool = True
    overwrite_outputs: bool = True
    reprocess_scans: bool = True

    use_imu: bool = False
    imu_zero_mode: str = "dense_median"   # "calibration" or "median"
    imu_zero_fraction: float = 0.5
    use_heading: bool = False
    heading_sign: float = 1.0
    roll_sign: float = -1.0
    pitch_sign: float = -1.0

    normalize_rssi: bool = False
    rssi_norm_mode: str = "percentile"  # or "zscore"
    use_rssi_filter: bool = False
    rssi_min: float | None = None
    rssi_max: float | None = None

    write_o3d_ply: bool = False
    fusion_method: str = "interp"

    # Dimensions / splitting controls
    dim_units: str = "m"             # "m" or "ft"
    row_width_u: float = 5.0
    start_u: float = 0.0
    split_u: float = 0.0
    x_min_u: float | None = None
    end_buffer_u: float = 0.5
    n_plots: int | None = None
    max_y_u: float | None = None
    min_radius_u: float | None = None

    # Open3D (analysis backend deprecated; retained, read, but unused)
    use_o3d_sor: bool = False
    o3d_sor_nb_neighbors: int = 5
    o3d_sor_std_ratio: float = 2.0
    use_o3d_voxel: bool = False
    o3d_voxel_size_mm: float = 5.0

    # Topology parameters
    topo_min_persistence: float = 0.35
    topo_background_cut: float = 0.0
    topo_x_bin_m: float = 0.01
    topo_z_bin_m: float = 0.01

    # Algorithm switches
    run_lai: bool = False
    run_height: bool = False
    run_topology: bool = True
    run_o3d_metrics: bool = False

    # Optional output
    write_lidar_per_plot: bool = True
