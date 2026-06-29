# Overview

This repository contains the central LiDAR analysis pipeline for field phenotyping cart data. It combines synchronized SICK multi-beam LiDAR CSV files, Pico encoder/IMU CSV files, optional marker CSV files, cart calibration YAML, and experiment YAML settings to generate per-target point-cloud CSVs and trait summaries.

The active command-line runner is `lidar_analysis/central_runner.py`. Its main processing stage calls `lidar_analysis/pipeline_core.py::process_scan` through `lidar_analysis/pipeline_stages.py::ProcessScanStage`.

## Intended Users

These documents are for researchers running experiments, developers extending the pipeline, and reviewers who need to understand how inputs become point clouds and trait tables.

## Coordinate System

The project convention is:

| Axis | Meaning |
| --- | --- |
| `X` | left/right across the crop row |
| `Y` | vertical height |
| `Z` | travel direction along the row |

`lidar_analysis/pipeline_core.py::Plot.write` writes point-cloud coordinates in meters. Internally, many pipeline calculations use millimeters.

## Main Inputs

| Input | Expected location | Evidence |
| --- | --- | --- |
| LiDAR CSV | input directory root, file ending `_lidar.csv` | `central_runner.discover_scan_pairs` |
| Pico encoder/IMU CSV | input directory root, file ending `_pico.csv` | `central_runner.discover_scan_pairs` |
| Marker CSV | usually `markers/`, optional unless marker splitting is enabled | `mark_splitting.find_marker_file_for_scan` |
| Cart calibration YAML | `cart_config.yaml` in the input directory | `central_runner.run_experiment_date` |
| Experiment config YAML | `experiment_config.yaml`, `source/experiment_config.yaml`, or `--config` path | `central_runner.resolve_config_path` |

In typical project data folders, `cart_config.yaml` may already be present while `experiment_config.yaml` is absent. The runner supports this by accepting an external experiment config through `--config`.

Required LiDAR columns are loaded by `pipeline_core.load_files_from_paths`: `time_s`, `phi`, `theta`, `dist`, `rssi`, `pps_pi`.

Required Pico columns are loaded by `pipeline_core.load_files_from_paths`: `time_s`, `count`, `roll_deg`, `pitch_deg`, `yaw_deg`, `pps`. The optional Pico column `imu_time_s` is used by `fusion_imu_interp.fuse_by_imu_interp` when available.

## Main Outputs

| Output | Location | Created by |
| --- | --- | --- |
| Per-target point-cloud CSVs | `OUTPUT_DIR/pointclouds/*.csv` | `pipeline_core.Plot.write` |
| Trait summary CSV | `OUTPUT_DIR/results.csv` | `central_runner.ensure_results_csv`, `central_runner.append_trait_rows` |
| Optional marker reference CSV | `OUTPUT_DIR/pointclouds/<scan>_marker_reference_points.csv` | `pipeline_core.write_marker_reference_points` |
| Optional topology object CSVs | `OUTPUT_DIR/pointclouds/*_topology_objects.csv` | `pipeline_core.analyze_plot` when configured |

Point-cloud CSVs contain `X`, `Y`, `Z`, and `RSSI`; additional scalar columns may be present after RSSI normalization or point-cloud operations.

## Pipeline Flow

```text
LiDAR CSV + Pico CSV + cart_config.yaml + experiment_config.yaml
  -> central_runner.run_experiment_date
  -> discover_scan_pairs
  -> read_calibration_from_cart_config
  -> build_config
  -> pipeline_stages.ProcessScanStage.run
  -> pipeline_core.process_scan
  -> load_files_from_paths
  -> choose_fusion_method
  -> reconstruct_world_points
  -> apply_global_filters
  -> apply_rssi_normalization_after_masks
  -> apply_rssi_filter
  -> distance or marker splitting
  -> analyze_plot
  -> write_scan_outputs
  -> results.csv and pointclouds/*.csv
```

Known limitation: the example fixture at `lidar_analysis/example_data/2026_04_28_1/` includes LiDAR, Pico, and marker CSVs, but does not include the required `cart_config.yaml` or `experiment_config.yaml`.
