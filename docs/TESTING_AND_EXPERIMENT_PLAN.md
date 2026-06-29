# Testing And Experiment Plan

This document gives a practical plan for learning and validating the pipeline. It is based on files in `tests/`, runner code in `lidar_analysis/central_runner.py`, and the observed local test run.

## Dependencies

The repository does not include `requirements.txt`, `pyproject.toml`, `environment.yml`, Dockerfile, or CI config.

Dependencies inferred from imports:

```text
numpy
pandas
scipy
PyYAML
pytest
matplotlib        # only needed for scripts/plot_pcl_summary.py
```

Observed in the current environment:

```text
numpy: installed
pandas: installed
scipy: installed
pytest: installed
matplotlib: missing
yaml / PyYAML: missing
```

Because `lidar_analysis/central_runner.py` and `lidar_analysis/pipeline_core.py` import `yaml` directly, PyYAML is required for the main pipeline and most tests.

Inferred install command, not verified because the repo has no dependency file:

```bash
python3 -m pip install numpy pandas scipy PyYAML pytest matplotlib
```

## Running Existing Tests

Observed command run without creating pytest cache or bytecode:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

Observed result:

```text
5 collection errors
ModuleNotFoundError: No module named 'yaml'
```

Affected test modules:

```text
tests/test_additional_scan_side_split.py
tests/test_mark_splitting_smoke.py
tests/test_marker_reference_points_smoke.py
tests/test_pointcloud_ops_smoke.py
tests/test_splitting_style_smoke.py
```

Why: those tests import `lidar_analysis.pipeline_core` or `lidar_analysis.central_runner`, and those modules import `yaml`.

## Smoke Tests

Some files are script-style smoke tests with a `main()` function and `if __name__ == "__main__"`. They are not fully represented by pytest collection unless they also define `test_...` functions.

Script-style smoke tests include:

```text
tests/test_fusion_imu_interp_smoke.py
tests/test_splitting_style_smoke.py
tests/test_mark_splitting_smoke.py
tests/test_marker_reference_points_smoke.py
tests/test_additional_scan_side_split.py
```

Example smoke command shape:

```bash
python3 tests/test_fusion_imu_interp_smoke.py
```

Do this after installing dependencies. If a script imports `pipeline_core.py` or `central_runner.py`, PyYAML is required.

## Known Test Problems To Fix

These are based on source inspection, not a post-PyYAML pytest run.

| Test file | Issue | Evidence |
| --- | --- | --- |
| `tests/test_additional_scan_side_split.py` | Calls `analyze_plot` without the current `beam_diag` argument. | `pipeline_core.analyze_plot` signature includes `beam_diag`; the test passes fewer arguments. |
| `tests/test_pointcloud_ops_smoke.py` | One test unpacks `topology_stand_count` as `count, points`, but `topology_stand_count` returns a dict. | `lidar_analysis/topology/stand_count.py::topology_stand_count` returns `{"count": ..., "points": ..., "count_raw": ...}`. |
| `tests/test_mark_splitting_smoke.py` and `tests/test_splitting_style_smoke.py` | Duplicated content. | Both files contain the same splitting-style smoke logic. |

## Syntax Check

Observed successful command:

```bash
python3 - <<'PY'
from pathlib import Path
files = sorted(Path('.').glob('lidar_analysis/**/*.py')) + sorted(Path('.').glob('tests/**/*.py')) + sorted(Path('.').glob('scripts/**/*.py'))
for path in files:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print(f'in-memory syntax compile OK: {len(files)} files')
PY
```

Observed result:

```text
in-memory syntax compile OK: 38 files
```

The AGENTS instructions mention `python3 -m py_compile lidar_analysis/*.py` as a minimum. That command is valid Python tooling, but it can create `__pycache__` files. Use it when write artifacts are acceptable.

## Running One Scan Many Times

Use different output directories for each experiment. The runner writes `results.csv` and `pointclouds/` under `--output`.

Command template verified from `central_runner.py::parse_args`:

```bash
python3 -m lidar_analysis.central_runner \
  --experiment EXP \
  --date DATE \
  --input INPUT_DIR \
  --working WORK_DIR \
  --output OUTPUT_DIR \
  --config CONFIG_YAML \
  --force \
  --fusion interp
```

Suggested folder naming:

```text
runs/
  001_baseline/
    work/
    output/
  002_fusion_imu_interp/
    work/
    output/
  003_row_width_2m/
    work/
    output/
```

Run one change at a time. Compare:

- `output/results.csv`
- `output/pointclouds/*.csv`
- CloudCompare screenshots

## Required Before Any End-To-End Run

The example fixture has LiDAR, Pico, and marker files but is missing:

```text
lidar_analysis/example_data/2026_04_28_1/cart_config.yaml
lidar_analysis/example_data/2026_04_28_1/experiment_config.yaml
```

Do not claim end-to-end fixture success until those files are added and documented.

## Testing Matrix

| Run ID | Config changed | Expected effect | Output folder | What to inspect in CSV | What to inspect in CloudCompare | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 001_baseline | `fusion_method: interp`, no pointcloud ops, no RSSI filter | Reference point count and geometry | `runs/001_baseline/output` | `points`, `plot_length_m`, `plot_width_m` | Basic shape and row orientation | Requires valid `cart_config.yaml`. |
| 002_fusion_imu_interp | `fusion_method: imu_interp` or CLI `--fusion imu_interp` | Orientation may differ if `imu_time_s` exists | `runs/002_fusion_imu_interp/output` | `points`, `height_m` if enabled | Tilt/rotation vs baseline | Uses `fusion_imu_interp.py`. |
| 003_fusion_pps | `fusion_method: pps` or CLI `--fusion pps` | Stricter alignment; may drop all rows if PPS sparse | `runs/003_fusion_pps/output` | Whether `results.csv` has rows | Missing or smaller cloud | Uses `fusion_pps.py`; empty output is possible. |
| 004_row_width_narrow | `row_width_u: 2.0` | Removes lateral points beyond +/-2 m when `dim_units: m` | `runs/004_row_width_narrow/output` | Lower `points`, lower `plot_width_m` | Narrower X spread | `apply_global_filters`. |
| 005_row_width_wide | `row_width_u: 5.0` | Keeps wider lateral area | `runs/005_row_width_wide/output` | Higher or equal `points` | More neighboring-row points may appear | Compare to narrow run. |
| 006_y_filter | `max_y_u: 2.0` | Removes points above 2 m if `dim_units: m` | `runs/006_y_filter/output` | Lower `height_m`, lower `points` | Clipped top canopy | `apply_global_filters`. |
| 007_x_min_filter | `x_min_u: 0.2` | Removes points close to X centerline | `runs/007_x_min_filter/output` | Lower `points` | Gap near X=0 | Uses absolute X. |
| 008_rssi_off | `use_rssi_filter: false` | No RSSI thresholding | `runs/008_rssi_off/output` | Baseline `points` | All raw returns | Compare to RSSI on. |
| 009_rssi_low_threshold | `use_rssi_filter: true`, `rssi_min: 10` | Mild low-RSSI removal | `runs/009_rssi_low_threshold/output` | Slightly lower `points` | Low-scalar points removed | Raw `RSSI` filter. |
| 010_rssi_high_threshold | `use_rssi_filter: true`, `rssi_min: 100` | Aggressive low-RSSI removal | `runs/010_rssi_high_threshold/output` | Much lower `points`; possible empty clouds | Sparse cloud | Risk of empty outputs. |
| 011_marker_split | `splitting_style: plant` or `plot`; marker config enabled | Outputs per marker plant/plot windows | `runs/011_marker_split/output` | `plot`, `points`, `z_min_m`, `z_max_m` | Separate target clouds | Requires marker CSV. |
| 012_distance_split | `splitting_style: distance`, `split_u` set | Outputs fixed travel windows | `runs/012_distance_split/output` | Number of plot rows | Regular Z intervals | Depends on scan name and split length. |
| 013_ops_off | `pointcloud_ops: []` | Raw post-global-filter target clouds | `runs/013_ops_off/output` | No `voxel_count` unless column configured absent | Dense/noisy cloud | Compare to ops on. |
| 014_ops_on | Add `sor_filter` and `voxel_count` | Filters outliers and reports voxels | `runs/014_ops_on/output` | `points`, `voxel_count` | Cleaner cloud, fewer isolated points | Ops run in YAML order. |
| 015_traits_off | `run_height: false`, `run_lai: false` | Trait columns limited | `runs/015_traits_off/output` | No height/LAI values | Geometry only | Columns controlled by `phenotype_columns`. |
| 016_traits_on | `run_height: true`, `run_lai: true` | Adds height and LAI traits | `runs/016_traits_on/output` | `height_m`, `lai_even`, `lai_uneven` | Height visually vs CSV | LAI uses sky-facing beam rows. |

## Record Keeping

For each run, save:

```text
CONFIG_YAML
command_used.txt
output/results.csv
CloudCompare screenshot
notes.md
```

The repository does not currently automate this experiment notebook structure.

