# AGENTS.md

## Project context

This repository contains the central LiDAR analysis pipeline for a field phenotyping cart.

The pipeline processes synchronized:
- SICK multi-beam LiDAR CSV data
- Pico encoder / IMU CSV data
- optional marker CSV files
- cart calibration files
- experiment YAML configs

Coordinate convention:
- X = left / right across row
- Y = vertical height
- Z = travel direction along row

Do not change coordinate conventions.

## Important files

- `lidar_analysis/pipeline_core.py`: core reconstruction, splitting, filtering, output logic
- `lidar_analysis/config.py`: analysis config dataclass and options
- `lidar_analysis/fusion.py`: time-based LiDAR/Pico fusion
- `lidar_analysis/fusion_pps.py`: PPS-based fusion
- `lidar_analysis/mark_splitting.py`: existing marker-related logic
- `lidar_analysis/orchestrator.py`: high-level orchestration
- `lidar_analysis/example_data/2026_04_28_1/`: tiny three-plant real fixture

## Development rules

Do not rewrite the whole project.

Make small, reviewable changes.

Preserve existing behavior unless the task explicitly changes it.

Do not remove existing config keys.

Do not change file naming behavior unless explicitly requested.

Do not discard RSSI or normalized RSSI scalar fields.

Keep new marker/filter/voxel logic modular. Prefer new helper modules over adding hundreds of lines to `pipeline_core.py`.

Do not modify GUI code in this repository unless explicitly requested.

## Testing expectations

At minimum, run:

```bash
python3 -m py_compile lidar_analysis/*.py
