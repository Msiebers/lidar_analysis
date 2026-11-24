# Time course v2 — combined observations for researchers

## Where to install

On Central, copy both files into:

```
/home/central/Documents/lidar_analysis/lidar_results/
  time_course_summary.R
  time_course_template.html
```

Replace the older v1 copies. You do **not** need to replace or modify any within-day files.

## Run

```bash
Rscript ~/Documents/lidar_analysis/lidar_results/time_course_summary.R \
  /mnt/raw_mirror/MeadowFescue_2026 \
  --name MeadowFescue_26
```

The input is the most recent cleaned `/mnt/raw_mirror/results/MeadowFescue_26/within_day/results.csv`. To incorporate newly processed dated results, run `with_day MeadowFescue_2026 MeadowFescue_26` first, then run the time-course script.

## Files generated

```
/mnt/raw_mirror/results/MeadowFescue_26/
├── groundtruth/                     # NEVER modified by time_course
├── within_day/
│   ├── index.html                   # read-only by time_course
│   └── results.csv                  # read-only by time_course
└── time_course/
    ├── index.html                   # interactive report, fully self-contained
    ├── results.csv                  # ALL original cleaned LiDAR observations, all dates
    └── changes.csv                  # DERIVED paired consecutive-date changes
```

**`time_course/results.csv` is now the main research dataset**, not the changes table. It contains every row and every curated measurement column from `within_day/results.csv`, with `day_of_year` and `measurement_number` added. The rows are chronologically ordered, then by field `row` and `plant` or `plot`.

Each row means **one LiDAR-measured plant or plot on one collection date**. For example, the same plant appears in multiple rows as dates increase. This is standard long/tidy format: collaborators can run regressions, mixed models, growth curves, filtering, and their own figures directly in R, Python, Excel, etc. Missing dates are simply absent for that plant, not filled or imputed.

`time_course/changes.csv` is retained separately for optional growth-rate analysis. It contains `date_start`, `date_end`, `doy_start`, `doy_end`, `trait`, `value_start`, `value_end`, `absolute_change`, `daily_change`, `percent_change`, etc., for plants measured on both consecutive study dates. Its near-zero baseline percent-change flag remains intact.

The HTML now includes a **Download all measurements (CSV)** button, which exports the full merged table from the data embedded in the HTML, even if the collaborator only receives the HTML file. The three existing graphs remain: experiment trends, individual trajectories, and compare two dates.

## Safeguards and limits

- The code does not write, delete, move, or copy files inside `groundtruth/`, the original experiment folder, or `within_day/`.
- Only `time_course/index.html`, `time_course/results.csv`, and `time_course/changes.csv` are regenerated.
- Duplicate field positions on the same date or inconsistent breeder IDs across dates cause an error; nothing is silently collapsed.
- This initial version handles **one experiment / one calendar year**; multiyear functionality is deferred.
- There must be at least two dates in the cleaned input. `day_of_year` is 1–365 (or 1–366 in leap years).

## Verification

The updated JavaScript syntax was checked, and the standalone HTML was exercised in Chromium with the previously provided Meadow Fescue sample data (964 rows over two dates). The full-data download exported all 964 rows. **Rscript is not available in this build environment**, so the updated R generator still requires its first execution on Central.
