# Configuration

The active configuration model is `lidar_analysis/config.py::AnalysisConfig`. `lidar_analysis/central_runner.py::build_config` converts experiment YAML into that dataclass and supports several compatibility aliases.

Whole-scan multiprocessing is off by default:

```yaml
processing:
  parallel_scans: null  # set 2 or 4 to enable
```

Only independent scans run concurrently. Aggregate result and completion files are written by the parent process.

Experiment YAML may place settings at the top level or under `analysis`; `central_runner.extract_analysis_cfg` prefers the `analysis` mapping when it is present.

For scan name parsing, two-sided `&` names, and side conventions, see [Scan Naming](SCAN_NAMING.md).

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

The current cart IMU is a BNO085. Pico CSV Euler fields are read as degrees in
the explicit order `roll_deg,pitch_deg,yaw_deg`. In pipeline coordinates, the
`ZXY` rotation applies roll about travel Z, pitch about lateral X, and heading
about vertical Y. Sign values remain mounting-specific and must be checked
against a physical ground plane; BNO055 sign conventions are not interchangeable.

### Spatial Filtering

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `dim_units` | `m` | `pipeline_core._to_m_units`, marker buffer conversion | Interprets `*_u` fields as meters or feet |
| `row_width_u` | `5.0` | `pipeline_core.apply_global_filters` | Keeps points within row width in `X` |
| `x_min_u` | `null` | `pipeline_core.apply_global_filters` | Removes points too close to row centerline |
| `max_y_u` | `null` | `pipeline_core.apply_global_filters` | Removes points above max height |
| `min_radius_u` | `null` | `pipeline_core.reconstruct_world_points` | Removes LiDAR-frame points too close to the sensor |
| `fad_x_near_m` | `0.0` | `pipeline_core._fad_x_bounds_for_plot` | Sets the near X face of each side-specific FAD box from the LiDAR centerline; does not filter point-cloud operations |
| `pai_x_near_m` | `0.0` | `pipeline_core._fad_x_bounds_for_plot` | Independently sets the near X face of the bounded PAI volume |
| `start_u`, `split_u`, `end_buffer_u` | `0.0`, `0.0`, `0.5` | `pipeline_core.build_plot_ranges` | Controls distance-based target windows |

`use_local_ground_filter` estimates a snapped X-Z ground grid and filters
on `min_height_agl_m`. `local_ground_x_bin_m` and `local_ground_z_bin_m` control
the lateral and travel-direction cell sizes independently; `local_ground_quantile`
and `local_ground_min_points_per_xz_bin` control the candidate in each cell.
Avoid a separate global-Y lower threshold, which can recreate
side-dependent retention.

### RSSI

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `normalize_rssi` | `false` | `pipeline_core.apply_rssi_normalization_after_masks` | Adds normalized RSSI scalar data |
| `rssi_norm_mode` | `percentile` | `config.normalize_rssi_mode` | `percentile` or `zscore` |
| `rssi_norm_transform` | `sqrt` | `pipeline_core.transform_rssi_norm` | `none`, `sqrt`, `log`/`log1p`, or `exp`/`exponential`; `sqrt` preserves legacy z-score output |
| `use_rssi_filter` | `false` | `pipeline_core.apply_rssi_filter` | Enables raw RSSI min/max filtering |
| `rssi_min`, `rssi_max` | `null`, `null` | `pipeline_core.apply_rssi_filter` | Removes points outside raw RSSI bounds |

`rssi_norm_scope` is deprecated and ignored by `config.map_deprecated_analysis_keys`.

### Splitting And Marks

Target = biological target from the scan filename. Window = distance- or mark-defined segment along the scan. Marks = files used to define windows.

Use one user-facing workflow in new configs:

```yaml
analysis:
  split_source: distance  # options: distance, marks
  marks:
    target_type: auto  # options: auto, plant, plot
    buffer_u: 0.0
    missing_file: error  # options: error, skip, distance
    empty_file: skip  # options: skip, error, distance
    free_marks_as: none  # options: none, plant, plot
    dirname: markers
```

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `split_source` | `distance` | `central_runner.resolve_splitting_style`, `pipeline_core.process_scan` | `distance` uses fixed windows; `marks` uses mark-defined windows |
| `marks.target_type` | `auto` | `mark_splitting.build_mark_segments` | Selects mark rows: `auto`, `plant`, or `plot` |
| `marks.buffer_u` | `0.0` | `central_runner.resolve_buffer_u`, `mark_splitting.marker_buffer_mm` | Mark window buffer in `dim_units` |
| `marks.dirname` | `markers` | `mark_splitting.find_marker_file_for_scan` | Legacy markers directory name |
| `marks.missing_file` | `error` | `pipeline_core.process_scan` | `error`, `skip`, or `distance` |
| `marks.empty_file` | `skip` | `pipeline_core.process_scan` | `skip`, `error`, or `distance` |
| `marks.free_marks_as` | `none` | `mark_splitting.build_mark_segments` | `none`, `plant`, or `plot` |

Older configs may still use compatibility aliases such as `splitting_style`, top-level `buffer_u`, `mark_z_buffer_u`, `marker_z_buffer_u`, `missing_mark_file`, `empty_mark_file`, `free_marks_as`, or `markers_dirname`. Do not copy those aliases into new templates.

### Point-Cloud Operations And Traits

| Key | Default | Used by | Effect |
| --- | --- | --- | --- |
| `pointcloud_ops` | all template entries disabled | `pointcloud_ops.apply_pointcloud_ops` | Ordered per-window operations for SOR, bilateral filtering, scalar filtering, height/range filtering, voxel counting, and topology traits |
| `pcl_backend` | `null` | `pointcloud_ops._resolve_backend` | Only `scipy` is implemented; PCL backend names are rejected |
| `run_height` | `false` | `pipeline_core.analyze_plot`, `central_runner.phenotype_columns` | Adds `height_m` |
| `run_lai` | `false` | `pipeline_core.analyze_plot`, `lidar_analysis/lai/` | Adds `lai_even`, `lai_uneven` |
| `run_mta` | `false` | `pipeline_core.analyze_plot`, `lidar_analysis/mta.py` | Adds the plot-bounded `bounded_lang_v1` MTA |
| `mta_angle_bin_deg` | `5.0` | `lidar_analysis/mta.py` | Angular-bin width; standard fitting bins remain anchored to the complete 25–65 degree interval |
| `mta_diagnostic` | `false` | `central_runner.run_experiment_date` | When true, writes the single aggregate `mta_diagnostics.csv`; never changes the main result schema |
| `run_pai` | `false` | `pipeline_core.analyze_plot`, `lidar_analysis/pai.py` | Integrates bounded layer PAI increments into the publication value `pai_m2_m2` |
| `pai_layer_thickness_m` | `0.10` | `lidar_analysis/pai.py` | Nominal vertical layer thickness in metres |
| `pai_include_layer_columns` | `false` | `central_runner.run_experiment_date` | Adds optional wide `pai_layer_*` columns to `results.csv` |
| `pai_diagnostic` | `false` | `central_runner.run_experiment_date` | Writes `pai_diagnostics.csv` with layer PAD, ray/path, likelihood, and whole-box audit values |
| `run_topology` | `false` compatibility shim | legacy branch in `pipeline_core.analyze_plot` | Prefer `pointcloud_ops: [{op: topology_trait}]` |

`pointcloud_ops` entries run in YAML order. Entries with `enabled: false` are skipped before dispatch. Put `voxel_count` after filters that should affect the count. The full config template lists user-facing operations with disabled defaults; voxel aliases remain supported in code for old configs.

MTA uses actual ray path through the same finite, side-aware `Box3D` as FAD,
then separates plant-area density from orientation before applying the Lang
polynomial. See [Plot-Bounded MTA](PLOT_BOUNDED_MTA.md) for equations, config,
output/QC fields, and scientific limitations.

PAI is a bounded layer transmission estimator. In each layer, a source ray is
classified from its raw first return as not reaching the layer, hitting within
it, or traversing it as a gap. The layer PAD is multiplied by the actual layer
thickness, and `pai_m2_m2` is the sum of those layer PAI increments. Whole-box
PAI and PAD remain audit values only. Existing `pai_run_*profile` keys remain
readable for compatibility but are not primary controls in generated configs.

Supported operation names are defined by `pointcloud_ops._SUPPORTED_OPS`:

```text
scalar_range_filter
sor_filter
voxel_count
voxel_grid  # legacy alias of voxel_count
voxel_volume  # legacy alias of voxel_count
bilateral_scalar_filter
height_range_filter
topology_trait
slice_structure_trait
canopy_volume_2p5d
```

`canopy_volume_2p5d` grids the X-Z footprint, takes a configurable height
percentile in each occupied cell, and sums height times cell area. It uses
`height_agl` when available and otherwise Y. The operation does not mutate the
point cloud. Raw volume, footprint-area-normalized volume, occupied/total cell
counts, observed area, and coverage fraction are written to `results.csv`.


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

### Mark-Based Plant Windows

```yaml
analysis:
  split_source: marks
  marks:
    target_type: plant
    buffer_u: 0.1
    dirname: markers
    missing_file: error
    empty_file: skip
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
