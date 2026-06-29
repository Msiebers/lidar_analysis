# Configuration

The active configuration model is `lidar_analysis/config.py::AnalysisConfig`. `lidar_analysis/central_runner.py::build_config` converts experiment YAML into that dataclass and supports several compatibility aliases.

Experiment YAML may place settings at the top level or under `analysis`; `central_runner.extract_analysis_cfg` prefers the `analysis` mapping when it is present.

## Baseline Config

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
  normalize_rssi: false
  use_rssi_filter: false
  run_height: false
  run_lai: false
  pointcloud_ops: []
```

## Key Settings

### Output Generation

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `generate_pointclouds` | `true` via `make_point_cloud` | `central_runner.build_config`, `pipeline_core.Plot.write` | Writes `pointclouds/*.csv` |
| `overwrite_pointclouds` | `true` via `overwrite_outputs` | `pipeline_core.Plot.write` | Rewrites existing CSV outputs |
| `write_marker_pointcloud` / `marks.write_pointcloud` | `false` | `central_runner.build_config`, `pipeline_core.write_scan_outputs` | Enables marker-related point-cloud output |
| `write_reference_points` / `marks.write_reference_points` | defaults to marker point-cloud setting | `pipeline_core.process_scan` | Writes marker reference points |
| `write_window_pointcloud` / `marks.write_window_pointcloud` | `false` | `pipeline_core.write_scan_outputs` | Writes marker window point clouds when applicable |

### Fusion

| Key | Default | Used by | Valid values |
| --- | --- | --- | --- |
| `fusion_method` | `interp` | `pipeline_core.choose_fusion_method` | `interp`, `imu_interp`, `pps` |
| `use_imu` / `apply_imu` | `false` | `pipeline_core.reconstruct_world_points` | Boolean |
| `imu_zero_mode` | `dense_median` | `pipeline_core.reconstruct_world_points` | `dense_median`, `calibration` |
| `imu_zero_fraction` | `0.5` | `pipeline_core.dense_median` | Float in `(0, 1]` |
| `use_heading` | `false` | `pipeline_core.reconstruct_world_points` | Boolean |
| `roll_sign`, `pitch_sign`, `heading_sign` | `-1.0`, `-1.0`, `1.0` | `pipeline_core.reconstruct_world_points` | Numeric sign multipliers |

### Spatial Filtering

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `dim_units` | `m` | `pipeline_core._to_m_units`, marker buffer conversion | Interprets `*_u` fields as meters or feet |
| `row_width_u` | `5.0` | `pipeline_core.apply_global_filters` | Keeps points within row width in `X` |
| `x_min_u` | `null` | `pipeline_core.apply_global_filters` | Removes points too close to row centerline |
| `max_y_u` | `null` | `pipeline_core.apply_global_filters` | Removes points above max height |
| `min_radius_u` | `null` | `pipeline_core.reconstruct_world_points` | Removes LiDAR-frame points too close to the sensor |
| `start_u`, `split_u`, `end_buffer_u` | `0.0`, `0.0`, `0.5` | `pipeline_core.build_plot_ranges` | Controls distance-based target windows |

### RSSI

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `normalize_rssi` | `false` | `pipeline_core.apply_rssi_normalization_after_masks` | Adds normalized RSSI scalar data |
| `rssi_norm_mode` | `percentile` | `config.normalize_rssi_mode` | `percentile` or `zscore` |
| `use_rssi_filter` | `false` | `pipeline_core.apply_rssi_filter` | Enables raw RSSI min/max filtering |
| `rssi_min`, `rssi_max` | `null`, `null` | `pipeline_core.apply_rssi_filter` | Removes points outside raw RSSI bounds |

`rssi_norm_scope` is deprecated and ignored by `config.map_deprecated_analysis_keys`.

### Splitting And Markers

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `splitting_style` | legacy fallback | `central_runner.resolve_splitting_style` | `distance`, `plant`, or `plot` |
| `buffer_u` | `0.0` | `central_runner.resolve_buffer_u`, `mark_splitting.marker_buffer_mm` | Marker buffer in `dim_units` |
| `markers_dirname` | `markers` | `mark_splitting.find_marker_file_for_scan` | Marker folder name |
| `marks.missing_file` / `missing_mark_file` | `error` | `pipeline_core.process_scan` | `error`, `skip`, or `distance` |
| `marks.empty_file` / `empty_mark_file` | `skip` | `pipeline_core.process_scan` | Behavior when marker file has no usable segments |
| `marks.target_type`, `mark_target_type`, `marker_target_type` | `auto` | `mark_splitting.build_mark_segments` | `auto`, `plant`, or `plot` |
| `free_marks_as` | `none` | `mark_splitting.build_mark_segments` | Converts free marks in supported modes |

Legacy aliases accepted by `central_runner.resolve_buffer_u`: `marks.buffer_u`, `mark_z_buffer_u`, and `marker_z_buffer_u`. Use `buffer_u` for new configs.

### Point-Cloud Operations And Traits

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `pointcloud_ops` | `[]` | `pointcloud_ops.apply_pointcloud_ops` | Ordered per-target operations |
| `pcl_backend` | `null` | `pointcloud_ops._BackendResolver` | PCL names are accepted but not implemented |
| `run_height` | `false` | `pipeline_core.analyze_plot`, `central_runner.phenotype_columns` | Adds `height_m` |
| `run_lai` | `false` | `pipeline_core.analyze_plot`, `lidar_analysis/lai/` | Adds `lai_even`, `lai_uneven` |
| `run_topology` | `false` compatibility shim | legacy branch in `pipeline_core.analyze_plot` | Prefer `pointcloud_ops: [{op: topology_trait}]` |

Supported operation names are defined by `pointcloud_ops._SUPPORTED_OPS`:

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

No active config keys named `run_mta` or `run_fad` were found. FAD/LAI math exists in `lidar_analysis/lai/fad.py`; the active trait toggle is `run_lai`.

## Short Experiment Configs

### RSSI Filtering

```yaml
analysis:
  generate_pointclouds: true
  overwrite_pointclouds: true
  use_rssi_filter: true
  rssi_min: 50
  rssi_max: null
```

### Marker-Based Plant Windows

```yaml
analysis:
  splitting_style: plant
  buffer_u: 0.1
  markers_dirname: markers
  missing_mark_file: error
  empty_mark_file: skip
  write_reference_points: true
```

### Trait Extraction

```yaml
analysis:
  run_height: true
  run_lai: true
  pointcloud_ops:
    - op: voxel_count
      voxel_size_m: 0.05
    - op: topology_trait
      min_persistence: 0.35
      z_bin_m: 0.05
```

### Conservative Filtering

```yaml
analysis:
  row_width_u: 5.0
  use_rssi_filter: false
  pointcloud_ops:
    - op: sor_filter
      mean_k: 12
      std_ratio: 2.0
```

### Aggressive Filtering

```yaml
analysis:
  row_width_u: 2.0
  max_y_u: 3.0
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
```
