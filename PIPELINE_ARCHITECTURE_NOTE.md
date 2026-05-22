# Pipeline cleanup note

## Module responsibilities
- `central_watcher.py`: unchanged polling/rerun/publish routing.
- `central_runner.py`: experiment/date runner and config-to-AnalysisConfig parsing.
- `run_experiment_date.py`: thin compatibility CLI wrapper around `central_runner`.
- `pipeline_core.py`: scan processing and target-level analysis orchestration.
- `pointcloud_ops.py`: ordered per-target pointcloud operations.
- `config.py`: single source of analysis defaults and config normalization helpers.

## Config source-of-truth
- New experiment scaffolds now build `analysis` defaults via `config.default_analysis_yaml_dict()`.
- `scaffold_experiments.py` imports defaults from `config.py` instead of hardcoded analysis defaults.

## AnalysisTarget lifecycle
- `AnalysisTarget` carries `raw_points`, `current_points`, `traits`, `diagnostics`, `op_history`, and `source_indices`.
- `raw_points` stays immutable by convention.
- pointcloud ops update only `current_points` and append ordered `op_history`.

## RSSI simplification
- Only `zscore` and `percentile` are active normalization modes.
- deprecated `rssi_norm_scope` is mapped to the simplified behavior (normalize after global masks) with warning.

## Removed/deprecated components
- Removed Open3D helper backend module and topology placeholder module from active codebase.
- Removed test files from `lidar_analysis/`; tests now live under `tests/`.
