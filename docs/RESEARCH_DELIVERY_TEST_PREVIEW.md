# Research Delivery Test Preview

`scripts/build_research_delivery.py` builds an internal, disposable preview from existing
canonical `results.csv` files. It does not run the LiDAR pipeline, edit inputs, or copy raw
scans and point clouds.

## Safety model

- Raw experiment data and existing analysis results are read-only inputs.
- The delivery root must not overlap either input root.
- Dry-run is the default. Files are written only with `--write`.
- Every write uses a new run ID. Existing preview runs are never overwritten.
- Output is built in a temporary directory and renamed into place only after completion.
- Only `points`, `point_density_m2`, and `stand_topo_per_m` are currently accepted for
  ranking. Geometry metrics must not be enabled until they are scientifically validated.

## Current interpretation of incomplete dates

Every `YYYY_MM_DD` directory found in either input root appears in the date index. A date
without a readable, non-empty canonical `results.csv` is marked `incomplete`; the builder
does not run or rank that date. For the currently observed MeadowFescue data, this is the
expected treatment of `2026_05_27`.

## Ranking behavior

Rankings are calculated independently for each date and metric. The cutoff count is
`ceil(eligible_rows * top_fraction)`, with at least one selected row. Ties at the cutoff
are included when `include_ties` is true. Non-finite values and rows explicitly failed by
`qc_pass` or `qc_status` are excluded. If those QC columns are absent, numeric eligibility
does not imply scientific QC approval.

Outliers are reported independently using the 1.5-IQR rule by default. They are reported
for review and are not automatically removed from rankings.

## Graphs

Graph generation is enabled by default with `generate_graphs: true`. `graph_dpi` controls
PNG resolution and must be an integer from 72 through 600; the example uses 160 DPI. Set
`generate_graphs: false` to retain the CSV/metadata preview without creating any graphs.

For every usable date and available configured metric, the preview writes a distribution
graph and a top-ranking graph under `<date>/results/graphs/`. Top-ranking graphs receive
the same selected rows, cutoff, QC filtering, and tie behavior as their corresponding
ranking CSVs. Incomplete dates and unavailable metrics do not receive placeholder graphs.

Cross-date box plots are written under `summary/graphs/`. They are visibly marked
`EXPLORATORY ONLY` whenever configuration fingerprints differ or are unavailable for any
usable date. The latest usable date's top-ranking graphs are copied to
`summary/latest_date_top_15_percent/graphs/`; these copies are byte-identical to their
date-level sources. `delivery_manifest.json` records `graphs_generated` and a sorted
`graph_files` inventory.

Matplotlib uses the noninteractive Agg backend. Its cache is confined to the atomic-build
staging directory and removed before the completed preview is published.

## Configuration consistency

The preview records detected historical configuration snapshots and SHA-256 fingerprints.
Historical differences or missing snapshots are reported rather than silently ignored.
Before a final dataset is produced, all dates must be rerun with one reviewed, versioned
project configuration; per-date algorithm toggles are not acceptable.

## Running

Read-only dry run:

```bash
.venv/bin/python scripts/build_research_delivery.py \
  --config lidar_analysis/example_configs/research_delivery_meadowfescue.yaml \
  --run-id meadowfescue_preview_v2_graphs
```

Write a new test preview only after reviewing the dry-run output:

```bash
.venv/bin/python scripts/build_research_delivery.py \
  --config lidar_analysis/example_configs/research_delivery_meadowfescue.yaml \
  --run-id meadowfescue_preview_v2_graphs \
  --write
```
