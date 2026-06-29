# CloudCompare

Use CloudCompare to inspect point-cloud CSVs written by `pipeline_core.Plot.write`.

## Files To Open

Open:

```text
OUTPUT_DIR/pointclouds/*.csv
```

Do not use these as primary point clouds:

| File | Reason |
| --- | --- |
| `OUTPUT_DIR/results.csv` | Trait table, not a point cloud |
| `*_marker_reference_points.csv` | Marker reference points, not full target clouds |
| `*_topology_objects.csv` | Diagnostic object points, not full target clouds |

## CSV Columns

`pipeline_core.Plot.write` writes at least:

| CSV column | CloudCompare role |
| --- | --- |
| `X` | X coordinate |
| `Y` | Y coordinate |
| `Z` | Z coordinate |
| `RSSI` | Scalar field |

Coordinates are written in meters. Optional scalar fields may include normalized RSSI or point-cloud operation outputs.

## Import Steps

1. Open CloudCompare.
2. Drag a point-cloud CSV into the window or use `File > Open`.
3. Choose ASCII/CSV import.
4. Set separator to comma.
5. Use the first row as headers or skip one header row.
6. Assign columns:
   - `X` -> X
   - `Y` -> Y
   - `Z` -> Z
   - `RSSI` and other non-coordinate columns -> scalar fields
7. Confirm the cloud loads with `Y` as vertical height and `Z` as travel direction.

## Scalar Coloring

To color by RSSI or another scalar field:

1. Select the cloud in the DB tree.
2. In properties, choose the active scalar field, such as `RSSI`.
3. Enable scalar-field color display.
4. Adjust the displayed scalar range if needed.

## Comparing Baseline And Filtered Outputs

1. Load the baseline run CSV and the filtered run CSV.
2. Rename the entities with run IDs, such as `001_baseline` and `008_rssi_high`.
3. Toggle visibility to compare shape, height, density, and missing regions.
4. Use the same camera angle for screenshots.
5. Save CloudCompare sessions as `.bin` files when preserving comparisons.

Recommended screenshot names:

```text
001_baseline_rssi.png
008_rssi_high_comparison.png
```

## Common Import Mistakes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| One text column appears | Separator was not set to comma | Re-import with comma separator |
| Cloud is flat or sideways | Coordinate columns were assigned incorrectly | Map `X`, `Y`, and `Z` exactly by name |
| Point count looks like traits, not points | `results.csv` was opened | Open files from `OUTPUT_DIR/pointclouds/` |
| Colors do not show RSSI | `RSSI` was not imported as a scalar field | Re-import or set `RSSI` as scalar |
