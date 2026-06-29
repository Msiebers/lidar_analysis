# Running The Pipeline

The active local runner is `lidar_analysis/central_runner.py`. The command-line options below are verified from `central_runner.parse_args`.

## Required Input Structure

```text
INPUT_DIR/
  cart_config.yaml
  experiment_config.yaml        # may be absent in many data folders
  <scan_id>_lidar.csv
  <scan_id>_pico.csv
  markers/
    <scan_id>_markers.csv       # required only for marker-based splitting
```

`central_runner.discover_scan_pairs` scans only the top level of `INPUT_DIR` for matching `_lidar.csv` and `_pico.csv` files with the same scan base name.

`central_runner.resolve_config_path` accepts one of:

```text
--config CONFIG_YAML
INPUT_DIR/experiment_config.yaml
INPUT_DIR/source/experiment_config.yaml
```

`central_runner.run_experiment_date` requires `INPUT_DIR/cart_config.yaml`.

Many project data folders already include `cart_config.yaml` but do not include `experiment_config.yaml`. In that case, keep the data folder unchanged and pass an experiment config from another location with `--config CONFIG_YAML`. The config can also be copied to `INPUT_DIR/experiment_config.yaml` or `INPUT_DIR/source/experiment_config.yaml` if a self-contained input folder is preferred.

## Main Command

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

Optional flags verified in `central_runner.parse_args`:

| Flag | Meaning |
| --- | --- |
| `--cart-id ID` | Override cart ID from calibration |
| `--force` | Set `AnalysisConfig.reprocess_scans` for this run |
| `--fusion interp|imu_interp|pps` | Override the fusion method |

`--config` is optional only when the experiment config exists at one of the default locations above. For data folders that include `cart_config.yaml` but not `experiment_config.yaml`, use `--config`.

## Wrapper Command

`lidar_analysis/run_experiment_date.py` is a compatibility wrapper around `central_runner.run_experiment_date`.

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

The wrapper resolves `INPUT_DIR/experiment_config.yaml` unless `--config` is supplied. If the data folder has `cart_config.yaml` but no experiment config, pass `--config CONFIG_YAML`.

## Watcher And Orchestrator Paths

Two higher-level workflows exist for mounted or staged data:

| Module | Purpose |
| --- | --- |
| `lidar_analysis/central_watcher.py` | Poll/rerun workflow using paths such as `/mnt/cartcity/raw_data` and `/media/central/raw_mirror` |
| `lidar_analysis/orchestrator.py` | Manifest-style staging, running, packaging, and optional publishing |

Use `central_runner.py` first for local development because it has the smallest required surface area.

## Expected Outputs

After a successful run, `central_runner.run_experiment_date` writes:

```text
OUTPUT_DIR/
  results.csv
  pointclouds/
    *.csv
```

Point-cloud CSVs are written only when `generate_pointclouds: true` maps to `AnalysisConfig.make_point_cloud` and points remain after filtering.

## Success Criteria

A successful scan normally prints messages such as:

```text
[Run] Processing scan <scan_id>
[Success] <scan_id>: wrote <N> phenotype row(s)
```

Also confirm:

| Check | Expected result |
| --- | --- |
| `OUTPUT_DIR/results.csv` | Exists and has rows beyond the header when targets were processed |
| `OUTPUT_DIR/pointclouds/` | Contains CSVs when point-cloud generation is enabled |
| CloudCompare import | CSV columns map cleanly to `X`, `Y`, `Z`, and scalar fields |

## Common Run Failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'yaml'` | `central_runner.py` and `pipeline_core.py` import `yaml` | Install PyYAML in the active environment |
| `Missing cart config YAML` | `INPUT_DIR/cart_config.yaml` is absent | Add the cart calibration file to `INPUT_DIR` |
| `Experiment config not found` | Many data folders include `cart_config.yaml` but not `experiment_config.yaml`; no `--config` was supplied | Provide `--config CONFIG_YAML`, copy a config to `INPUT_DIR/experiment_config.yaml`, or place it at `INPUT_DIR/source/experiment_config.yaml` |
| No scan pairs found | File names do not end with matching `_lidar.csv` and `_pico.csv` | Rename or place files at the input root |
| Missing marker file | `splitting_style: plant` or `plot` resolves to marker mode | Add marker CSVs or configure missing-marker behavior |
