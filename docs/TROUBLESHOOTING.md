# Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'yaml'` | PyYAML is missing; `central_runner.py`, `pipeline_core.py`, `orchestrator.py`, and `run_manifest.py` import `yaml` | Install PyYAML in the active Python environment |
| Missing dependency errors for `numpy`, `pandas`, or `scipy` | Core pipeline imports these packages | Install the missing package before running tests or analysis |
| `Missing cart config YAML` | `central_runner.run_experiment_date` requires `INPUT_DIR/cart_config.yaml` | Add `cart_config.yaml` to the input directory |
| `Experiment config not found` | The data folder may include `cart_config.yaml` but not `experiment_config.yaml`; `central_runner.resolve_config_path` cannot find `--config`, `INPUT_DIR/experiment_config.yaml`, or `INPUT_DIR/source/experiment_config.yaml` | Pass an external config with `--config CONFIG_YAML`, copy a config to `INPUT_DIR/experiment_config.yaml`, or place it at `INPUT_DIR/source/experiment_config.yaml` |
| No scan pairs found | `central_runner.discover_scan_pairs` only matches top-level `*_lidar.csv` and `*_pico.csv` pairs | Confirm both files share the same scan base name and are in `INPUT_DIR` |
| Missing marker file | Marker mode is active through `splitting_style: plant` or `plot`, but no marker file matches | Add a marker CSV such as `markers/<scan_id>_markers.csv` or set `missing_mark_file: distance` or `skip` intentionally |
| Multiple marker files matched | `mark_splitting.find_marker_file_for_scan` found ambiguous candidates | Rename the intended file to `<scan_id>_markers.csv` |
| Empty point clouds | Fusion, reconstruction, global filters, RSSI filters, or splitting removed all rows | Start with `fusion_method: interp`, loosen filters, disable RSSI filtering, and confirm calibration values |
| Output CSVs do not change | `overwrite_pointclouds: false` maps to `AnalysisConfig.overwrite_outputs`; `Plot.write` returns early if the file exists | Use a new output directory or set `overwrite_pointclouds: true` |
| CloudCompare imports all data as one column | The CSV separator was not set to comma | Re-import as ASCII/CSV with comma separator and a header row |
| CloudCompare shows a flat or sideways cloud | `X`, `Y`, and `Z` were assigned incorrectly | Assign `X` to X, `Y` to Y, and `Z` to Z; do not use `dist` as a coordinate |
| PCL backend error | `pointcloud_ops._BackendResolver` raises for `pcl`, `pclpy`, and `python_pcl` | Use the default SciPy backend; PCL backends are not implemented |
| `rssi_norm_scope` appears ignored | `config.map_deprecated_analysis_keys` removes it and warns | Use `normalize_rssi` and `rssi_norm_mode`; do not use `rssi_norm_scope` |
| `run_mta` or `run_fad` has no effect | No active config keys with those names were found | Use `run_lai` for LAI/FAD-related trait generation supported by the current code |

## Known Limitations

Many project data folders are expected to contain `cart_config.yaml` but not `experiment_config.yaml`. This is supported when the run command includes `--config CONFIG_YAML`.

The example fixture at `lidar_analysis/example_data/2026_04_28_1/` is not directly runnable end to end because the required `cart_config.yaml` and `experiment_config.yaml` are not present in that folder.

The repository currently has no dependency manifest. Dependency installation must be inferred from imports until a project-level dependency file is added.
