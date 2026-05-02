from dataclasses import dataclass
from pathlib import Path
from typing import List

@dataclass
class AnalysisConfig:
    # Core paths
    data_dirs: List[Path]
    calibration_dir: Path
    cart_id: str

    # Splitting source
    split_source: str = "distance"      # "distance" or "marks"
    use_markers: bool = False

    # Marker splitting
    mark_target_type: str = "auto"      # "auto", "plot", or "plant"
    marker_target_type: str = "auto"    # alias for mark_target_type
    mark_z_buffer_u: float = 0.0        # uses dim_units
    plant_marker_buffer_u: float = 0.0
    plot_marker_buffer_u: float = 0.0
    markers_dirname: str = "markers"
    missing_mark_file: str = "error"    # "error", "distance", or "skip"
    markers_required: bool = False
    write_marker_pointcloud: bool = False

    # Output / processing switches
    make_point_cloud: bool = False
    overwrite_outputs: bool = True
    reprocess_scans: bool = True

    use_imu: bool = False
    imu_zero_mode: str = "dense_median"   # "calibration" or "median"
    imu_zero_fraction: float = 0.5 
    use_heading: bool = False
    heading_sign: float = 1.0
    roll_sign: float = 1.0
    pitch_sign: float = 1.0
    
    normalize_rssi: bool = True
    rssi_norm_mode: str = "percentile" # or "zscore"
    use_rssi_filter: bool = False
    rssi_min: float | None = None
    rssi_max: float | None = None


    write_o3d_ply: bool = False
    fusion_method: str = "interp"

    # Dimensions / splitting controls
    dim_units: str = "ft"            # "m" or "ft"
    row_width_u: float = 10.0
    start_u: float = 0.0
    split_u: float = 10.0
    x_min_u: float | None = None
    end_buffer_u: float = 3.5
    n_plots: int | None = None
    max_y_u: float | None = None
    min_radius_u: float | None = 0.05

    # Open3D
    use_o3d_sor: bool = True
    o3d_sor_nb_neighbors: int = 5
    o3d_sor_std_ratio: float = 2.0
    use_o3d_voxel: bool = True
    o3d_voxel_size_mm: float = 5.0

    # Topology parameters
    topo_min_persistence: float = 0.35
    topo_background_cut: float = 0.0
    topo_x_bin_m: float = 0.02
    topo_z_bin_m: float = 0.02

    # Algorithm switches
    run_lai: bool = True
    run_height: bool = True
    run_topology: bool = True
    run_o3d_metrics: bool = True

    # Optional output
    write_lidar_per_plot: bool = False
