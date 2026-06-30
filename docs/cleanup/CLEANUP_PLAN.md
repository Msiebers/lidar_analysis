# Cleanup Plan

The plan groups changes into small reviewable batches. Batches should be applied independently and validated before moving to the next batch.

## Batch 1: Documentation And Comments Only

| Item | Files affected | Exact changes | Expected behavior impact | Rollback strategy | Tests / checks |
| --- | --- | --- | --- | --- | --- |
| Cleanup audit and plan | `docs/cleanup/CLEANUP_AUDIT.md`, `docs/cleanup/CLEANUP_PLAN.md` | Add risk-classified cleanup report and phased plan. | None. | Delete `docs/cleanup/`. | `git diff --check` |
| Code comments at scientific boundaries | `lidar_analysis/pipeline_core.py` | Add comments for fused row column order, coordinate convention, and mm/m output boundary. | None. | Revert comment-only diff. | `python3 -m py_compile lidar_analysis/*.py` |
| Config typo comment cleanup | `lidar_analysis/config.py` | Replace stray no-op `d# Backward compatibility:` with a normal comment. | None. | Revert one-line change. | `python3 -m py_compile lidar_analysis/*.py` |
| Uncommitted changelog | `docs/cleanup/CHANGELOG_UNCOMMITTED.md` | Document every file changed, risk, behavior impact, rollback, and checks. | None. | Delete changelog. | `git diff --check` |

## Batch 2: Low-Risk Readability Cleanup

| Item | Files affected | Exact changes | Expected behavior impact | Rollback strategy | Tests / checks |
| --- | --- | --- | --- | --- | --- |
| README alignment | `README.md` | Point readers to `docs/`, correct stale file references, close any broken Markdown block. | None. | Revert README only. | Markdown review, `git diff --check` |
| Local variable clarity | `pipeline_core.analyze_plot` | Rename local `goto_open3d` to a clearer local name such as `has_plot_points`, if done in a small isolated diff. | None intended. | Revert local rename. | `python3 -m py_compile lidar_analysis/*.py`; relevant smoke tests |
| Narrow helper comments | `pointcloud_ops.py` | Clarify config values in meters vs current points in millimeters at operation boundaries. | None. | Revert comments. | `python3 -m py_compile lidar_analysis/*.py` |

## Batch 3: Test And Config Cleanup

| Item | Files affected | Exact changes | Expected behavior impact | Rollback strategy | Tests / checks |
| --- | --- | --- | --- | --- | --- |
| Duplicate split smoke tests | `tests/test_mark_splitting_smoke.py`, `tests/test_splitting_style_smoke.py` | Keep one canonical test or make one import the other. | Test-suite structure only; no pipeline behavior change. | Restore deleted/changed test file. | `python3 -m pytest -q tests/test_splitting_style_smoke.py tests/test_mark_splitting_smoke.py` |
| Script-style smoke tests | `tests/` | Convert `main()` smoke tests into pytest-collected `test_*` functions. | Test runner behavior improves; pipeline behavior unchanged. | Revert test files. | `python3 -m pytest -q tests` |
| Config key status | `config.py`, docs | Decide whether ambiguous keys such as `write_lidar_per_plot` should be documented, deprecated, or wired to behavior. | Potentially behavior-sensitive if runtime wiring changes. | Revert config/docs changes. | Config tests plus pipeline smoke run |
| Dependency manifest | repository root | Add a minimal dependency manifest if project owners approve package versions. | Install workflow changes; runtime code unchanged. | Remove manifest. | Fresh environment install test |

## Batch 4: Behavior-Sensitive Cleanup Requiring Approval

| Item | Files affected | Exact changes proposed | Expected behavior impact | Rollback strategy | Tests / checks |
| --- | --- | --- | --- | --- | --- |
| Legacy runner repair or removal | `pipeline_core.run_experiment`, `pipeline_core.run_for_directory` | Either fix the undefined `d` path with tests or formally mark/remove the legacy entry point. | Could alter legacy invocation behavior. | Revert legacy-runner diff. | Dedicated legacy-runner test and comparison output |
| Calibration error handling | `pipeline_core.load_calibration`, `central_runner.read_calibration_from_cart_config` | Standardize on exceptions instead of `sys.exit` if legacy loader remains supported. | Error behavior changes. | Revert calibration changes. | Calibration fixture tests |
| Schema constants | `central_runner.phenotype_columns`, `pipeline_core.Plot.write`, legacy summary writer | Centralize output schemas. | Could change CSV columns or ordering. | Revert schema refactor. | Golden CSV header comparison |
| Logging strategy | Core and fusion modules | Replace unconditional debug prints with configurable verbosity. | Logs change; data output should not. | Revert logging refactor. | Pipeline smoke run and log review |
| Coordinate / IMU / RSSI / trait math | Reconstruction, fusion, RSSI, LAI/FAD/topology modules | Only change for a confirmed bug with fixture-based expected outputs. | Scientific outputs may change. | Revert and compare outputs. | Golden point-cloud and trait comparisons |
