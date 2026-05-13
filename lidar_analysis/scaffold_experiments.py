#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

try:
    from .yaml_loader import yaml
except Exception:
    from yaml_loader import yaml

CARTCITY_ROOT = Path("/mnt/cartcity")
EXPERIMENTS_ROOT = CARTCITY_ROOT / "experiments"


def save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def default_experiment_config(experiment: str) -> dict:
    return {
        "experiment_name": experiment,
        "processing_mode": "off", #off, local or auto_publish
        "config_reviewed": False,
        "config_note": "Template only. Review and edit this config before enabling processing.",
        "raw_data_path": f"/mnt/cartcity/raw_data/{experiment}",
        "output_path": f"/mnt/cartcity/experiments/{experiment}",
        "sharing": {
            "enabled": False,
        },
        "notifications": {
            "enabled": False,
        },
        "analysis": {
            
            "fusion_method": "interp",

            "dim_units": "ft",
            
            "row_width_u": 5,
            "start_u": 3.0,
            "split_u": 5,
            "n_plots": None,
            "end_buffer_u": 0.0,
            "max_y_u": None,
            "x_min_u": None,
            "min_radius_u": 0.1,

            "apply_imu": False,
            "imu_zero_mode": "dense_median",
            "imu_zero_fraction": 0.5,
            "use_heading": False,
            "heading_sign": 1.0,

            "normalize_rssi": False,
            "rssi_norm_mode": "zscore",
            "use_rssi_filter": False,
            "rssi_min": None,
            "rssi_max": None,

            "generate_pointclouds": False,
            "append_results_csv": False,
            "overwrite_pointclouds": True,

            "write_o3d_ply": False,
            "use_o3d_sor": False,
            "o3d_sor_nb_neighbors": 3,
            "o3d_sor_std_ratio": 2.0,
            "use_o3d_voxel": False,
            "o3d_voxel_size_mm": 5.0,
            
            "run_lai": False,
            "run_height": False,
            "run_topology": False,
            "run_o3d_metrics": False,
            "write_lidar_per_plot": False,
            "topo_min_persistence": 0.35,
            "topo_background_cut": 0.0,
            "topo_x_bin_m": 0.01,
            "topo_z_bin_m": 0.01,
            "roll_sign": 1.0,
            "pitch_sign": -1.0,
            "pointcloud_ops": [],
            "pcl_backend": {
                "enabled": False,
                "executable": "/home/central/Documents/lidar_analysis/cpp_ops/build/pcl_pointcloud_ops_batch",
                "work_dir": None,
                "keep_intermediate": True,
                "fail_if_missing": False,
            },
        },
    }


def ensure_experiment_scaffold(experiment: str) -> None:
    exp_root = EXPERIMENTS_ROOT / experiment

    pointclouds_dir = exp_root / "pointclouds"
    results_dir = exp_root / "results"
    metadata_dir = exp_root / "scan_metadata"
    exp_config_path = exp_root / "experiment_config.yaml"

    pointclouds_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if not exp_config_path.exists():
        save_yaml(exp_config_path, default_experiment_config(experiment))


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scaffold_experiments.py <experiment_name>")

    ensure_experiment_scaffold(sys.argv[1])
    print(f"Scaffold ensured for experiment: {sys.argv[1]}")
