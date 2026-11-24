# LiDAR results — Within-day report, v5

This release adds the within-day layout requested for field-phenotyping research, and protects source experiment and ground-truth directories against report overwrites. **This package contains no ground-truth datasets.**

## Install on Central

Copy these two files (replacing the previous versions) into the independent reporting folder:

```text
/home/central/Documents/lidar_analysis/lidar_results/
    within_day_summary.R
    within_day_template.html
```

Your `with_day` shell function should invoke the above R script. Or run directly:

```bash
Rscript /home/central/Documents/lidar_analysis/lidar_results/within_day_summary.R \
  /mnt/raw_mirror/MeadowFescue_2026 --name MeadowFescue_26
```

Output remains:

```text
/mnt/raw_mirror/results/MeadowFescue_26/
    groundtruth/                        # User supplied: NEVER written by the report
        GEMS meadow fescue 2026_08_07.csv
    within_day/
        index.html                      # Regenerated interactive report
        results.csv                     # Regenerated cleaned researcher data
```

## What is new in the HTML

**Within-day QC** now puts a compact histogram, boxplot with Tukey outliers, and **scrollable, sortable list of every measurement** in three side-by-side columns on a wide screen. The measured-values table includes breeder ID, breeder row, breeder range (column), and selected LiDAR trait value. Click a column heading to sort ascending/descending.

The **outlier observations** and **paired-pass point-count QC** tables are collapsed under expandable arrow controls. The pass QC is computed from **left vs right point counts within each two-row cart pass** (not overall field-wide totals). Where a key is present, the paired-pass statistics include only mapped study positions; a shared-position comparison is also shown for uneven planting layouts.

There is also a collapsible **LiDAR trait correlation matrix**: histograms along the diagonal, pairwise scatterplots below, Pearson r (and n) above. It uses the selected LiDAR date and mapped/all QC filter. The matrix can be saved as a PNG.

The existing Summary and Ground Truth tabs remain; ground truth comparisons are generated from CSV files read from the analysis's `groundtruth/` directory. Association uses one of three methods: breeder ID through `plot_key.csv`, breeder row plus column through `plot_key.csv`, or LiDAR row plus position. The report selects the method with the most unique matches for each ground-truth file, shows all three match counts, and keeps a manual selector for overrides. Original LiDAR results and plot-key files remain untouched.

## Rerunning an existing analysis: groundtruth protection

Rerunning the same analysis name **rebuilds only files in `within_day/`**. The R script reads from `groundtruth/` but **does not write, replace, move, or delete anything there**. The package intentionally does **not** include or reinstall a sample ground-truth CSV.

The script also refuses to run if an `--output` path overlaps the ground-truth folder or any part of the source experiment, even if an alternate `--groundtruth` path is supplied. The `--name` argument can reuse an existing analysis safely.

> Please keep your ground-truth CSVs in `/mnt/raw_mirror/results/<ANALYSIS_NAME>/groundtruth/` and not within `within_day/`.

## Testing and compatibility

- HTML JavaScript parsed successfully in Node.js.
- The package was checked for write operations to `groundtruth/`; none are present, and directory overlap guards were added.
- The R generator has **not** been executed on Central from this environment. The first execution there is the final test.
- No new R package dependencies: base R only.

## Next: time-course analysis

The planned time-course report will consume the curated `within_day/results.csv`, offering three views: experiment-wide trait trends by day of year, trajectories of selected plants/plots, and paired date-to-date comparisons. Derived growth rates can follow later. Time-course generation should only write within its own `time_course/` directory, and never modify `groundtruth/` or `within_day/results.csv`.
