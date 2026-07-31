# SLIM IMU Testing Instructions

This package lets SLIM run the IMU comparison workflow without sharing field data with AI.

Do not copy raw LiDAR/Pico CSV files into this repository. Keep field data and all generated outputs outside the repo.

## Files in This Package

- `runs/imu_tests/configs/001_no_imu_interp.yaml`
- `runs/imu_tests/configs/002_imu_roll_pitch_interp.yaml`
- `runs/imu_tests/configs/003_imu_roll_pitch_heading_interp.yaml`
- `runs/imu_tests/configs/004_imu_roll_pitch_imu_interp.yaml`
- `runs/imu_tests/configs/005_imu_roll_pitch_pps.yaml`
- `scripts/run_imu_tests.sh`
- `scripts/compare_imu_runs.py`
- `docs/research/IMU_TEST_RESULTS_TEMPLATE.md`
- `docs/research/CLOUDCOMPARE_CHECKLIST.md`

## Inputs Required on SLIM

The input folder must stay outside this repo and should contain:

```text
/PATH/TO/FIELD_INPUT/
  *_lidar.csv
  *_pico.csv
  cart_config.yaml
  experiment_config.yaml or marker/config files required by the selected experiment
```

`central_runner` requires `cart_config.yaml` directly inside the input folder.

If `cart_config.yaml` is missing, copy it safely without overwriting:

```bash
INPUT="/PATH/TO/FIELD_INPUT"
SOURCE_CART_CONFIG="/PATH/TO/CART_CONFIG/cart_config.yaml"

if [ -e "$INPUT/cart_config.yaml" ]; then
  echo "cart_config.yaml already exists; not overwriting: $INPUT/cart_config.yaml"
else
  cp "$SOURCE_CART_CONFIG" "$INPUT/cart_config.yaml"
fi
```

## Output Location

Use an output folder outside the repo:

```text
/PATH/TO/IMU_OUTPUT_ROOT
```

The runner will create:

```text
/PATH/TO/IMU_OUTPUT_ROOT/
  outputs/
  working/
  logs/
  screenshots/
  imu_all_results.csv
  imu_comparison_summary.csv
```

Do not commit anything from `/PATH/TO/IMU_OUTPUT_ROOT`.

## Run the Full IMU Test Set

From the repo root on SLIM:

```bash
cd /PATH/TO/lidar_analysis

scripts/run_imu_tests.sh \
  /PATH/TO/FIELD_INPUT \
  /PATH/TO/IMU_OUTPUT_ROOT \
  EXPERIMENT_NAME \
  YYYY_MM_DD
```

The script runs five configurations:

| Run | Fusion | IMU | Heading | Purpose |
|---|---|---:|---:|---|
| `001_no_imu_interp` | `interp` | false | false | Baseline |
| `002_imu_roll_pitch_interp` | `interp` | true | false | Roll/pitch correction |
| `003_imu_roll_pitch_heading_interp` | `interp` | true | true | Heading/yaw effect |
| `004_imu_roll_pitch_imu_interp` | `imu_interp` | true | false | IMU timestamp alignment |
| `005_imu_roll_pitch_pps` | `pps` | true | false | PPS reliability |

Each run writes its own log:

```text
/PATH/TO/IMU_OUTPUT_ROOT/logs/<run_id>.log
```

## Run Comparison Only

If the five runs already exist:

```bash
python3 scripts/compare_imu_runs.py --run-root /PATH/TO/IMU_OUTPUT_ROOT
```

This writes:

```text
/PATH/TO/IMU_OUTPUT_ROOT/imu_all_results.csv
/PATH/TO/IMU_OUTPUT_ROOT/imu_comparison_summary.csv
```

The script runs offline and only reads local result files.

## What to Check After Running

1. Confirm each run has `results.csv`.
2. Confirm each run has `pointclouds/*.csv`.
3. Open `/PATH/TO/IMU_OUTPUT_ROOT/imu_comparison_summary.csv`.
4. Copy summary values manually into `docs/research/IMU_TEST_RESULTS_TEMPLATE.md` or a separate report.
5. Use CloudCompare with `docs/research/CLOUDCOMPARE_CHECKLIST.md`.

## Rules

- Do not put raw CSVs in the repo.
- Do not put generated pointcloud CSVs in the repo.
- Do not put generated result CSVs in the repo.
- Do not put logs in the repo.
- Only commit reusable configs, scripts, and blank documentation templates.
