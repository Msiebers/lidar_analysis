# Configuration Guide

The active config path is `lidar_analysis/central_runner.py::build_config`, which builds an `AnalysisConfig` from an experiment config dictionary. `lidar_analysis/central_runner.py::extract_analysis_cfg` uses the `analysis` mapping when present, so examples below use:

```yaml
analysis:
  key: value
```

Defaults are defined in `lidar_analysis/config.py::AnalysisConfig`. YAML aliases are handled in `central_runner.build_config`.

## Important Settings Table

| Config key | Default value | Type | Where defined | Where used | What it changes | Safe examples | Risky values / warnings |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `generate_pointclouds` | alias for `make_point_cloud=True` | bool | alias in `central_runner.build_config`; dataclass field `make_point_cloud` | `pipeline_core.write_scan_outputs`, `Plot.write` | Writes point-cloud CSVs | `true`, `false` | If `false`, CloudCompare outputs may not exist unless marker window writing is enabled. |
| `overwrite_pointclouds` | alias for `overwrite_outputs=True` | bool | alias in `central_runner.build_config`; dataclass field `overwrite_outputs` | `Plot.write` | Allows existing point-cloud CSVs to be overwritten | `true` for experiments | `false` can make output appear unchanged. |
| `fusion_method` | `interp` | string | `AnalysisConfig`; CLI `--fusion` can override | `pipeline_core.choose_fusion_method` | Chooses `interp`, `imu_interp`, or `pps` fusion | `interp`, `imu_interp`, `pps` | `pps` can return no matched rows if PPS evidence is insufficient. |
| `splitting_style` | absent; legacy fallback | string | `central_runner.resolve_splitting_style` | `build_config` -> `cfg.split_source`, `cfg.mark_target_type` | Canonical split mode | `distance`, `plant`, `plot` | Invalid values raise `ValueError`. |
| `split_source` | `distance` | string | `AnalysisConfig`; legacy fallback | `pipeline_core.process_scan` | Distance splitting vs marker splitting | `distance`, `marks` | Prefer `splitting_style` for new configs. |
| `buffer_u` | `0.0` through `resolve_buffer_u` | float | `central_runner.resolve_buffer_u` | marker buffer via `cfg.mark_z_buffer_u` | Marker window buffer in `dim_units` | `0.0`, `0.1` | Large values can erase marker windows when start/stop windows invert. |
| `mark_z_buffer_u` / `marker_z_buffer_u` | `0.0` | float | legacy aliases in `resolve_buffer_u` | marker buffer | Legacy marker buffer aliases | `0.0` | Prefer `buffer_u`. |
| `row_width_u` | `5.0` | float | `AnalysisConfig` | `central_runner.run_experiment_date`, `apply_global_filters` | Keeps points with `abs(X) <= row_width_u` converted to mm | `1.5`, `2.0`, `5.0` | Too small removes crop points; too large keeps neighboring rows. |
| `dim_units` | `m` | string | `AnalysisConfig` | `_to_m_units`, marker buffers, row width | Interprets `*_u` dimension settings | `m`, `ft` | Anything other than exact `m` is treated as feet by `_to_m_units`. |
| `start_u` | `0.0` | float or null | `AnalysisConfig` | `build_plot_ranges` | Start offset before first distance split | `0.0`, `0.5` | In `central_runner`, `None` is allowed; in legacy `run_experiment`, code assumes numeric. |
| `split_u` | `0.0` | float or null | `AnalysisConfig` | `build_plot_ranges` | Distance split length | `0.0`, `5.0` | `None` means one full range; `0.0` means no distance splitting. |
| `end_buffer_u` | `0.5` | float | `AnalysisConfig` | `build_plot_ranges` | Trims end of scan | `0.0`, `0.5` | Too large can make start >= end. |
| `x_min_u` | `None` | float or null | `AnalysisConfig` | `apply_global_filters` | Removes points near centerline by `abs(X) >= x_min_u` | `null`, `0.1` | Too high removes plants close to cart centerline. |
| `max_y_u` | `None` | float or null | `AnalysisConfig` | `apply_global_filters` | Removes points above maximum `Y` | `null`, `3.0` | Too low clips canopy height. |
| `min_radius_u` | `None` | float or null | `AnalysisConfig` | `reconstruct_world_points` | Removes LiDAR-frame points too close in sensor X/Z radius | `null`, `0.1` | Too high removes valid near returns. |
| `normalize_rssi` | `False` | bool | `AnalysisConfig` | `apply_rssi_normalization_after_masks` | Adds `rssi_norm` scalar after global masks | `true`, `false` | Keep raw `RSSI`; code preserves it. |
| `rssi_norm_mode` | `percentile` | string | `AnalysisConfig`; `normalize_rssi_mode` | `apply_rssi_normalization_after_masks` | Normalizes RSSI per phi | `percentile`, `zscore` | Other values raise `ValueError`. |
| `use_rssi_filter` | `False` | bool | `AnalysisConfig` | `apply_rssi_filter` | Enables raw RSSI min/max filtering | `true`, `false` | Filtering uses raw `RSSI`, not `rssi_norm`. |
| `rssi_min` | `None` | float or null | `AnalysisConfig` | `apply_rssi_filter` | Minimum raw RSSI | `null`, `10`, `50` | Too high can empty point clouds. |
| `rssi_max` | `None` | float or null | `AnalysisConfig` | `apply_rssi_filter` | Maximum raw RSSI | `null`, `10000` | Too low can empty point clouds. |
| `pointcloud_ops` | `None` in dataclass; `[]` from runner | list of dicts | `AnalysisConfig`, `central_runner.build_config` | `pipeline_core.analyze_plot`, `pointcloud_ops.apply_pointcloud_ops` | Ordered per-target filters/traits | See examples below | Unsupported op names raise `ValueError`. |
| `pcl_backend` | `None` | dict or null | `AnalysisConfig` | passed as context to pointcloud ops | Legacy/backend config | leave unset | PCL names are accepted by config but not implemented. |
| `run_height` | `False` | bool | `AnalysisConfig` | `analyze_plot`, `phenotype_columns` | Adds `height_m` trait | `true`, `false` | Height is 99th percentile of positive `Y`; filters affect it. |
| `run_lai` | `False` | bool | `AnalysisConfig` | `analyze_plot`, LAI modules | Adds LAI traits | `true`, `false` | Requires meaningful sky-facing beam distances. |
| `run_topology` | `False` | bool | deprecated shim in `AnalysisConfig` | legacy branch in `analyze_plot` | Old topology toggle | leave `false` | Active topology traits should use `pointcloud_ops: [{op: topology_trait}]`. |
| `write_lidar_per_plot` | `True` | bool | `AnalysisConfig` | present in config, not clearly used in active code path | Unclear from repository evidence | leave default | No active use was found in `pipeline_core.py`. |
| `use_imu` / `apply_imu` | `False` | bool | `AnalysisConfig`, alias in `build_config` | `reconstruct_world_points` | Applies roll/pitch correction | `true`, `false` | Requires reliable IMU calibration and signs. |
| `imu_zero_mode` | `dense_median` | string | `AnalysisConfig` | `reconstruct_world_points` | Roll/pitch zeroing method | `dense_median`, `calibration` | Other values raise `ValueError`. |
| `imu_zero_fraction` | `0.5` in dataclass | float | `AnalysisConfig` | `dense_median` | Dense window fraction for IMU zeroing | `0.5`, `0.6`, `1.0` | Must be in `(0, 1]`. |
| `use_heading` | `False` | bool | `AnalysisConfig` | `reconstruct_world_points` | Applies yaw correction | `false`, `true` | Can rotate cloud unexpectedly if yaw is noisy. |
| `roll_sign`, `pitch_sign`, `heading_sign` | `-1.0`, `-1.0`, `1.0` | float | `AnalysisConfig` | `reconstruct_world_points` | IMU sign conventions | default values | Changing signs changes geometry. |
| `marks.target_type` | none | string | legacy/canonical marker logic in `build_config` | `build_mark_segments` | Marker target mode | `plant`, `plot`, `auto` | Prefer `splitting_style` for new configs. |
| `marks.missing_file` / `missing_mark_file` | `error` | string | `build_config` | `process_scan` | Missing marker behavior | `error`, `skip`, `distance` | `distance` silently falls back to distance splitting. |
| `marks.write_pointcloud` / `write_marker_pointcloud` | `False` | bool | `build_config` | `write_scan_outputs` | Marker-related pointcloud writing | `true`, `false` | Old alias remains supported. |
| `marks.write_reference_points` | defaults to marker pointcloud value | bool | `build_config` | `process_scan`, `write_marker_reference_points` | Writes marker reference points CSV | `true`, `false` | Requires valid marker file. |
| `marks.write_window_pointcloud` | `False` | bool | `build_config` | `write_scan_outputs` | Writes marker windows when pointcloud generation is otherwise disabled | `true`, `false` | Only relevant for marker splits. |
| `markers_dirname` | `markers` | string | `AnalysisConfig` | `find_marker_file_for_scan` | Marker folder name | `markers` | Wrong folder name causes missing marker errors. |
| `free_marks_as` | `none` | string | `AnalysisConfig` | `build_mark_segments` | Converts free marks to plant marks in plant mode | `none`, `plant` | Only specific free mark roles are converted. |
| `empty_mark_file` | `skip` | string | `AnalysisConfig` | `process_scan` | Empty/unused marker behavior | `skip`, `error`, `distance` | `distance` changes splitting mode. |
| `additional_scan_side_split` | `False` | bool | `AnalysisConfig` | `process_scan`, `with_side_suffix` | Splits `scan_*` names into positive/negative X sides | `true`, `false` | Only applies when scan base starts with `scan_` and axis is `x`. |
| `additional_scan_side_axis` | `x` | string | `AnalysisConfig` | `process_scan` | Side split axis | `x` | Other axes do not activate current side split. |
| `additional_scan_positive_side_label` | `right` | string | `AnalysisConfig` | `with_side_suffix`, topology context | Positive X label | `right` | Label affects filenames and result rows. |
| `additional_scan_negative_side_label` | `left` | string | `AnalysisConfig` | `with_side_suffix`, topology context | Negative X label | `left` | Label affects filenames and result rows. |
| `rssi_norm_scope` | deprecated | any | `map_deprecated_analysis_keys` | removed before config build | Ignored | do not use | Emits warning and is ignored. |
| `write_o3d_ply`, `run_o3d_metrics` | `False` | bool | deprecated shims in `AnalysisConfig` | legacy placeholders in `pipeline_core` | Removed/disabled Open3D behavior | leave `false` | Active `Plot._write_ply` returns without writing. |

No config key named `run_mta` was found. FAD/LAI math exists in `lidar_analysis/lai/fad.py`, but the active config toggle is `run_lai`.

## Supported Point-Cloud Operations

`lidar_analysis/pointcloud_ops.py::_SUPPORTED_OPS` lists:

```text
scalar_range_filter
sor_filter
voxel_volume
voxel_grid
voxel_count
bilateral_scalar_filter
height_range_filter
topology_trait
slice_structure_trait
```

Ops run in the exact YAML order supplied to `pointcloud_ops`.

## Copy-Paste Config Examples

These examples show only the analysis block. A full experiment config may also include top-level keys like `experiment_name` and `processing_mode`, as shown in `lidar_analysis/scaffold_experiments.py::default_experiment_config`.

### Baseline Run

```yaml
analysis:
  fusion_method: interp
  dim_units: m
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  row_width_u: 5.0
  start_u: 0.0
  split_u: 0.0
  end_buffer_u: 0.5
  run_height: false
  run_lai: false
  normalize_rssi: false
  use_rssi_filter: false
  pointcloud_ops: []
```

### Point-Cloud Only Run

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  run_height: false
  run_lai: false
  pointcloud_ops: []
```

### RSSI Filtering Experiment

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  normalize_rssi: true
  rssi_norm_mode: percentile
  use_rssi_filter: true
  rssi_min: 50
  rssi_max: null
  pointcloud_ops: []
```

### Marker Splitting Experiment

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: plant
  buffer_u: 0.0
  markers_dirname: markers
  missing_mark_file: error
  empty_mark_file: skip
  write_marker_pointcloud: true
  write_reference_points: true
  pointcloud_ops: []
```

### Trait Extraction Run

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  run_height: true
  run_lai: true
  pointcloud_ops:
    - op: voxel_count
      voxel_size_m: 0.05
    - op: topology_trait
      min_persistence: 0.35
      z_bin_m: 0.05
```

### Conservative Filtering Run

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  row_width_u: 5.0
  max_y_u: null
  min_radius_u: null
  use_rssi_filter: false
  pointcloud_ops:
    - op: sor_filter
      mean_k: 12
      std_ratio: 2.0
```

### Aggressive Filtering Run

```yaml
analysis:
  fusion_method: interp
  generate_pointclouds: true
  overwrite_pointclouds: true
  splitting_style: distance
  row_width_u: 2.0
  max_y_u: 3.0
  min_radius_u: 0.10
  use_rssi_filter: true
  rssi_min: 100
  pointcloud_ops:
    - op: height_range_filter
      axis: Y
      min_m: 0.05
      max_m: 3.0
    - op: sor_filter
      mean_k: 12
      std_ratio: 1.0
    - op: voxel_count
      voxel_size_m: 0.025
```

## Safe Editing Workflow

1. Start with one known scan and one output folder.
2. Set `overwrite_pointclouds: true` while experimenting.
3. Change one config setting at a time.
4. Put each run in a different `--output` directory.
5. Compare `results.csv` columns such as `points`, `height_m`, `point_density_m2`, and `voxel_count`.
6. Compare point-cloud CSVs in CloudCompare.

