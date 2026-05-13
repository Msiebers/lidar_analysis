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

def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def render_default_experiment_config_yaml(experiment: str) -> str:
    return f"""# LiDAR experiment configuration template
# Safe defaults: processing is OFF until this file is reviewed.

experiment_name: {experiment}
processing_mode: off   # off | local | auto_publish
config_reviewed: false # set true after reviewing and editing this file
config_note: "Template only. Edit this config before enabling processing."

raw_data_path: /mnt/cartcity/raw_data/{experiment}
output_path: /mnt/cartcity/experiments/{experiment}

sharing:
  enabled: false

notifications:
  enabled: false

analysis:
  # Core pipeline behavior
  fusion_method: interp
  dim_units: ft
  row_width_u: null
  start_u: null
  split_u: null
  n_plots: null
  end_buffer_u: 0.0
  max_y_u: null
  x_min_u: null
  min_radius_u: 0.1

  # IMU and heading options
  apply_imu: false
  imu_zero_mode: dense_median
  imu_zero_fraction: 0.5
  use_heading: false
  heading_sign: 1.0
  roll_sign: 1.0
  pitch_sign: -1.0

  # RSSI options
  normalize_rssi: false
  rssi_norm_mode: zscore
  rssi_norm_scope: scan_after_global_masks
  use_rssi_filter: false
  rssi_min: null
  rssi_max: null

  # Output safety defaults
  generate_pointclouds: false
  append_results_csv: false
  overwrite_pointclouds: false
  write_lidar_per_plot: false

  # Metrics (disabled by default)
  run_lai: false
  run_height: false
  run_topology: false
  topo_min_persistence: 0.35
  topo_background_cut: 0.0
  topo_x_bin_m: 0.01
  topo_z_bin_m: 0.01

  # Marker splitting (canonical block)
  split_source: distance  # distance | marks
  marks:
    target_type: auto
    buffer_u: 0.0
    missing_file: error   # error | distance | skip
    write_pointcloud: false

  # Additional_Scans side split (disabled by default)
  additional_scan_side_split: false
  additional_scan_side_axis: x
  additional_scan_positive_side_label: right
  additional_scan_negative_side_label: left

  # PCL post-processing schema (disabled by default)
  pointcloud_ops: []
  pcl_backend:
    enabled: false
    executable: /home/central/Documents/lidar_analysis/cpp_ops/build/pcl_pointcloud_ops_batch
    work_dir: null
    keep_intermediate: true
    fail_if_missing: false
"""


def default_experiment_config(experiment: str) -> dict:
    text = render_default_experiment_config_yaml(experiment)
    parsed = yaml.safe_load(text)
    return parsed if isinstance(parsed, dict) else {}


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
        save_text(exp_config_path, render_default_experiment_config_yaml(experiment))


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scaffold_experiments.py <experiment_name>")

    ensure_experiment_scaffold(sys.argv[1])
    print(f"Scaffold ensured for experiment: {sys.argv[1]}")
