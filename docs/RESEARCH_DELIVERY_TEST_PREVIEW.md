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

## Folder contract (V2A)

Every generated artifact has exactly one canonical location. The contract is defined in
code in `lidar_analysis/research_delivery_layout.py`; a build fails if it produces a file
outside the contract.

    <run_id>/
    |-- README.md                          researcher guide (start here)
    |-- summary_config.yaml                delivery config used for this build
    |-- summary/
    |   |-- EXPERIMENT_SUMMARY.md          overview; links to date folders instead of copying them
    |   |-- data/combined_results.csv      all usable rows from every date, with provenance columns
    |   |-- growth/<metric>_by_date.png    cross-date box plots
    |   `-- qc/missing_metrics.csv         metrics that could not be ranked, by date
    |-- <YYYY_MM_DD>/                      same four subfolders for every date
    |   |-- results/results.csv            frozen snapshot of the canonical results (usable dates)
    |   |-- results/top_15_percent/<metric>.csv
    |   |-- graphs/<metric>_distribution.png, <metric>_top_15_percent.png
    |   |-- qc/qc_flags.csv, qc/outliers.csv   only when results QC was performed
    |   `-- metadata/source_reference.md   status, read-only input locations, inspection findings
    `-- manifest/
        |-- experiment_date_index.csv      canonical per-date provenance table
        `-- delivery_manifest.json         build identity + fingerprint inventory of every file

The ranking folder name follows `top_fraction` (for example `top_15_percent`).

### Intentional duplication

Each usable date's `results/results.csv` is a byte-identical copy of the canonical analysis
`results.csv`. This is a deliberate frozen snapshot so the delivery remains valid if the
analysis folder later changes. `experiment_date_index.csv` records the source path and
`results_sha256` so the relationship can be verified. `combined_results.csv` is a derived
experiment-wide table, not a copy.

### Removed in V2A

The following generated redundancy no longer exists:

- `summary/latest_date_top_15_percent/` (byte-identical copies of the latest date's ranking
  CSVs and graphs). `EXPERIMENT_SUMMARY.md` links to the latest date's folder instead.
- `<date>/metadata/date_status.json` (duplicate of the date index row).
- Full per-date records inside `delivery_manifest.json` (duplicate of the date index).
- `<date>/source/` and `<date>/pointclouds/` (reference-only README and inventory files).
  Their information is in `metadata/source_reference.md` and the date index
  (`pointcloud_dir` plus point-cloud file counts).

Old locations that moved: `delivery_manifest.json` -> `manifest/`,
`summary/experiment_date_index.csv` -> `manifest/`, `summary/combined_results.csv` ->
`summary/data/`, `summary/missing_metrics.csv` -> `summary/qc/`, `summary/graphs/` ->
`summary/growth/`, and `<date>/results/{graphs,qc,outliers}` -> `<date>/graphs/` and
`<date>/qc/`.

### Result row identity

A result row's unique key is `experiment`, `date`, `scan_name`, `scan_number`, `plot`,
`side` — the same identity `central_runner` uses for `results.csv` itself
(`RESULT_UNIQUE_FIELDS` in `research_delivery.py`, kept in sync with
`central_runner._RESULT_UNIQUE_FIELDS` by a dedicated test). `target_type` and
`target_id` are carried through for traceability but are not part of the key.
There is no `row` or `scan_id` column in the current schema; a field scan's `row`
concept is expressed today through `plot` plus `side` (`left`/`right`/`both`/`none`).

### Traceability

experiment -> date -> `<date>/results/results.csv` -> `scan_name` / `scan_number` / `plot` / `side` ->
`results_path` + `results_sha256` -> `raw_date_dir`, `source_dir`, `pointcloud_dir`.
In `combined_results.csv`, `_delivery_results_path` is relative to the delivery folder and
`_source_results_path` is the absolute analysis input. Generated-to-generated references
are relative; absolute paths are used only for read-only inputs.

### Manifest (schema version 2)

`delivery_manifest.json` contains: schema version, experiment, `run_id`, `created_at_utc`,
config SHA-256, latest usable date, `date_count`, a lightweight `dates` list (date and
status only), `date_index` (relative path to the date index), safety flags,
`graph_files`, and `artifacts` (every other file's relative path, contract role, and
SHA-256).

`run_id` and `created_at_utc` appear only in the manifest. Two builds from the same inputs
and config differ only in `manifest/delivery_manifest.json`.

## Incomplete dates

Every `YYYY_MM_DD` directory found in either input root appears in the date index unless a
`dates:` filter is set. A date without a readable, non-empty canonical `results.csv` is
marked `incomplete`; the builder does not run or rank that date. Its `results/`, `graphs/`,
and `qc/` folders exist but stay empty, so no file implies that QC was performed. Its status,
reason, and inspection findings are recorded in `metadata/source_reference.md` and the date
index. For the currently observed MeadowFescue data, this is the expected treatment of
`2026_05_27`.

## Optional date filter

`dates:` limits a build to specific dates. Quote each entry, because unquoted YAML reads
`2026_05_14` as a number. Unknown or malformed dates are rejected. When `dates:` is not set,
all discovered dates are included and the config fingerprint is unchanged.

    dates:
      - "2026_05_14"
      - "2026_05_28"

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
graph and a top-ranking graph under `<date>/graphs/`. Top-ranking graphs receive the same
selected rows, cutoff, QC filtering, and tie behavior as their corresponding ranking CSVs.
Incomplete dates and unavailable metrics do not receive placeholder graphs.

Cross-date box plots are written under `summary/growth/`. They are visibly marked
`EXPLORATORY ONLY` whenever configuration fingerprints differ or are unavailable for any
usable date.

Matplotlib uses the noninteractive Agg backend. Its cache is confined to the atomic-build
staging directory and removed before the completed preview is published.

## Configuration consistency

The preview records detected historical configuration snapshots and SHA-256 fingerprints.
Historical differences or missing snapshots are reported rather than silently ignored.
Before a final dataset is produced, all dates must be rerun with one reviewed, versioned
project configuration; per-date algorithm toggles are not acceptable.

## Running

Read-only dry run:

    .venv/bin/python scripts/build_research_delivery.py \
      --config lidar_analysis/example_configs/research_delivery_meadowfescue.yaml \
      --run-id meadowfescue_preview_example

Write a new test preview only after reviewing the dry-run output:

    .venv/bin/python scripts/build_research_delivery.py \
      --config lidar_analysis/example_configs/research_delivery_meadowfescue.yaml \
      --run-id meadowfescue_preview_example \
      --write
