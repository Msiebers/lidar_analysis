# IMU Test Results Template

Summary:

```text
Paste a short manager summary here.
Example:
I tested the same LiDAR/Pico scan using five controlled configurations: no IMU, roll/pitch IMU, roll/pitch plus heading, IMU interpolation, and PPS fusion. Based on numeric results and CloudCompare inspection, the safest current recommendation is ______. The main limitation is ______, so the next test should be ______.
```

## 1. Purpose

This test evaluates whether IMU correction improves LiDAR point-cloud reconstruction and plant trait outputs.

## 2. Data Used

- Input folder: `/PATH/TO/FIELD_INPUT`
- LiDAR file or scan pattern:
- Pico file or scan pattern:
- Cart config:
- Experiment config:
- Scan condition:
- Notes about terrain:

## 3. Test Configurations

| Run | Fusion | use_imu | use_heading | Purpose |
|---|---|---:|---:|---|
| `001_no_imu_interp` | `interp` | false | false | Baseline, no IMU correction |
| `002_imu_roll_pitch_interp` | `interp` | true | false | Roll/pitch correction |
| `003_imu_roll_pitch_heading_interp` | `interp` | true | true | Roll/pitch plus heading/yaw |
| `004_imu_roll_pitch_imu_interp` | `imu_interp` | true | false | IMU-specific timestamp path |
| `005_imu_roll_pitch_pps` | `pps` | true | false | PPS-based fusion reliability |

## 4. Numeric Results

Paste values from:

```text
/PATH/TO/IMU_OUTPUT_ROOT/imu_comparison_summary.csv
```

| Run | Results rows | Pointcloud CSV files | Total points | Mean height m | Median height m | Min height m | Max height m | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `001_no_imu_interp` |  |  |  |  |  |  |  |  |
| `002_imu_roll_pitch_interp` |  |  |  |  |  |  |  |  |
| `003_imu_roll_pitch_heading_interp` |  |  |  |  |  |  |  |  |
| `004_imu_roll_pitch_imu_interp` |  |  |  |  |  |  |  |  |
| `005_imu_roll_pitch_pps` |  |  |  |  |  |  |  |  |

## 5. CloudCompare Observations

Screenshot folder:

```text
/PATH/TO/IMU_OUTPUT_ROOT/screenshots
```

| Screenshot | Observation | Better / worse / same |
|---|---|---|
| `001_no_imu_side.png` |  |  |
| `001_no_imu_top.png` |  |  |
| `002_roll_pitch_side.png` |  |  |
| `002_roll_pitch_top.png` |  |  |
| `003_heading_top.png` |  |  |
| `004_imu_interp_side.png` |  |  |
| `005_pps_side_or_failed_note.png` |  |  |

## 6. Findings

Roll/pitch:

```text
Paste findings here.
```

Heading/yaw:

```text
Paste findings here.
```

IMU interpolation:

```text
Paste findings here.
```

PPS:

```text
Paste findings here.
```

## 7. Recommendation

Recommended setting for now:

```yaml
fusion_method:
use_imu:
use_heading:
```

Reason:

```text
Paste recommendation rationale here.
```

## 8. Limitations

- Number of scans tested:
- Terrain condition:
- Calibration uncertainty:
- Timestamp/PPS uncertainty:
- CloudCompare inspection completed:
- Known validation object available:

## 9. Next Tests

- Uneven-ground scan:
- Repeated scan:
- Calibration sensitivity:
- Known-height validation object:
- Additional crop/species/date:
