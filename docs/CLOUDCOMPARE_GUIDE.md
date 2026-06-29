# CloudCompare Guide

This guide explains how to inspect output CSV point clouds from the repository in CloudCompare. The output column names are based on `lidar_analysis/pipeline_core.py::analyze_plot` and `lidar_analysis/pipeline_core.py::Plot.write`.

## Which Files To Open

Open point-cloud CSV files written under:

```text
OUTPUT_DIR/pointclouds/
```

The active runner creates this folder in `lidar_analysis/central_runner.py::run_experiment_date`.

Do not open `OUTPUT_DIR/results.csv` as a point cloud. That file is a trait table written by `central_runner.append_trait_rows`.

## Expected Point-Cloud CSV Columns

Typical output columns:

```text
X, Y, Z, RSSI, source_index, time_s, phi, theta, dist_mm, range_m,
encoder, roll_deg, pitch_deg, yaw_deg, beam_id
```

Optional scalar columns:

```text
rssi_norm
rssi_norm_bilateral
```

Other scalar columns can exist if point-cloud operations add them. `Plot.write` writes all columns from `AnalysisTarget.current_points` and divides only `X`, `Y`, `Z` by 1000 so they are in meters.

## Import As CSV / ASCII

In CloudCompare:

1. Open the CSV file from `OUTPUT_DIR/pointclouds/`.
2. Use the ASCII/CSV import dialog.
3. Set separator to comma.
4. Tell CloudCompare the first row is a header or skip one header line.
5. Assign columns:

| CSV column | CloudCompare role |
| --- | --- |
| `X` | X coordinate |
| `Y` | Y coordinate |
| `Z` | Z coordinate |
| `RSSI` | scalar field |
| `rssi_norm` | scalar field, if present |
| `rssi_norm_bilateral` | scalar field, if present |
| `source_index` | scalar field or skip |
| `time_s` | scalar field or skip |
| `phi` | scalar field or skip |
| `theta` | scalar field or skip |
| `dist_mm` | scalar field or skip |
| `range_m` | scalar field or skip |
| `encoder` | scalar field or skip |
| `roll_deg` | scalar field or skip |
| `pitch_deg` | scalar field or skip |
| `yaw_deg` | scalar field or skip |
| `beam_id` | scalar field or skip |

## Color By Scalar Field

After import:

1. Select the cloud in the DB tree.
2. In properties, choose active scalar field such as `RSSI`, `rssi_norm`, `dist_mm`, `range_m`, or `beam_id`.
3. Enable scalar field color display.
4. Adjust scalar range to highlight low/high values.

Use `RSSI` for raw signal strength. Use `rssi_norm` only when `normalize_rssi: true` added that column in `apply_rssi_normalization_after_masks`.

## Compare Baseline Vs Filtered Outputs

Recommended workflow:

1. Run baseline into one output folder, for example `runs/001_baseline/output`.
2. Run filtered config into a second folder, for example `runs/014_ops_on/output`.
3. Open matching point-cloud CSVs from both folders.
4. Rename clouds in CloudCompare to include run IDs.
5. Color one cloud by a constant color and the other by another constant color, or color both by `RSSI`.
6. Toggle visibility to inspect removed points.

Useful comparisons:

| Experiment | What to look for |
| --- | --- |
| Row width change | X spread should get narrower/wider. |
| `max_y_u` height filter | Top canopy points should disappear when max Y is low. |
| `x_min_u` filter | Points near X=0 should disappear. |
| RSSI filter | Low-`RSSI` points should disappear. |
| `sor_filter` pointcloud op | Isolated outlier points should be reduced. |
| Marker splitting | Each plant/plot CSV should occupy its marker Z window. |

## Inspect Height, Density, And Removed Points

Height:

- `Y` is vertical height by repository convention.
- Compare visual top of the cloud to `height_m` in `results.csv` when `run_height: true`.
- `height_m` is computed by `pipeline_core.height_from_world_y`.

Density:

- `point_density_m2` in `results.csv` is calculated in `pipeline_core.analyze_plot` from point count divided by estimated plot area.
- In CloudCompare, visually inspect whether high-density regions correspond to plant/canopy structure.

Removed points:

- Load baseline and filtered clouds together.
- Use different colors.
- Toggle visibility or use scalar coloring to understand what changed.

## Save Screenshots

For documentation:

1. Set a consistent camera angle.
2. Show the DB tree with cloud names if useful.
3. Color by the scalar field being discussed.
4. Save a screenshot with a run ID in the filename, for example:

```text
001_baseline_scan_side.png
014_sor_filter_scan_side.png
```

CloudCompare screenshot commands are GUI actions, not repository code, so exact menu names may vary by CloudCompare version.

## Export CloudCompare Sessions

After loading and arranging clouds, save a CloudCompare `.bin` session so the view can be reopened later.

Suggested naming:

```text
cloudcompare_sessions/001_vs_014_baseline_vs_filtered.bin
```

This is a CloudCompare feature, not repository code.

## Common Import Mistakes

| Mistake | Symptom | Fix |
| --- | --- | --- |
| Header row not skipped | CloudCompare may reject the file or create invalid points. | Mark first line as header or skip one line. |
| Separator not set to comma | All values appear as one column. | Set separator to comma. |
| Wrong coordinate assignment | Cloud appears flat, sideways, or scrambled. | Assign `X`, `Y`, `Z` exactly. |
| Using `dist_mm` as Z | Cloud geometry follows range rather than reconstructed travel direction. | Use CSV `Z` column for Z coordinate. |
| Treating `results.csv` as point cloud | Import does not make spatial sense. | Open files under `OUTPUT_DIR/pointclouds/`. |
| Forgetting units | Measurements seem 1000x too large/small. | Output `X`, `Y`, `Z` from `Plot.write` are meters. |

