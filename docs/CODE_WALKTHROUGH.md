# Code Walkthrough

This document is a practical map of the repository based on source code. Source files are more authoritative than README text. Function and class names below are exact names from the repository.

## High-Level Call Graph

```text
lidar_analysis.central_runner.main
  -> parse_args
  -> normalize_request
  -> resolve_config_path
  -> _load_yaml
  -> extract_analysis_cfg
  -> run_experiment_date
       -> discover_scan_pairs
       -> read_calibration_from_cart_config
       -> build_config
       -> ensure_results_csv
       -> DEFAULT_STAGES
            -> ProcessScanStage.run
                 -> lidar_analysis.pipeline_core.process_scan
                      -> load_files_from_paths
                      -> choose_fusion_method
                           -> fuse_by_time OR fuse_by_imu_interp OR fuse_by_pps
                      -> compute_beam_diagnostics
                      -> reconstruct_world_points
                      -> apply_global_filters
                      -> apply_rssi_normalization_after_masks
                      -> apply_rssi_filter
                      -> build_plot_ranges OR build_mark_segments
                      -> build_plot_objects OR build_plot_objects_from_mark_segments
                      -> analyze_plot
                           -> AnalysisTarget.from_points
                           -> apply_pointcloud_ops
                           -> compute_lai_trait_from_beam_rows
                           -> height_from_world_y
                      -> write_scan_outputs
       -> append_trait_rows
```

## `lidar_analysis/config.py`

Purpose: central configuration dataclass and config helper functions.

Main symbols:

- `AnalysisConfig`: dataclass defining pipeline options and defaults.
- `default_analysis_yaml_dict`: creates default YAML-style analysis settings from `AnalysisConfig`.
- `normalize_rssi_mode`: accepts only `zscore` or `percentile`.
- `map_deprecated_analysis_keys`: currently removes deprecated `rssi_norm_scope`.

Inputs: Python dictionaries and mode strings.

Outputs: `AnalysisConfig` defaults, normalized strings, mapped dictionaries.

Side effects: `map_deprecated_analysis_keys` emits a warning when `rssi_norm_scope` is present.

Called by: `lidar_analysis/central_runner.py::build_config`, `lidar_analysis/scaffold_experiments.py::default_experiment_config`, tests in `tests/test_config_defaults.py`.

Careful editing: do not remove existing config keys. `default_analysis_yaml_dict` is used as a source of scaffold defaults.

## `lidar_analysis/central_runner.py`

Purpose: active local runner for one experiment/date.

Main symbols:

- `NormalizedRunRequest`
- `parse_args`
- `resolve_config_path`
- `normalize_request`
- `discover_scan_pairs`
- `read_calibration_from_cart_config`
- `resolve_splitting_style`
- `resolve_buffer_u`
- `build_config`
- `phenotype_columns`
- `ensure_results_csv`
- `append_trait_rows`
- `extract_analysis_cfg`
- `run_experiment_date`
- `main`

Inputs: CLI args, experiment config YAML, `cart_config.yaml`, LiDAR/Pico CSV files.

Outputs: `OUTPUT_DIR/results.csv`, `OUTPUT_DIR/pointclouds/*.csv`.

Side effects: creates output directories, writes CSVs, prints progress.

What calls it: command line via `python3 -m lidar_analysis.central_runner`; wrapper `lidar_analysis/run_experiment_date.py`; orchestrator `lidar_analysis/orchestrator.py`.

What it calls: `pipeline_stages.DEFAULT_STAGES`, `pipeline_core._to_m_units`, `pipeline_core.process_scan` through `ProcessScanStage`.

Careful editing:

- `discover_scan_pairs` only searches the top level of `input_dir`.
- `build_config` accepts both canonical and legacy config aliases.
- `read_calibration_from_cart_config` supplies numeric defaults for missing nested values; this can make a config syntactically valid but scientifically wrong if calibration values are absent.

## `lidar_analysis/run_experiment_date.py`

Purpose: compatibility wrapper around `central_runner`.

Main symbols:

- `parse_args`
- `resolve_config_path`
- `call_runner`
- `main`

Inputs: same command-line shape as `central_runner`.

Outputs: whatever `central_runner.run_experiment_date` writes.

Side effects: creates working/output directories; may call a subprocess fallback if `central_runner.run_experiment_date` is not available.

What calls it: `central_watcher.py::run_processing`.

Careful editing: keep CLI compatibility because watcher uses this file as `PROCESS_SCRIPT`.

## `lidar_analysis/orchestrator.py`

Purpose: higher-level manifest-based workflow for staging, running, packaging, and optionally publishing date outputs.

Main symbols:

- `PipelinePaths`
- `DEFAULT_PATHS`
- `append_log`
- `ensure_workspace_dirs`
- `reset_dir`
- `classify_output_file`
- `build_output_package`
- `validate_output_package`
- `rebuild_all_results_csv`
- `ensure_local_experiment_config`
- `sync_raw_date`
- `publish_output_package`
- `experiment_mode`
- `raw_date_ready`
- `process_one_date`
- `poll_once`

Inputs: raw data root, experiments root, workspace root, experiment/date names.

Outputs: run workspace, package directories, manifests, optional published outputs under experiments root.

Side effects: copies directories, removes/recreates package/current output directories, writes logs and manifests.

What calls it: `lidar_analysis/local_run.py`.

What it calls: `central_runner.run_experiment_date`, `run_manifest` functions, `scaffold_experiments.ensure_experiment_scaffold`.

Careful editing: `reset_dir` and publishing logic delete and recreate target output directories. Confirm paths before use.

## `lidar_analysis/central_watcher.py`

Purpose: simpler sync/rerun workflow for mounted CartCity data.

Main symbols:

- `poll_once`
- `sync_date_only`
- `sync_dir_contents`
- `stamp_default_config`
- `run_processing`
- `process_date_root`
- `rerun_date`
- `parse_args`
- `main`

Inputs: `/mnt/cartcity/raw_data`, config templates, mirrored local source folders.

Outputs: `/media/central/raw_mirror/<experiment>/<date>/source`, point clouds, `results.csv`, and `scan_metadata`.

Side effects: calls `rsync --delete`, runs `run_experiment_date.py` as a subprocess, writes logs/state/snapshots.

What calls it: command line.

Careful editing: `poll` intentionally does not process data. Processing happens through `rerun`.

## `lidar_analysis/pipeline_core.py`

Purpose: core scientific processing: load files, fuse streams, reconstruct point clouds, filter, split, calculate traits, and write outputs.

Main symbols:

- `load_calibration`
- `lai`
- `height_from_world_y`
- `parse_scan_name`
- `load_csv`
- `load_files_from_paths`
- `Plot`
- `normalize_rssi_by_phi_zscore`
- `normalize_rssi_by_phi_percentile`
- `choose_fusion_method`
- `dense_median`
- `reconstruct_world_points`
- `apply_global_filters`
- `build_plot_ranges`
- `build_plot_objects`
- `build_plot_objects_from_mark_segments`
- `write_scan_outputs`
- `write_marker_reference_points`
- `with_side_suffix`
- `analyze_plot`
- `apply_rssi_normalization_after_masks`
- `apply_rssi_filter`
- `process_scan`
- `run_for_directory`
- `run_experiment`

Inputs: LiDAR/Pico CSV paths, `AnalysisConfig`, calibration numbers, split parameters.

Outputs: plot point-cloud CSVs, trait record dictionaries, optional marker reference CSVs.

Side effects: writes point-cloud CSVs; prints many debug/progress lines.

What calls it: `pipeline_stages.ProcessScanStage.run`, legacy `pipeline_core.run_for_directory`, tests.

What it calls: fusion modules, marker splitting, pointcloud ops, LAI functions, beam diagnostics.

Careful editing:

- `reconstruct_world_points` implements the project coordinate convention.
- `Plot.write` converts `X`, `Y`, `Z` from millimeters to meters before writing.
- `run_experiment` appears stale: it references undefined variable `d` when calling `run_for_directory`.
- `load_calibration` uses `sys.exit(1)` on errors, while the active central runner uses `read_calibration_from_cart_config`.

## Fusion Modules

### `lidar_analysis/fusion.py`

Purpose: simple timestamp interpolation.

Main symbols:

- `_unwrap_deg`
- `_lin_interp`
- `fuse_by_time`

Inputs: LiDAR and Pico NumPy arrays.

Outputs: fused NumPy array with 9 columns:

```text
time_s, phi, theta, dist_mm, rssi, encoder, roll_deg, pitch_deg, yaw_deg
```

Careful editing: `trim_to_overlap=False` in `pipeline_core.choose_fusion_method` allows endpoint clamping through `np.interp`.

### `lidar_analysis/fusion_imu_interp.py`

Purpose: direct IMU timestamp interpolation.

Main symbols:

- `_choose_imu_timestamp`
- `_sorted_imu_source`
- `_sorted_encoder_source`
- `_interp_columns`
- `fuse_by_imu_interp`

Inputs: LiDAR/Pico arrays, optional Pico `imu_time_s` column.

Outputs: same 9-column fused array shape.

Careful editing: `trim_to_overlap=False` can clamp endpoints and warn once.

### `lidar_analysis/fusion_pps.py`

Purpose: strict PPS-locked fusion.

Main symbols:

- `_linear_fit_edges`
- `_phase_time`
- `_build_value_stream`
- `_choose_imu_timestamp`
- `fuse_by_pps`

Inputs: LiDAR/Pico arrays with PPS columns.

Outputs: same 9-column fused array shape or an empty array if PPS alignment is insufficient.

Careful editing: PPS fusion intentionally returns empty for sparse or non-overlapping data rather than silently accepting poor alignment.

## `lidar_analysis/mark_splitting.py`

Purpose: marker-file discovery and conversion of marker rows into Z intervals.

Main symbols:

- `MarkSegment`
- `marker_buffer_mm`
- `marker_count_to_z_mm`
- `find_marker_file_for_scan`
- `build_mark_segments`

Inputs: marker CSV, encoder calibration, LiDAR wheel offset, marker target type.

Outputs: list of `MarkSegment` objects.

What calls it: `pipeline_core.process_scan`.

Careful editing:

- Marker filenames are matched by scan base and `marker`/`markers` patterns.
- Ambiguous multiple marker files raise `ValueError`.
- Plant center marks use symmetric windows around the marker based on `z_buffer_mm`.

## `lidar_analysis/pointcloud_ops.py`

Purpose: ordered per-target point-cloud operations.

Main symbols:

- `_BackendResolver`
- `op_enabled`
- `apply_pointcloud_ops`
- `_scalar_range_filter`
- `_sor_filter`
- `_height_range_filter`
- `_topology_trait`
- `_voxel_count`
- `_bilateral_scalar_filter`
- `_compute_slice_structure_traits`

Inputs: `AnalysisTarget` and `pointcloud_ops` config list.

Outputs: updated `AnalysisTarget.current_points`, `target.traits`, and diagnostics.

Side effects: mutates `AnalysisTarget.current_points`; preserves `AnalysisTarget.raw_points` by convention.

What calls it: `pipeline_core.analyze_plot`.

Careful editing:

- Only the SciPy backend is implemented. `_BackendResolver.resolve` raises for `pcl`, `pclpy`, and `python_pcl`.
- Ops run in exact YAML order.
- Coordinates in `current_points` are millimeters while op config sizes are generally meters.

## LAI / FAD / Topology Modules

### `lidar_analysis/lai/fad.py`

Purpose: legacy gap-fraction and LAI math.

Main symbols:

- `EVEN_ZENITH_BREAKS_RAD`
- `UNEVEN_ZENITH_BREAKS_RAD`
- `LaiResult`
- `compute_gap_fraction_by_zenith`
- `legacy_lai_from_gap_fraction`
- `legacy_lai`

### `lidar_analysis/lai/lai.py`

Purpose: wrappers that flatten LAI results into pipeline trait dictionaries.

Main symbols:

- `compute_legacy_lai_pair`
- `compute_lai_trait_from_lidar_data`
- `compute_lai_trait_from_beam_rows`
- `compute_lai_trait_from_target`

Called by: `pipeline_core.analyze_plot`.

Careful editing: LAI uses sky-facing raw emitted beams, not only endpoint-selected current points, when `fused_np` plot indices are available.

### `lidar_analysis/topology/stand_count.py`

Purpose: legacy topology stand count from an X/Z density image.

Main symbols:

- `topology_stand_count`

Called by: `pointcloud_ops._topology_trait`.

Careful editing: input is expected in meters with columns or array order `x, y, z`.

### `lidar_analysis/topology/imagepers.py` and `union_find.py`

Purpose: persistent homology support code used by `topology_stand_count`.

## Test Files

Tests live under `tests/`.

Important files:

- `tests/test_config_defaults.py`: config defaults and RSSI mode validation.
- `tests/test_fusion_imu_interp_smoke.py`: script-style smoke test for IMU interpolation behavior.
- `tests/test_pointcloud_ops_smoke.py`: pytest tests for pointcloud ops and topology trait behavior.
- `tests/test_splitting_style_smoke.py` and `tests/test_mark_splitting_smoke.py`: duplicate script-style checks for splitting style aliases.
- `tests/test_marker_reference_points_smoke.py`: script-style marker reference CSV check.
- `tests/test_additional_scan_side_split.py`: script-style side split check, currently stale relative to the current `analyze_plot` signature.
- `tests/test_run_experiment_date_wrapper.py`: verifies wrapper references `central_runner`.

Careful editing: not every `test_*.py` file contains pytest-collected `test_...` functions. Some only run when invoked as scripts.

## Scripts

### `scripts/convert_pico_folder_rename_reorder.py`

Purpose: convert older Pico CSV schema to current schema.

Main function: `convert_file`.

Inputs: folder containing `*_pico.csv`.

Outputs: overwrites converted Pico CSV files in place.

Careful editing: this script modifies input files.

### `scripts/plot_pcl_summary.py`

Purpose: create plots and outlier CSVs for a summary CSV.

Main functions:

- `clean_numeric`
- `outlier_limits`
- `plot_hist_with_box`
- `plot_boxplot`
- `write_outlier_csv`
- `main`

Inputs: a summary CSV with columns such as `pcl_voxel_count` and `height_extent_m` or `height_y_max_m`.

Outputs:

```text
height_hist_box.png
voxel_hist_box.png
height_boxplot.png
voxel_boxplot.png
height_outliers.csv
voxel_outliers.csv
```

Careful editing: this script requires `matplotlib`, which was not installed in the observed environment.

