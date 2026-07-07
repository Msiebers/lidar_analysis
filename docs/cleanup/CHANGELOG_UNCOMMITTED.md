# Uncommitted Cleanup Changelog

This changelog records the small cleanup pass based on `docs/cleanup/CLEANUP_AUDIT.md` and `docs/cleanup/CLEANUP_PLAN.md`. At the start of this pass, `git status --short --branch` reported a clean `christian-branch`.

## Files Changed

| File | Change | Reason | Behavior impact | Rollback | Checks |
| --- | --- | --- | --- | --- | --- |
| `README.md` | Closed the `Important Files` code block, clarified that listed source files live under `lidar_analysis/`, added `fusion_imu_interp.py`, corrected `topology.py` to `topology/`, and added links to the new docs. | The cleanup audit identified stale README references and broken Markdown formatting. | Documentation-only; no runtime behavior changes. | Revert `README.md`. | `git diff --check` passed; `python3 -m py_compile lidar_analysis/*.py` passed; `python3 -m pytest -q` failed during collection because `yaml` / PyYAML is missing. |
| `requirements.txt` | Added a minimal dependency manifest inferred from imports in `lidar_analysis/` and `tests/`; left `matplotlib` documented as an optional dependency for `scripts/plot_pcl_summary.py`. | Pytest collection failed because `yaml` / PyYAML was missing, and the repository previously had no dependency manifest. `matplotlib` was kept optional because it is script-only and made the full install slow in this environment. | Install-workflow only; no runtime code behavior changes. Versions are unpinned because the repo has no owner-approved package versions or lockfile. | Delete `requirements.txt`. | `python3 -m pip install -r requirements.txt` passed after installing `PyYAML`; `git diff --check` passed; `python3 -m py_compile lidar_analysis/*.py tests/*.py` passed. |
| `docs/RUNNING_THE_PIPELINE.md` | Added the `python3 -m pip install -r requirements.txt` setup command and pointed the missing-`yaml` fix to the manifest. | Gives new users a concrete dependency setup path before running `central_runner`. | Documentation-only; no runtime behavior changes. | Revert `docs/RUNNING_THE_PIPELINE.md`. | `git diff --check` passed. |
| `docs/TESTING_AND_VALIDATION.md` | Updated dependency guidance to reference `requirements.txt`, documented why versions are unpinned, and documented `matplotlib` as optional for the plotting helper. | Keeps testing docs aligned with the new manifest while preserving the reproducibility caveat. | Documentation-only; no runtime behavior changes. | Revert `docs/TESTING_AND_VALIDATION.md`. | `git diff --check` passed. |
| `docs/TROUBLESHOOTING.md` | Replaced inferred dependency guidance with `requirements.txt` install guidance and documented that versions are unpinned. | Makes dependency failures easier to fix without guessing package names. | Documentation-only; no runtime behavior changes. | Revert `docs/TROUBLESHOOTING.md`. | `git diff --check` passed. |
| `lidar_analysis/pipeline_core.py` | Added a concise comment in `Plot.write()` documenting that internal point coordinates are in millimeters and point-cloud CSV output writes X/Y/Z in meters. | The cleanup plan requested comments at high-risk unit boundaries. | Comment-only; no runtime behavior changes. | Revert the comment addition. | `git diff --check` passed; `python3 -m py_compile lidar_analysis/*.py` passed; `python3 -m pytest -q` failed during collection because `yaml` / PyYAML is missing. |
| `tests/test_additional_scan_side_split.py` | Renamed the script-style `main()` body to `test_additional_scan_side_split_smoke()` and kept the standalone script entry point. | Allows pytest to collect the existing smoke assertion without changing what it checks. | Test-suite structure only; no pipeline runtime behavior changes. | Revert this test file. | `python3 -m py_compile tests/*.py` passed; full pytest still needs PyYAML installed. |
| `tests/test_fusion_imu_interp_smoke.py` | Renamed the script-style `main()` body to `test_fusion_imu_interp_smoke()` and kept the standalone script entry point. | Allows pytest to collect the existing smoke assertion without changing fusion code. | Test-suite structure only; no pipeline runtime behavior changes. | Revert this test file. | `python3 -m pytest -q tests/test_fusion_imu_interp_smoke.py -p no:cacheprovider` passed with one existing endpoint-clamping warning. |
| `tests/test_mark_splitting_smoke.py` | Converted the file into a compatibility wrapper around `tests/test_splitting_style_smoke.py::test_splitting_style_resolution_smoke`, including a small repo-root `sys.path` setup for direct script execution. | These two files duplicated the same assertions. Keeping the old filename as a wrapper avoids deleting a known test entry point while centralizing the assertions. | Test-suite structure only; no pipeline runtime behavior changes. | Revert this test file to restore the duplicate assertion body. | `python3 tests/test_mark_splitting_smoke.py` passed; `python3 -m pytest -q tests/test_mark_splitting_smoke.py tests/test_splitting_style_smoke.py -p no:cacheprovider` passed. |
| `tests/test_marker_reference_points_smoke.py` | Renamed the script-style `main()` body to `test_marker_reference_points_smoke()` and kept the standalone script entry point. | Allows pytest to collect the existing marker-reference smoke assertion without changing output logic. | Test-suite structure only; no pipeline runtime behavior changes. | Revert this test file. | `python3 -m py_compile tests/*.py` passed; full pytest still needs PyYAML installed. |
| `tests/test_splitting_style_smoke.py` | Renamed the script-style `main()` body to `test_splitting_style_resolution_smoke()` and kept the standalone script entry point. | Allows pytest to collect the existing smoke assertion without changing splitting logic. | Test-suite structure only; no pipeline runtime behavior changes. | Revert this test file. | `python3 -m py_compile tests/*.py` passed; full pytest still needs PyYAML installed. |
| `docs/cleanup/CHANGELOG_UNCOMMITTED.md` | Updated this changelog to describe the actual files changed in this pass, safety level, rollback path, and validation status. | Keeps the cleanup work reviewable and easy to revert. | Documentation-only; no runtime behavior changes. | Revert this file. | `git diff --check` passed; `python3 -m py_compile lidar_analysis/*.py` passed; `python3 -m pytest -q` failed during collection because `yaml` / PyYAML is missing. |

## Verified Existing Safe Cleanup

- `lidar_analysis/config.py::default_analysis_yaml_dict` already has a normal `# Backward compatibility:` comment; the stray `d# Backward compatibility:` expression was not present at the start of this pass.
- `lidar_analysis/pipeline_core.py` already had comments documenting `_to_cartesian_mm()` coordinate sign convention, `choose_fusion_method()` fused row column order, and `reconstruct_world_points()` fused-array indexing / millimeter boundary.
- `lidar_analysis/pointcloud_ops.py` already had comments documenting meter-based operation config values versus internal millimeter coordinates in `_voxel_count()` and `_bilateral_scalar_filter()`.
- `tests/test_mark_splitting_smoke.py` and `tests/test_splitting_style_smoke.py` were originally duplicate tests. This pass kept `test_splitting_style_smoke.py` as canonical and made `test_mark_splitting_smoke.py` a wrapper for compatibility.

## Changes Deferred

- Did not rename `pipeline_core.analyze_plot` local variable `goto_open3d`; it is a readability-only candidate, but leaving it unchanged keeps this pass smaller.
- Did not delete the duplicate smoke test filename; it remains as a compatibility wrapper.
- Did not pin dependency versions because the repository does not provide owner-approved package versions or a locked environment.
- Did not install optional `matplotlib`; it is only needed for `scripts/plot_pcl_summary.py`.
- Did not change runtime YAML loading or import behavior.
- Did not update the four failing tests or underlying behavior discovered after PyYAML unblocked full pytest collection; those require a separate test-expectation / behavior review.
- Did not change config defaults, config aliases, calibration behavior, CSV schemas, logging behavior, coordinate math, IMU correction, RSSI normalization, LAI, FAD, topology, fusion math, or point-cloud operation math.

## Validation

Validation results:

```bash
git diff --check
# passed with no output

python3 -m py_compile lidar_analysis/*.py tests/*.py
# passed with no output

python3 -m pip install -r requirements.txt
# passed after PyYAML 6.0.3 was installed; optional matplotlib is not in requirements.txt

python3 -m pytest -q tests/test_fusion_imu_interp_smoke.py -p no:cacheprovider
# passed: 1 test, 1 warning from fusion_imu_interp endpoint clamping

python3 -m pytest -q tests/test_mark_splitting_smoke.py tests/test_splitting_style_smoke.py -p no:cacheprovider
# passed: 2 tests

python3 tests/test_mark_splitting_smoke.py
# passed: printed PASS

python3 -m pytest -q
# collected and ran 25 tests after PyYAML install:
# 21 passed, 4 failed, 1 warning
```

The full-suite failures after dependency installation are:

- `tests/test_additional_scan_side_split.py::test_additional_scan_side_split_smoke`: stale call to `analyze_plot`; missing required `beam_diag` argument.
- `tests/test_pointcloud_ops_smoke.py::test_ops_alias_enabled_and_named_scalar_filter`: expected `voxel_count == 3`, observed `1`.
- `tests/test_pointcloud_ops_smoke.py::test_zscore_no_clip_and_source_has_no_clip_call`: expected normalized RSSI max above `exp(4.0)`, observed about `5.65`.
- `tests/test_pointcloud_ops_smoke.py::test_topology_stand_count_direct_simple_meter_cloud`: expected two return values from `topology_stand_count`, observed three.

These failures are now visible because `PyYAML` is installed. They were not changed in this pass because they touch behavior-sensitive expectations around analysis calls, point-cloud operations, RSSI normalization, and topology return contracts.
