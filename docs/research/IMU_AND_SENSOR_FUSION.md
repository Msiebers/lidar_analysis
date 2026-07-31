# IMU and Sensor Fusion

## What the Pico Records

The Pico firmware records encoder count, timestamps, roll, pitch, yaw, IMU timestamp, and PPS. In `encoder_imu_c`, the serial header is printed by `src/main.cpp:314`:

```text
TS_US,ENC,ROLL_DEG,PITCH_DEG,YAW_DEG,IMU_TS_US,PPS
```

`lidar_analysis` expects the Pico CSV columns in `lidar_analysis/pipeline_core.py:411-419`:

```text
time_s,count,roll_deg,pitch_deg,yaw_deg,pps
```

Optional:

```text
imu_time_s
```

## How `lidar_analysis` Uses the Pico File

The paired LiDAR/Pico loader is `load_files_from_paths()` in `lidar_analysis/pipeline_core.py:400-422`.

LiDAR CSV columns:

```text
time_s,phi,theta,dist,rssi,pps_pi
```

Pico CSV columns:

```text
time_s,count,roll_deg,pitch_deg,yaw_deg,pps
```

The fusion output contract is documented in `choose_fusion_method()` at `lidar_analysis/pipeline_core.py:569-571`:

```text
[time_s, phi, theta, dist_mm, rssi, encoder, roll_deg, pitch_deg, yaw_deg]
```

## Fusion Methods

### `interp`

`fusion_method=interp` calls `fuse_by_time()` in `lidar_analysis/pipeline_core.py:582-589`. `fuse_by_time()` interpolates Pico encoder, roll, pitch, and yaw onto LiDAR `time_s`; see `lidar_analysis/fusion.py:38-99`.

### `imu_interp`

`fusion_method=imu_interp` calls `fuse_by_imu_interp()` in `lidar_analysis/pipeline_core.py:590-597`.

`fuse_by_imu_interp()` uses `imu_time_s` for roll/pitch/yaw if it is present and meaningfully different from Pico `time_s`; otherwise it falls back to Pico `time_s`. The timestamp choice is in `lidar_analysis/fusion_imu_interp.py:104-132`, and the direct interpolation behavior is in `lidar_analysis/fusion_imu_interp.py:213-299`.

### `pps`

`fusion_method=pps` calls `fuse_by_pps()` in `lidar_analysis/pipeline_core.py:573-581`. PPS fusion expects LiDAR PPS in column 5 and Pico PPS in column 5. Its input and output assumptions are documented in `lidar_analysis/fusion_pps.py:375-405`.

## IMU Correction

IMU data being present does not automatically mean IMU correction is applied.

The actual roll/pitch correction switch is `use_imu`, defined in `lidar_analysis/config.py:28` and loaded from YAML in `lidar_analysis/central_runner.py:344`.

Roll and pitch are applied during reconstruction in `reconstruct_world_points()`:

- fused roll/pitch/yaw columns are read in `lidar_analysis/pipeline_core.py:645-647`
- `cfg.use_imu` controls roll/pitch correction in `lidar_analysis/pipeline_core.py:675-689`
- `roll_sign` and `pitch_sign` are applied in `lidar_analysis/pipeline_core.py:688-689`

## Heading / Yaw

The heading switch is `use_heading`, defined in `lidar_analysis/config.py:31` and loaded in `lidar_analysis/central_runner.py:347`.

Yaw is applied only when `cfg.use_heading` is true in `lidar_analysis/pipeline_core.py:691-694`.

## Output Columns

Generated pointcloud CSVs include:

```text
X,Y,Z,RSSI,source_index,time_s,phi,theta,dist_mm,range_m,encoder,roll_deg,pitch_deg,yaw_deg,beam_id
```

Observed during local smoke testing before generated data files were removed from the repo.

Generated `results.csv` columns in the local smoke test were:

```text
experiment,date,scan_id,row,plot,height_m,point_density_m2,plot_length_m,plot_width_m,points,lidar_scans,lidar_angles
```

## Three Different Concepts

IMU data being present means the Pico CSV has roll, pitch, yaw, and maybe `imu_time_s`.

IMU data being time-aligned means the selected fusion method has placed encoder and IMU values onto LiDAR sample times.

IMU correction actually being applied means `use_imu: true` caused roll/pitch to rotate the reconstructed points during `reconstruct_world_points()`.

## Why This Matters

IMU may help on uneven ground by reducing roll/pitch tilt in the reconstructed point cloud. It can hurt if calibration, timestamp alignment, sign convention, or heading/yaw is wrong. Heading is especially suspicious unless visually verified because it can rotate or bend the row in top view.
