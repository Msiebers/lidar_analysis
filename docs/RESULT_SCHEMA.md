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

When `ray_box.diagnostic: true`, shared-box summaries, detailed MTA angular-bin
records, and PAI layer records are written to `ray_box_diagnostics.csv`. Its
rows include the same identity fields. Turning
diagnostics on does not add columns to `results.csv` or change target identities
or trait values. When diagnostics are off (the default), that file is not
created.

## PAI fields

| Column | Meaning | Unit |
| --- | --- | --- |
| `pai_m2_m2` | Sum of the vertical layer PAI increments; missing if the complete layer profile is unavailable | m² m⁻² |
| `pai_height_m` | Vertical height of the shared ray box; ground-relative when `ray_box.ground_mode: local_grid` | m |
| `pai_layer_thickness_m` | Requested nominal layer thickness | m |
| `pai_n_layers` | Number of actual layers, including a shorter final layer when needed | count |

`pai_m2_m2` is the only publication PAI estimate in the main table. Whole-box
PAI/PAD, convergence flags, ray counts, gap fractions, likelihoods, and bounds
are not main result columns.

Set `pai_include_layer_columns: true` to add one integrated PAI value per layer
to `results.csv` (`pai_layer_*_conditional_pai_m2_m2`). All layer support and
fit fields remain in diagnostics. The writer verifies that the layer sum equals
`pai_m2_m2`.

The `pai_layer` rows in `ray_box_diagnostics.csv` add PAD, hit/gap/unknown counts,
chord lengths, likelihood, G function, conditioning, fit status, ground
diagnostics, whole-box comparison, and layer support fields. The writer verifies
`pai_layer_m2_m2 = pad_layer_m2_m3 * layer_thickness_m`.

## Topology fields

`stand_topo_count` is the raw detected peak count and `stand_topo_per_m` is the
existing row-length-normalized count. Set `topology_trait.include_per_m2: true`
to also write `stand_topo_per_m2`, calculated as raw count divided by the X-Z
plot area. Internally split targets also write left/right per-m² values.

Other trait columns retain their established names and units; enabled traits
control which columns are present. Identity columns always appear first.
