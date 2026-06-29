# Contributing Guide

This guide focuses on changes that affect scientific behavior, output schemas, or pipeline configuration.

## Read First

| Area | Files |
| --- | --- |
| Runner and config flow | `lidar_analysis/central_runner.py`, `lidar_analysis/config.py` |
| Core processing | `lidar_analysis/pipeline_core.py`, `lidar_analysis/pipeline_stages.py` |
| Fusion | `lidar_analysis/fusion.py`, `lidar_analysis/fusion_imu_interp.py`, `lidar_analysis/fusion_pps.py` |
| Markers | `lidar_analysis/mark_splitting.py` |
| Point-cloud operations | `lidar_analysis/pointcloud_ops.py` |
| Traits | `lidar_analysis/lai/`, `lidar_analysis/topology/` |
| Tests | `tests/` |

## Adding A Config Option

1. Add the dataclass field and default in `config.AnalysisConfig`.
2. Wire YAML parsing in `central_runner.build_config`.
3. Use the value in the narrowest processing function that needs it.
4. Add or update tests under `tests/`.
5. Document the key in `docs/CONFIGURATION.md`.

Keep aliases explicit. If a legacy key is supported, document whether it is active, deprecated, or ignored.

## Adding A Point-Cloud Operation

1. Add the operation name to `pointcloud_ops._SUPPORTED_OPS`.
2. Implement the operation in `pointcloud_ops.py`.
3. Wire it inside `pointcloud_ops.apply_pointcloud_ops`.
4. Preserve `X`, `Y`, `Z`, and `RSSI` unless there is a documented scientific reason to remove a field.
5. Add tests in `tests/test_pointcloud_ops_smoke.py` or a focused new test file.

Point-cloud operation config sizes are generally in meters, while `pipeline_core` stores active point coordinates in millimeters before writing CSV output.

## Adding Marker Behavior

1. Keep canonical split selection in `central_runner.resolve_splitting_style`.
2. Keep marker buffer resolution in `central_runner.resolve_buffer_u`.
3. Extend marker parsing or segment construction in `mark_splitting.py`.
4. Add tests similar to `tests/test_splitting_style_smoke.py` and `tests/test_marker_reference_points_smoke.py`.

Marker CSV parsing currently expects `target_type`, `target_number`, `mark_role`, and `encoder_count`.

## Adding Tests

Use focused tests for:

| Change | Suggested test target |
| --- | --- |
| Config defaults or aliases | `tests/test_config_defaults.py` |
| Fusion behavior | `tests/test_fusion_imu_interp_smoke.py` or a new fusion test |
| Marker splitting | `tests/test_splitting_style_smoke.py` |
| Point-cloud operations | `tests/test_pointcloud_ops_smoke.py` |
| Runner wrapper behavior | `tests/test_run_experiment_date_wrapper.py` |

Recommended command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

## Validation Before Committing

Run the narrowest relevant test plus a syntax check:

```bash
python3 -m py_compile lidar_analysis/*.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

If dependencies are missing, document the exact missing package and the command that failed.

## Scientific Reproducibility Cautions

| Topic | Requirement |
| --- | --- |
| Coordinates | Preserve `X = left/right`, `Y = vertical height`, `Z = travel direction`. |
| Units | Clearly document meters vs millimeters for any new calculation. |
| Output schema | Preserve `X`, `Y`, `Z`, `RSSI` in point-cloud CSVs unless a documented output version change is introduced. |
| Config behavior | Avoid silent behavior changes to existing config keys. |
| Filtering | Record thresholds and output folders for every experiment run. |
| Traits | Explain whether a trait uses raw reconstructed points, filtered points, or sky-facing beam rows. |
