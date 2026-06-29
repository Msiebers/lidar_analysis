# Troubleshooting

This document lists common problems based on repository code and the observed local environment.

## Missing Dependencies

Symptoms:

```text
ModuleNotFoundError
```

Evidence:

- `lidar_analysis/central_runner.py` imports `yaml`.
- `lidar_analysis/pipeline_core.py` imports `numpy`, `pandas`, `yaml`, and `scipy`.
- `lidar_analysis/pointcloud_ops.py` imports `scipy.spatial.cKDTree`.
- `scripts/plot_pcl_summary.py` imports `matplotlib.pyplot`.

Observed missing modules in the current environment:

```text
yaml / PyYAML
matplotlib
```

Fix:

The repo has no dependency file. An inferred install command is:

```bash
python3 -m pip install numpy pandas scipy PyYAML pytest matplotlib
```

This command is inferred from imports, not from a repository dependency manifest.

## Missing `yaml` / PyYAML

Symptom:

```text
ModuleNotFoundError: No module named 'yaml'
```

Observed when running:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

Why:

`central_runner.py`, `pipeline_core.py`, `orchestrator.py`, and `run_manifest.py` import `yaml` directly.

Fix:

Install PyYAML.

Note:

`lidar_analysis/yaml_loader.py` has a fallback YAML loader, but the active runner and core modules do not consistently use it.

## Missing `cart_config.yaml`

Symptom:

```text
FileNotFoundError: Missing cart config YAML: INPUT_DIR/cart_config.yaml
```

Evidence:

`lidar_analysis/central_runner.py::run_experiment_date` checks:

```text
input_dir / "cart_config.yaml"
```

Fix:

Place `cart_config.yaml` at the root of the input directory.

## Missing Experiment Config

Symptom:

```text
Experiment config not found
```

Evidence:

`lidar_analysis/central_runner.py::resolve_config_path` tries:

```text
--config CFG
INPUT_DIR/experiment_config.yaml
INPUT_DIR/source/experiment_config.yaml
```

Fix:

Pass `--config /path/to/experiment_config.yaml` or add the file to one of the expected locations.

## No Scan Pairs Found

Symptom:

No scans are processed, or output `results.csv` has only headers.

Evidence:

`lidar_analysis/central_runner.py::discover_scan_pairs` only pairs files ending in:

```text
_lidar.csv
_pico.csv
```

Fix:

Confirm both files are in the input directory root and share the same base name before `_lidar.csv` / `_pico.csv`.

## Missing Marker Files

Symptom:

```text
No marker file found for SCAN_ID
```

Evidence:

`lidar_analysis/pipeline_core.py::process_scan` calls `mark_splitting.find_marker_file_for_scan` when `cfg.split_source == "marks"`.

Fix options:

- Put marker CSV under `INPUT_DIR/markers/`.
- Name it like `SCAN_BASE_marker.csv` or `SCAN_BASE_markers.csv`.
- Set missing marker behavior if appropriate:

```yaml
analysis:
  missing_mark_file: distance
```

or:

```yaml
analysis:
  missing_mark_file: skip
```

Use `error` when markers are required and missing files should fail the run.

## Empty Point Clouds

Symptoms:

- No point-cloud CSVs.
- `results.csv` has zero or low `points`.
- Logs mention no matched rows or no points remaining.

Evidence:

`pipeline_core.process_scan` returns early if:

- LiDAR or Pico CSV load empty.
- fusion returns empty.
- reconstruction returns empty.
- global filters remove all points.
- RSSI filter removes all points.
- splitting produces no ranges or marker segments.

Fix checklist:

1. Confirm LiDAR/Pico columns match `load_files_from_paths`.
2. Try `fusion_method: interp` before `pps`.
3. Loosen `row_width_u`, `x_min_u`, `max_y_u`, `min_radius_u`.
4. Turn off `use_rssi_filter`.
5. Check marker windows and `buffer_u`.
6. Check calibration values in `cart_config.yaml`.

## CloudCompare Imports All Columns Incorrectly

Symptom:

CloudCompare shows one giant text column or cannot parse coordinates.

Fix:

- Set separator to comma.
- Skip or use the header row.
- Assign `X`, `Y`, `Z` as coordinates.
- Assign `RSSI` and other fields as scalar fields.

Repository evidence:

`pipeline_core.Plot.write` writes CSV using pandas `to_csv`, so the delimiter is comma by default.

## CloudCompare Shows A Flat Or Sideways Cloud

Possible causes:

- Wrong columns assigned during import.
- `Y` and `Z` swapped in CloudCompare.
- A filter clipped one dimension.
- IMU/heading correction changed orientation.

Repository convention:

```text
X = left/right
Y = vertical height
Z = travel direction
```

Fix:

Import `X`, `Y`, `Z` exactly as named. Do not use `dist_mm` as a coordinate.

## Output Folder Not Changing Because Overwrite Is Disabled

Symptom:

Point-cloud CSVs appear unchanged across runs.

Evidence:

`pipeline_core.Plot.write` returns early if:

```text
overwrite_outputs is false and csv_out already exists
```

Fix:

Use a new `--output` folder or set:

```yaml
analysis:
  overwrite_pointclouds: true
```

## PCL Backend Config Problems

Symptom:

```text
Backend 'pcl' requested but not implemented. Only 'scipy' is available.
```

Evidence:

`lidar_analysis/pointcloud_ops.py::_BackendResolver.resolve` raises for:

```text
pcl
pclpy
python_pcl
```

Fix:

Do not request PCL backends. Use the default SciPy behavior.

Note:

`POINTCLOUD_OPS_NOTE.md` says PCL-compatible names are accepted, but the active implementation is Python/SciPy.

## Broken Or Stale Tests

Observed pytest status:

```text
5 collection errors due to missing yaml / PyYAML
```

Additional source-inspection risks:

- `tests/test_additional_scan_side_split.py` calls `analyze_plot` with the old argument list.
- `tests/test_pointcloud_ops_smoke.py` unpacks `topology_stand_count` as if it returned a tuple, but `topology_stand_count` returns a dict.
- `tests/test_mark_splitting_smoke.py` duplicates `tests/test_splitting_style_smoke.py`.

Fix:

1. Install PyYAML.
2. Run pytest again.
3. Update stale tests to match current function signatures and return types.

## Example Data Does Not Run End To End As-Is

Observed files present:

```text
lidar_analysis/example_data/2026_04_28_1/*_lidar.csv
lidar_analysis/example_data/2026_04_28_1/*_pico.csv
lidar_analysis/example_data/2026_04_28_1/markers/*_marker.csv
```

Observed missing files:

```text
lidar_analysis/example_data/2026_04_28_1/cart_config.yaml
lidar_analysis/example_data/2026_04_28_1/experiment_config.yaml
```

Because `central_runner.run_experiment_date` requires `cart_config.yaml`, add calibration/config files before using the fixture as an end-to-end test.

