# Scan Naming

Scan names define biological target names and optional window numbers. The parser only treats `&` as a two-sided scan indicator.

Target = biological target from the scan filename. Window = distance- or mark-defined segment along the scan. Marks = files used to define windows.

## Rules

1. Only `&` makes a scan two-sided.
2. Underscores do not mean two-sided.
3. Bare target names are valid.
4. The first token, or the two tokens around `&`, are biological target names and can be arbitrary non-empty strings.
5. Numeric suffixes after underscores define the window/range:
   - no numeric suffix: single full-window target, internally treated as window `1`
   - one numeric suffix: individual window
   - two numeric suffixes: inclusive range, forward or reverse

Non-numeric underscore suffixes are allowed and ignored by the window parser after the target name. For example, `control_recheck` is still the bare target `control` unless numeric suffixes are present.

## Examples

| Scan name | Meaning |
| --- | --- |
| `1` | Single target named `1`, full-window target, internally window `1` |
| `control` | Single target named `control`, full-window target, internally window `1` |
| `test` | Single target named `test`, full-window target, internally window `1` |
| `1_7` | Single target named `1`, window `7` |
| `1_1_20` | Single target named `1`, inclusive windows `1` through `20` |
| `1&2` | Two-sided scan with targets `1` and `2`, full-window target, internally window `1` |
| `1&2_7` | Two-sided scan with targets `1` and `2`, window `7` |
| `1&2_1_20` | Two-sided scan with targets `1` and `2`, inclusive windows `1` through `20` |
| `2&1_20_1` | Two-sided scan with targets `2` and `1`, inclusive windows `20` down through `1` |
| `control&test` | Two-sided scan with targets `control` and `test`, full-window target, internally window `1` |
| `2b5&1control` | Two-sided scan with targets `2b5` and `1control`, full-window target, internally window `1` |
| `control&test_1_20` | Two-sided scan with targets `control` and `test`, inclusive windows `1` through `20` |

## Side Convention

Side filtering is hard-coded by reconstructed `X` coordinate:

```text
left  = x >= 0
right = x < 0
```

## Forcing Old Single-Target Scans

```yaml
analysis:
  force_two_sided_targets: false
```

`force_two_sided_targets` defaults to `false`. It only forces otherwise single-target normal field scan names into left/right derived outputs for reprocessing old datasets.

It does not apply to legacy `scan_*` additional scans. Those remain controlled by `additional_scan_side_split`.
