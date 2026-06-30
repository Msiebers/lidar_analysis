# Uncommitted Cleanup Changelog

This changelog records the cleanup changes made after `docs/cleanup/CLEANUP_AUDIT.md` and `docs/cleanup/CLEANUP_PLAN.md`. No commits have been created for these changes.

## Files Changed

| File | What changed | Why it changed | Behavior changed? | Risk level | How to revert |
| --- | --- | --- | --- | --- | --- |
| `docs/cleanup/CLEANUP_AUDIT.md` | Added a risk-classified cleanup audit. | Captures safe, behavior-sensitive, and risky cleanup opportunities before editing code. | No. | Safe cleanup | Delete the file or revert `docs/cleanup/`. |
| `docs/cleanup/CLEANUP_PLAN.md` | Added a phased cleanup plan. | Groups future cleanup into reviewable batches with tests and rollback notes. | No. | Safe cleanup | Delete the file or revert `docs/cleanup/`. |
| `docs/cleanup/CHANGELOG_UNCOMMITTED.md` | Added this uncommitted changelog. | Documents each cleanup change, risk, behavior impact, rollback path, and validation. | No. | Safe cleanup | Delete the file. |
| `lidar_analysis/config.py` | Replaced the stray no-op `d# Backward compatibility:` line with a normal comment. | The previous line was valid Python but confusing because it evaluated `d` as a no-op expression before a comment. | No. The dictionary content and alias handling are unchanged. | Safe cleanup | Revert the one-line comment change. |
| `lidar_analysis/pipeline_core.py` | Added comments documenting coordinate sign convention, fused row column order, and the millimeter-to-meter boundary before CSV output. | These are behavior-sensitive contracts that future maintainers should see before editing reconstruction or output code. | No. Comments only. | Safe cleanup | Revert the comment additions. |

## Changes Deferred

The following items were audited but not changed:

- Duplicate smoke tests: `tests/test_mark_splitting_smoke.py` and `tests/test_splitting_style_smoke.py`.
- Legacy `pipeline_core.run_experiment` / `run_for_directory` path.
- Calibration loader process exits in `pipeline_core.load_calibration`.
- Ambiguous compatibility config fields such as `write_lidar_per_plot`.
- YAML loading strategy across `yaml_loader.py` and direct `yaml` imports.
- Coordinate, IMU, RSSI, LAI/FAD/topology, and output schema logic.

## Validation

Validation requested for this cleanup pass:

```bash
git diff --stat
git diff --check
python3 -m py_compile lidar_analysis/*.py
```

Results should be recorded in the final response after the commands are run.
