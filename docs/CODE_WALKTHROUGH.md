# Code Walkthrough

Start with these files:

| File | Responsibility |
| --- | --- |
| `lidar_analysis/central_runner.py` | Main local CLI, config resolution, scan-pair discovery, results CSV writing |
| `lidar_analysis/pipeline_stages.py` | Stage wrapper that calls the core processor |
| `lidar_analysis/pipeline_core.py` | Fusion, reconstruction, filtering, splitting, trait extraction, output writing |
| `lidar_analysis/config.py` | `AnalysisConfig` dataclass, defaults, RSSI mode validation, deprecated-key mapping |
| `lidar_analysis/pointcloud_ops.py` | Ordered point-cloud filters and trait operations |
| `lidar_analysis/mark_splitting.py` | Marker-file discovery and marker-to-window conversion |

## Main Execution Path

```text
central_runner.main
  -> parse_args
  -> normalize_request
  -> resolve_config_path
  -> _load_yaml
  -> extract_analysis_cfg
  -> run_experiment_date
      -> discover_scan_pairs
      -> read_calibration_from_cart_config
      -> build_config
      -> ensure_results_csv
      -> DEFAULT_STAGES
          -> ProcessScanStage.run
              -> pipeline_core.process_scan
                  -> load_files_from_paths
                  -> choose_fusion_method
                  -> reconstruct_world_points
                  -> apply_global_filters
                  -> apply_rssi_normalization_after_masks
                  -> apply_rssi_filter
                  -> build_plot_ranges or build_mark_segments
                  -> analyze_plot
                  -> write_scan_outputs
      -> append_trait_rows
```

## Runner Layer

`central_runner.parse_args` defines the verified CLI:

```text
--experiment, --date, --input, --working, --output,
--config, --cart-id, --force, --fusion
```

`central_runner.run_experiment_date` requires `cart_config.yaml`, reads scan pairs, builds `AnalysisConfig`, creates `OUTPUT_DIR/results.csv`, and runs `pipeline_stages.DEFAULT_STAGES`.

`run_experiment_date.py` is a compatibility wrapper that imports `central_runner` and calls `central_runner.run_experiment_date` when available.

## Core Pipeline

`pipeline_core.process_scan` is the primary scientific processing function. It:

1. Loads LiDAR and Pico CSVs with `load_files_from_paths`.
2. Selects fusion through `choose_fusion_method`.
3. Reconstructs world points with `reconstruct_world_points`.
4. Applies global filters with `apply_global_filters`.
5. Applies RSSI normalization/filtering.
6. Splits into targets by distance or markers.
7. Calls `analyze_plot` for traits and point-cloud operations.
8. Calls `write_scan_outputs` for CSV outputs.

Fusion implementations:

| Method | Function |
| --- | --- |
| `interp` | `fusion.fuse_by_time` |
| `imu_interp` | `fusion_imu_interp.fuse_by_imu_interp` |
| `pps` | `fusion_pps.fuse_by_pps` |

## Outputs And Schemas

`pipeline_core.Plot.write` writes point-cloud CSVs with at least:

```text
X, Y, Z, RSSI
```

Coordinates are converted from millimeters to meters before writing. Additional scalar columns may appear when `AnalysisTarget.current_points` includes them.

`central_runner.phenotype_columns` controls `results.csv` columns. It adds optional columns when `run_height`, `run_lai`, `topology_trait`, `slice_structure_trait`, or voxel operations are enabled.

## Developer Notes

| Area | Caution |
| --- | --- |
| Coordinates | Preserve `X` left/right, `Y` height, `Z` travel direction. |
| Units | `pipeline_core` often uses millimeters internally; point-cloud CSV output uses meters. |
| Config | Add new config fields to `AnalysisConfig`, then wire them through `central_runner.build_config`. |
| Outputs | Keep `X`, `Y`, `Z`, `RSSI` available for CloudCompare workflows. |
| Marker logic | Prefer `central_runner.resolve_splitting_style` and `resolve_buffer_u` for new behavior. |
| Point-cloud operations | Add operations through `pointcloud_ops._SUPPORTED_OPS` and `apply_pointcloud_ops`. |

## Related Modules

| File | Purpose |
| --- | --- |
| `lidar_analysis/orchestrator.py` | Higher-level staged workflow and output packaging |
| `lidar_analysis/central_watcher.py` | Polling/rerun workflow for mounted data paths |
| `lidar_analysis/local_run.py` | Local wrapper around orchestrator processing |
| `lidar_analysis/lai/lai.py` and `lidar_analysis/lai/fad.py` | LAI/FAD-related trait helpers |
| `lidar_analysis/topology/stand_count.py` | Topology stand-count trait implementation |
| `scripts/plot_pcl_summary.py` | Post-run summary plotting; imports `matplotlib` |
