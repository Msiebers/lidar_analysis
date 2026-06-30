# Testing And Validation

The repository includes tests under `tests/`, but does not include a dependency manifest such as `requirements.txt`, `pyproject.toml`, or `environment.yml`.

## Dependencies

Imports in the code and tests indicate these Python packages are required:

```text
numpy
pandas
scipy
PyYAML
pytest
matplotlib   # only for scripts/plot_pcl_summary.py
```

Install commands are environment-specific. This inferred command matches the observed imports:

```bash
python3 -m pip install numpy pandas scipy PyYAML pytest matplotlib
```

## Existing Tests

Test files:

```text
tests/test_additional_scan_side_split.py
tests/test_config_defaults.py
tests/test_fusion_imu_interp_smoke.py
tests/test_mark_splitting_smoke.py
tests/test_marker_reference_points_smoke.py
tests/test_pointcloud_ops_smoke.py
tests/test_run_experiment_date_wrapper.py
tests/test_splitting_style_smoke.py
```

Recommended test command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

Observed limitation in the local environment: test collection fails when PyYAML is missing because `central_runner.py` and `pipeline_core.py` import `yaml`.

## Syntax Check

Use this when bytecode artifacts are acceptable:

```bash
python3 -m py_compile lidar_analysis/*.py
```

For a no-bytecode syntax check, compile files in memory with Python. This was previously observed to compile 38 Python files successfully.

## Smoke Testing Strategy

1. Start with one scan pair and one output directory.
2. Use `fusion_method: interp` first because it is the default in `AnalysisConfig`.
3. Set `generate_pointclouds: true` and `overwrite_pointclouds: true`.
4. Run with one config change at a time.
5. Compare `OUTPUT_DIR/results.csv`, `OUTPUT_DIR/pointclouds/*.csv`, and CloudCompare screenshots.

Do not claim an end-to-end example-data run succeeds until `lidar_analysis/example_data/2026_04_28_1/cart_config.yaml` is provided and an experiment config is available either through `--config` or at one of the supported default paths.

## Controlled Experiment Protocol

Use a unique output folder for every config variant:

```text
runs/
  001_baseline/output/
  002_fusion_imu_interp/output/
  003_row_width_2m/output/
```

Record:

| Item | Example |
| --- | --- |
| Run ID | `003_row_width_2m` |
| Command | `python3 -m lidar_analysis.central_runner ...` |
| Config file | `configs/003_row_width_2m.yaml` |
| Output folder | `runs/003_row_width_2m/output` |
| Result columns inspected | `points`, `height_m`, `voxel_count` |
| CloudCompare checks | shape, density, height, removed points |

When a data folder already has `cart_config.yaml` but no `experiment_config.yaml`, keep experiment variants outside the data folder and pass the desired file with `--config`. This avoids changing raw project data while making each test run reproducible.

## Testing Matrix

| Run ID | Config changed | Expected effect | Inspect in CSV | Inspect in CloudCompare |
| --- | --- | --- | --- | --- |
| `001_baseline` | Default `interp`, no ops | Reference output | `points`, `plot_length_m`, `plot_width_m` | Overall row shape |
| `002_fusion_imu_interp` | `fusion_method: imu_interp` | Uses IMU timestamp interpolation | Point count and geometry changes | Tilt/rotation vs baseline |
| `003_fusion_pps` | `fusion_method: pps` | Stricter PPS alignment; may return no rows | Presence of result rows | Missing or smaller cloud |
| `004_row_width_2m` | `row_width_u: 2.0` | Removes lateral points outside width | Lower `points` | Narrower `X` spread |
| `005_height_filter` | `max_y_u: 2.0` | Clips tall points | Lower `height_m` if enabled | Missing canopy top |
| `006_rssi_off` | `use_rssi_filter: false` | Keeps all raw RSSI values | Baseline `points` | Full cloud |
| `007_rssi_low` | `use_rssi_filter: true`, low `rssi_min` | Mild low-RSSI removal | Slightly lower `points` | Low-scalar points removed |
| `008_rssi_high` | high `rssi_min` | Aggressive low-RSSI removal | Much lower `points` | Sparse or empty cloud |
| `009_marker_split` | `splitting_style: plant` or `plot` | Marker-defined target windows | `plot`, `points` | Separate target clouds |
| `010_distance_split` | `splitting_style: distance`, `split_u` set | Fixed travel windows | Number of result rows | Regular `Z` intervals |
| `011_ops_off` | `pointcloud_ops: []` | Raw post-global-filter target clouds | No op-derived traits | More isolated points |
| `012_ops_on` | `sor_filter`, `voxel_count` | Outlier removal and voxel trait | `voxel_count`, `points` | Cleaner cloud |
| `013_traits_off` | `run_height: false`, `run_lai: false` | Fewer trait columns | No height/LAI columns | Geometry only |
| `014_traits_on` | `run_height: true`, `run_lai: true` | Adds height and LAI traits | `height_m`, `lai_even`, `lai_uneven` | Height vs visible cloud |
