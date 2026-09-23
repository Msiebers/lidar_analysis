# Research Delivery V2 — Demo Walkthrough

## Build the demo folder

```bash
cd /home/slim/Documents/lidar_analysis
./.venv/bin/python3 scripts/build_research_delivery.py \
  --config lidar_analysis/example_configs/research_delivery_meadowfescue_demo.yaml \
  --run-id meadowfescue_demo_v2 \
  --write
```

Demo folder: `/home/slim/Documents/lidar_delivery_tests/MeadowFescue_2026/meadowfescue_demo_v2`

## 2-3 minute demo flow

1. Show `lidar_analysis/example_configs/research_delivery_meadowfescue_demo.yaml`. Say: a researcher picks dates, metrics, and exactly which graphs they want in plain YAML.
2. Point at the `graphs:` list. Say: this config asks for one histogram, one ranking chart, and one cross-date growth plot — out of three supported graph types.
3. Run the build command above. Say: one command builds the whole delivery folder.
4. Open the top-level demo folder. Say: every date gets the same four subfolders — results, graphs, QC, metadata.
5. Open `summary/EXPERIMENT_SUMMARY.md`. Say: this is where a researcher starts — date status, ranking method, and any scientific caveats.
6. Open `2026_05_28/graphs/point_density_m2_distribution.png`. Say: here's a per-date graph.
7. Open `2026_05_28/graphs/point_density_m2_distribution.csv` next to it. Say: every plotted point has a companion CSV with scan ID, row, plot, and outlier status.
8. Pick one row from that CSV and find the matching row in `2026_05_28/results/results.csv`. Say: any point traces straight back to the frozen results snapshot.
9. Open `2026_05_28/qc/outliers.csv`. Say: outliers are flagged with the same QC logic used for the graphs.
10. Close with: future validated metrics — height, area, volume — plug into this exact same structure; the folder contract doesn't change.

## Key files to open

- `lidar_analysis/example_configs/research_delivery_meadowfescue_demo.yaml` — the demo's researcher-editable config.
- `README.md` (demo folder root) — orientation for anyone opening the folder cold.
- `summary/EXPERIMENT_SUMMARY.md` — experiment-level overview and scientific caveats.
- `2026_05_28/graphs/point_density_m2_distribution.png` + `.csv` — a graph and its traceability companion.
- `2026_05_28/results/results.csv` — the frozen canonical snapshot the CSV traces back to.
- `2026_05_28/qc/outliers.csv` — outlier flags for the same date.
- `summary/growth/point_density_m2_by_date.png` — the cross-date growth plot (marked EXPLORATORY ONLY).
- `manifest/delivery_manifest.json` — technical provenance; usually skip in the live demo unless asked.
