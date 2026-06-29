# How To Run The Analysis Locally

This guide documents the active runner in `lidar_analysis/central_runner.py`. Commands are verified from `lidar_analysis/central_runner.py::parse_args` and `lidar_analysis/run_experiment_date.py::parse_args`. Do not treat `lidar_analysis/example_data/2026_04_28_1` as directly runnable without adding missing config files.

## Required Folder Structure

The active runner expects a single input directory containing one date of data:

```text
INPUT_DIR/
  cart_config.yaml
  experiment_config.yaml        # optional if --config is supplied
  *_lidar.csv
  *_pico.csv
  markers/
    *_marker*.csv               # optional, required only for marker splitting
```

Matching LiDAR/Pico scan pairs are discovered by `lidar_analysis/central_runner.py::discover_scan_pairs`. It looks only for files in `INPUT_DIR` whose names end with:

```text
_lidar.csv
_pico.csv
```

For a pair to run, the same scan base must exist for both files. Example:

```text
2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026_lidar.csv
2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026_pico.csv
```

## Required Input Files

### LiDAR CSV

Read by `lidar_analysis/pipeline_core.py::load_files_from_paths`.

Required columns:

```text
time_s, phi, theta, dist, rssi, pps_pi
```

### Pico CSV

Read by `lidar_analysis/pipeline_core.py::load_files_from_paths`.

Required columns:

```text
time_s, count, roll_deg, pitch_deg, yaw_deg, pps
```

Optional column:

```text
imu_time_s
```

### Cart Config

Required path:

```text
INPUT_DIR/cart_config.yaml
```

This is enforced in `lidar_analysis/central_runner.py::run_experiment_date`, which raises `FileNotFoundError` if the file is missing.

### Experiment Config

Resolved by `lidar_analysis/central_runner.py::resolve_config_path`.

Use one of:

```text
--config /path/to/experiment_config.yaml
INPUT_DIR/experiment_config.yaml
INPUT_DIR/source/experiment_config.yaml
```

## Main Command: central_runner

Verified from `lidar_analysis/central_runner.py::parse_args`:

```bash
python3 -m lidar_analysis.central_runner \
  --experiment EXPERIMENT_NAME \
  --date DATE_NAME \
  --input INPUT_DIR \
  --working WORKING_DIR \
  --output OUTPUT_DIR \
  --config CONFIG_YAML \
  --fusion interp
```

Optional flags verified from `parse_args`:

```text
--cart-id ID
--force
--fusion interp|imu_interp|pps
```

`--config` is optional only if `INPUT_DIR/experiment_config.yaml` or `INPUT_DIR/source/experiment_config.yaml` exists.

## Alternative Wrapper Command

Verified from `lidar_analysis/run_experiment_date.py::parse_args` and `lidar_analysis/run_experiment_date.py::call_runner`:

```bash
python3 -m lidar_analysis.run_experiment_date \
  --experiment EXPERIMENT_NAME \
  --date DATE_NAME \
  --input INPUT_DIR \
  --working WORKING_DIR \
  --output OUTPUT_DIR \
  --config CONFIG_YAML \
  --fusion interp
```

The wrapper imports `lidar_analysis.central_runner` and calls `central_runner.run_experiment_date` when that function exists.

## Example Data Status

The repository includes:

```text
lidar_analysis/example_data/2026_04_28_1/
  2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026_lidar.csv
  2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026_pico.csv
  markers/2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026_marker.csv
```

Observed missing files:

```text
lidar_analysis/example_data/2026_04_28_1/cart_config.yaml
lidar_analysis/example_data/2026_04_28_1/experiment_config.yaml
```

Because `central_runner.run_experiment_date` requires `cart_config.yaml`, the example data cannot be documented as runnable end to end without adding those config files.

## Where Outputs Are Written

With `central_runner`, outputs are written to `OUTPUT_DIR`.

From `lidar_analysis/central_runner.py::run_experiment_date`:

```text
OUTPUT_DIR/results.csv
OUTPUT_DIR/pointclouds/
```

`results.csv` is created by `ensure_results_csv` and populated by `append_trait_rows`.

Point-cloud CSVs are written by `lidar_analysis/pipeline_core.py::Plot.write`.

## How To Know A Run Succeeded

A successful `central_runner` run should:

1. Print lines like `[Run] Processing scan ...` from `central_runner.run_experiment_date`.
2. Print `[Success] SCAN_ID: wrote N phenotype row(s)` after each scan.
3. Create `OUTPUT_DIR/results.csv`.
4. Create at least one CSV under `OUTPUT_DIR/pointclouds/` when `generate_pointclouds` / `make_point_cloud` is enabled and points survive filters.

The orchestrator path also validates outputs in `lidar_analysis/orchestrator.py::validate_output_package`, which requires:

```text
package/results/results.csv
package/pointclouds/<at least one file>
```

## Watcher and Orchestrator Paths

There are two higher-level workflows.

### Manifest Orchestrator

Implemented in `lidar_analysis/orchestrator.py`.

Default paths from `PipelinePaths` and `DEFAULT_PATHS`:

```text
raw_root=/mnt/cartcity/raw_data
experiments_root=/mnt/cartcity/experiments
workspace_root=/media/central/raw_mirror
manifest_root=/media/central/raw_mirror/manifests
log_root=/media/central/raw_mirror/logs
```

`lidar_analysis/local_run.py` exposes a local CLI around `orchestrator.process_one_date`.

Verified command shape from `lidar_analysis/local_run.py::parse_args`:

```bash
python3 -m lidar_analysis.local_run \
  --experiment EXPERIMENT_NAME \
  --date DATE_NAME \
  --raw-root RAW_ROOT \
  --experiments-root EXPERIMENTS_ROOT \
  --workspace-root WORKSPACE_ROOT \
  --force
```

Optional flags:

```text
--publish
--reuse-staged-input
```

### Central Watcher

Implemented in `lidar_analysis/central_watcher.py`.

Default paths:

```text
RAW_ROOT=/mnt/cartcity/raw_data
CONFIG_TEMPLATES_ROOT=/mnt/cartcity/config_templates
LOCAL_ROOT=/media/central/raw_mirror
```

Verified commands from `central_watcher.py::parse_args`:

```bash
python3 -m lidar_analysis.central_watcher poll --once
python3 -m lidar_analysis.central_watcher poll --experiment EXP --date DATE
python3 -m lidar_analysis.central_watcher rerun EXP DATE
```

The watcher uses `rsync` in `central_watcher.py::sync_dir_contents`. It preserves local `source/experiment_config.yaml` unless `--overwrite-config` is used.

## Common Errors And Fixes

| Error / Symptom | Evidence | Likely fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'yaml'` | `central_runner.py`, `pipeline_core.py`, `orchestrator.py`, and `run_manifest.py` import `yaml` directly. | Install PyYAML in the Python environment. The repo does not provide a requirements file. |
| `Missing cart config YAML` | Raised by `central_runner.run_experiment_date`. | Add `INPUT_DIR/cart_config.yaml`. |
| `Experiment config not found` | Raised by `central_runner.resolve_config_path`. | Provide `--config` or add `experiment_config.yaml` to input folder. |
| No scan pairs found | `central_runner.discover_scan_pairs` only pairs `*_lidar.csv` with `*_pico.csv`. | Check file names and input directory level. |
| Missing marker file | `pipeline_core.process_scan` calls `find_marker_file_for_scan` when `split_source` is `marks`. | Add marker CSV under `markers/` or set missing marker behavior to `distance` or `skip`. |
| Empty point clouds | `process_scan` returns early if fusion, reconstruction, filters, or splitting produce no points. | Loosen filters, verify calibration, verify fusion method, inspect scan naming. |
| PCL backend requested | `_BackendResolver.resolve` in `pointcloud_ops.py` raises for `pcl`, `pclpy`, and `python_pcl`. | Use the default SciPy backend. Current code does not implement PCL backends. |

