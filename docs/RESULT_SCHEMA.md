# Result CSV schema

`results.csv` contains one row per analyzed target. Its unique key is:

```text
experiment, date, scan_name, scan_number, plot, side
```

The writer rejects duplicate keys instead of overwriting, averaging, or
silently dropping rows. Rows are ordered by date, scan number, plot, and side.

## Identity

| Column | Meaning |
| --- | --- |
| `experiment` | Experiment name supplied to the runner |
| `date` | Input date identifier |
| `scan_name` | Original recognizable scan name |
| `scan_number` | Numeric scan number when parsing is unambiguous; otherwise missing |
| `plot` | Biological plot identifier carried from the analysis target |
| `side` | Target side: `left`, `right`, `both`, or `none` |
| `target_type` | Existing target category, normally `plot` |
| `target_id` | Existing internal target identifier for traceability |

Side comes from target construction. It is not inferred from output order.
Configured Additional Scan positive/negative side labels therefore remain
authoritative.

## MTA fields

| Column | Meaning | Unit |
| --- | --- | --- |
| `mta_deg` | Whole-target bounded effective mean plant-element tilt angle, measured from horizontal | degrees |
| `mta_qc_pass` | `True` when the compact MTA estimate passes the built-in QC checks, otherwise `False` | boolean |

A non-computable MTA leaves the target row in place, writes a missing `mta_deg`,
and writes `mta_qc_pass=False`. The old graphing alias `lai_mta_deg` maps to
`mta_deg`; old MTA slope and bin count aliases are diagnostic only and are not
written to the main result.

When `mta_diagnostic: true`, detailed fit and angular-bin records are written
to `mta_diagnostics.csv`. Its rows include the same identity fields. Turning
diagnostics on does not add columns to `results.csv` or change target identities
or trait values. When diagnostics are off (the default), that file is not
created.

## PAI fields

| Column | Meaning | Unit |
| --- | --- | --- |
| `pai_m2_m2` | Sum of the vertical layer PAI increments; missing if the complete layer profile is unavailable | m² m⁻² |
| `pai_height_m` | Vertical height of the analyzed PAI box | m |
| `pai_layer_thickness_m` | Requested nominal layer thickness | m |
| `pai_n_layers` | Number of actual layers, including a shorter final layer when needed | count |

`pai_m2_m2` is the only publication PAI estimate in the main table. Whole-box
PAI/PAD, convergence flags, ray counts, gap fractions, likelihoods, and bounds
are not main result columns.

Set `pai_include_layer_columns: true` to add the optional wide `pai_layer_*`
columns to `results.csv`. The writer verifies that the layer sum equals
`pai_m2_m2`.

Set `pai_diagnostic: true` to write `pai_diagnostics.csv`. It adds PAD, ray/gap
counts, chord lengths, likelihood, G function, whole-box comparison, and plain
layer support fields. The writer verifies
`pai_layer_m2_m2 = pad_layer_m2_m3 * layer_thickness_m`.

Other trait columns retain their established names and units; enabled traits
control which columns are present. Identity columns always appear first.
