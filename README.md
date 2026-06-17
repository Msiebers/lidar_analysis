# LiDAR Analysis Pipeline

This repository contains the central analysis pipeline for the field LiDAR phenotyping cart system.

The pipeline processes synchronized:

- SICK multi-beam LiDAR CSV data
- Pico encoder / IMU CSV data
- Optional marker CSV files
- Cart calibration files
- Experiment configuration files

The goal is to reconstruct field point clouds, split them into plots or plants, apply optional filtering / voxelization operations, and produce downstream analysis outputs.

## Coordinate System

The reconstructed point cloud uses the following coordinate convention:

- `X` = left / right across the row
- `Y` = vertical height
- `Z` = travel direction along the row

Encoder counts are converted into travel distance using cart calibration.

## Important Files

```text
central_runner.py          Main central runner / entry point for local processing
central_watcher.py         Watches staged data and handles processing / publishing workflow
config.py                  AnalysisConfig dataclass and configuration options
fusion.py                  Time-based LiDAR/Pico fusion
fusion_pps.py              PPS-based LiDAR/Pico fusion
local_run.py               Local processing helper
mark_splitting.py          Marker-aware splitting utilities
orchestrator.py            High-level pipeline orchestration
pipeline_core.py           Core reconstruction, filtering, splitting, and output logic
run_experiment_date.py     Run one experiment/date bundle
run_manifest.py            Manifest-based run helper
scaffold_experiments.py    Experiment scaffolding utilities
topology.py                Optional topology / trait helper code
yaml_loader.py             YAML config loading
