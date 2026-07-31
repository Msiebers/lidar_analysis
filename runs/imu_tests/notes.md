# IMU Test Notes

Task goal: compare the same LiDAR/Pico scan across controlled IMU/fusion settings to see whether IMU correction improves reconstructed point clouds and trait outputs.

Selected scan:
- Use a SLIM field-data input folder outside this repo.
- Do not copy raw LiDAR/Pico CSVs into the repository.
- Do not write analysis outputs, logs, or generated result CSVs into the repository.

All runs use the same input scan. Only `fusion_method`, `use_imu`, and `use_heading` should change between controlled configs.

SLIM field-data target for real evidence:
- `/PATH/TO/FIELD_INPUT`

## Numeric Comparison Table

Run | Fusion | IMU | Heading | Results rows | Pointcloud files | Mean height | Point density | Notes
--- | --- | --- | --- | ---: | ---: | ---: | ---: | ---
001_no_imu_interp | interp | false | false | pending | pending | pending | pending | baseline
002_imu_roll_pitch_interp | interp | true | false | pending | pending | pending | pending | roll/pitch
003_imu_roll_pitch_heading_interp | interp | true | true | pending | pending | pending | pending | heading/yaw
004_imu_roll_pitch_imu_interp | imu_interp | true | false | pending | pending | pending | pending | IMU timestamp path
005_imu_roll_pitch_pps | pps | true | false | pending | pending | pending | pending | PPS reliability

## CloudCompare Notes

Screenshots have not been captured in this environment. Required screenshot names are listed in `docs/research/IMU_TEST_RESULTS.md`.
