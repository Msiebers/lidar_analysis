# CloudCompare Checklist for IMU Tests

Use this checklist after running `scripts/run_imu_tests.sh` on SLIM.

Do not copy pointcloud CSVs into the repo. Open them directly from:

```text
/PATH/TO/IMU_OUTPUT_ROOT/outputs/<run_id>/pointclouds/
```

## Import Settings

When opening pointcloud CSVs:

- Use `X` as X coordinate.
- Use `Y` as Y coordinate.
- Use `Z` as Z coordinate.
- Use `RSSI` as a scalar field if needed.
- Do not use `dist_mm` as a coordinate.

Coordinate meaning:

- `X` = left/right
- `Y` = vertical height
- `Z` = travel direction

## Required Views

Save screenshots outside the repo under:

```text
/PATH/TO/IMU_OUTPUT_ROOT/screenshots/
```

Required screenshots:

```text
001_no_imu_side.png
001_no_imu_top.png
002_roll_pitch_side.png
002_roll_pitch_top.png
003_heading_top.png
004_imu_interp_side.png
005_pps_side_or_failed_note.png
```

## What to Compare

### Baseline vs Roll/Pitch

Compare:

- `001_no_imu_interp`
- `002_imu_roll_pitch_interp`

Look for:

- canopy less tilted in side view
- vertical structure more realistic
- similar or improved point count
- no obvious warping

Roll/pitch helps if the canopy looks more level without distorting the row.

### Roll/Pitch vs Heading

Compare:

- `002_imu_roll_pitch_interp`
- `003_imu_roll_pitch_heading_interp`

Use top view.

Heading is suspicious if:

- row rotates oddly
- row alignment gets worse
- cloud shifts sideways
- plant windows no longer line up

Do not recommend heading unless top-view geometry clearly improves.

### Interp vs IMU Interp

Compare:

- `002_imu_roll_pitch_interp`
- `004_imu_roll_pitch_imu_interp`

If the Pico file has no `imu_time_s`, these may look the same. If `imu_time_s` exists, check whether direct IMU timing improves side-view stability.

### PPS

Inspect:

- `005_imu_roll_pitch_pps`

PPS is not ready if:

- output is empty
- many plots are missing
- point count drops heavily
- row shape is visibly broken
- logs show PPS/fusion warnings

## Notes to Record

For each screenshot, write 2-3 sentences:

- What changed?
- Did the cloud look more realistic?
- Did the row stay aligned?
- Did the canopy look less tilted?
- Did anything look distorted?

Paste final notes into `docs/research/IMU_TEST_RESULTS_TEMPLATE.md` or the final report.
