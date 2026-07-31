# IMU Test Results

Summary:
This file is now a no-data report template. Generated CSVs, copied input data, logs, and local numeric smoke-test results were removed from the repository. The controlled IMU comparison should be run on SLIM with outputs written outside the repo, then summarized here only after deciding what result tables are appropriate to commit.

## 1. Purpose

This test evaluates whether IMU correction improves LiDAR point-cloud reconstruction and plant trait outputs.

## 2. Data Used

Target field-data folder for real evidence:

```text
/PATH/TO/FIELD_INPUT
```

Keep raw CSVs, copied input data, logs, generated pointclouds, and generated results outside the repo.

## 3. Test Configurations

| Run | Fusion | use_imu | use_heading | Purpose |
|---|---|---:|---:|---|
| `001_no_imu_interp` | `interp` | false | false | Baseline, no IMU correction |
| `002_imu_roll_pitch_interp` | `interp` | true | false | Roll/pitch correction |
| `003_imu_roll_pitch_heading_interp` | `interp` | true | true | Roll/pitch plus heading/yaw |
| `004_imu_roll_pitch_imu_interp` | `imu_interp` | true | false | IMU-specific timestamp path |
| `005_imu_roll_pitch_pps` | `pps` | true | false | PPS-based fusion reliability |

## 4. Commands Run

Baseline pattern:

```bash
python3 -m lidar_analysis.central_runner \
  --experiment IMU_LOCAL_SMOKE \
  --date 2026_04_28_1 \
  --input /PATH/TO/FIELD_INPUT \
  --working /PATH/TO/IMU_OUTPUT_ROOT/working/001_no_imu_interp \
  --output /PATH/TO/IMU_OUTPUT_ROOT/outputs/001_no_imu_interp \
  --config runs/imu_tests/configs/001_no_imu_interp.yaml \
  --fusion interp \
  --force
```

The other runs used the same input and changed only output folder, config file, working folder, and `--fusion`.

Logs:

- `runs/imu_tests/logs/001_no_imu_interp.log`
- `runs/imu_tests/logs/002_imu_roll_pitch_interp.log`
- `runs/imu_tests/logs/003_imu_roll_pitch_heading_interp.log`
- `runs/imu_tests/logs/004_imu_roll_pitch_imu_interp.log`
- `runs/imu_tests/logs/005_imu_roll_pitch_pps.log`

## 5. Numeric Results

Do not commit generated result CSVs or copied input data to this repo.

Write run outputs outside the repo, for example:

```text
/PATH/TO/IMU_OUTPUT_ROOT/outputs/
/PATH/TO/IMU_OUTPUT_ROOT/working/
```

After the SLIM runs finish, summarize only the approved high-level table here.

| Run | Results rows | Pointcloud CSV files | Total points | Mean height m | Median height m | Min height m | Max height m |
|---|---:|---:|---:|---:|---:|---:|---:|
| `001_no_imu_interp` | pending | pending | pending | pending | pending | pending | pending |
| `002_imu_roll_pitch_interp` | pending | pending | pending | pending | pending | pending | pending |
| `003_imu_roll_pitch_heading_interp` | pending | pending | pending | pending | pending | pending | pending |
| `004_imu_roll_pitch_imu_interp` | pending | pending | pending | pending | pending | pending | pending |
| `005_imu_roll_pitch_pps` | pending | pending | pending | pending | pending | pending | pending |

## 6. Log Notes

Run logs should be stored outside the repo with the outputs. If the Pico file lacks optional `imu_time_s`, `imu_interp` is expected to fall back to Pico `time_s`; see `lidar_analysis/fusion_imu_interp.py:104-132`.

## 7. CloudCompare Observations

CloudCompare screenshots were not captured in this environment.

Required screenshot checklist for SLIM:

- `runs/imu_tests/screenshots/001_no_imu_side.png`
- `runs/imu_tests/screenshots/001_no_imu_top.png`
- `runs/imu_tests/screenshots/002_roll_pitch_side.png`
- `runs/imu_tests/screenshots/002_roll_pitch_top.png`
- `runs/imu_tests/screenshots/003_heading_top.png`
- `runs/imu_tests/screenshots/004_imu_interp_side.png`
- `runs/imu_tests/screenshots/005_pps_side_or_failed_note.png`

CloudCompare import reminder:

- `X` = X coordinate
- `Y` = vertical height
- `Z` = travel direction
- `RSSI` = scalar field
- Do not use `dist_mm` as a coordinate

## 8. Findings

Pending SLIM field-data runs.

Evaluate:

- whether roll/pitch changes height or point count materially
- whether heading/yaw improves or worsens row alignment
- whether `imu_interp` differs from `interp`
- whether PPS produces complete and visually sane point clouds

## 9. Recommendation

For production field analysis today, use the conservative baseline unless CloudCompare inspection on real SLIM data proves IMU correction helps:

```yaml
fusion_method: interp
use_imu: false
use_heading: false
```

For the next controlled field test, compare this against:

```yaml
fusion_method: interp
use_imu: true
use_heading: false
```

Avoid `use_heading: true` until top-view row alignment is verified.

Avoid treating PPS as validated from this smoke test alone. PPS needs a real scan with reliable LiDAR/Pico PPS columns and visual review.

## 10. Limitations

- Generated local smoke-test CSVs and logs were removed from the repo.
- The real MeadowFescue SLIM field dataset still needs to be run with outputs outside the repo.
- No CloudCompare screenshots were captured.
- If the selected Pico file lacks optional `imu_time_s`, `imu_interp` cannot prove direct IMU timestamp behavior.

## 11. Next Tests

1. Repeat the same five configs on `/PATH/TO/FIELD_INPUT`.
2. Capture side/top CloudCompare screenshots for each run.
3. Test an uneven-ground scan where roll/pitch correction should matter more.
4. Repeat one stable scan and one uneven scan.
5. Include a known-height validation object if available.
6. Confirm whether the SLIM Pico logger writes `imu_time_s`; if not, `imu_interp` will not differ from ordinary `interp`.
