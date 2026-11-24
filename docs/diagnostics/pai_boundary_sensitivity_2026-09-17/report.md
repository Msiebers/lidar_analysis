# Final audit: plot-bounded PAI boundary sensitivity

Date: 2026-09-17

Scope: `al_lai/density`, five controlled near-X boundaries, read-only analysis
Production code changed: **none**

## Executive decision

The five-run sweep exposes an unavoidable conflict:

- **Optically**, moving the near face toward the LiDAR removes pre-box censoring.
- **Biologically**, only the 0.4–1.4 m box represents the thinning-treatment plot.
- At the true 0.4-m boundary, mature foreground alfalfa prevents a large and non-random subset of first-return rays from ever observing the plot.

Therefore, the mature-canopy data do **not** identify unbiased absolute PAI for the true plot without an untestable foreground/target independence model. The large number of rays makes the estimate precise for the subset of rays that reached the plot; it does not reveal what those rays would have encountered behind foreground first returns.

The recommended decisions are:

1. Keep **Z-PAI (`z_pai_m2_m2`) as the primary estimator** when the target volume is adequately observable. It is the exact first-event, vertically additive estimator.
2. For this density experiment, use the **0.4-m boundary** whenever making a statement about the treatment plot. Do not substitute 0.0, 0.1, 0.2, or 0.3 m as a “correction”; those boxes include untreated foreground.
3. Treat July 1 at 0.4 m as the only date that passes a defensible absolute-PAI optical screen. Treat July 9 and July 16 primarily as treatment-response/ranking evidence, with explicit censoring qualifications. Do not use July 16 or July 23 for unbiased absolute plot PAI.
4. Keep **whole-box PAI** as the LAI-2200-like transmission reference and an important robustness/QC diagnostic. It is more stable across views and repeats, but its homogeneous-PAD assumption does not solve pre-box missingness.
5. Treat **conditional-layer PAI** as a legacy cross-check. It approximates Z-PAI in low-censoring geometry but discards exact within-layer return distance and adds no distinct biological interpretation.
6. Do not apply inverse-reach weighting or subtract nested-box PAI values. Neither reconstructs unobserved target events.

## 1. Inputs and controlled-run verification

The actual paired files were:

| Near-X | Results | Diagnostics |
|---:|---|---|
| 0.0 m | `results_near00.csv` | `ray_box_diagnostics_results00.csv` |
| 0.1 m | `results_near01.csv` | `ray_box_diagnostics_near01.csv` |
| 0.2 m | `results_near02.csv` | `ray_box_diagnostics_near02.csv` |
| 0.3 m | `results_near03.csv` | `ray_box_diagnostics_near03.csv` |
| 0.4 m | `results_near04.csv` | `ray_box_diagnostics_near04.csv` |

All are under `/media/central/raw_mirror/al_lai/density/`.

Each results file has 546 unique scan/marker/side targets: 39 scans × 7 marker plots × 2 sides. The dates contribute 140, 140, 140, and 126 rows. July 23 lacks scan 6 in every run, so this is not a boundary-specific loss.

### Actual X geometry

| Near-X | Left-side X bounds (m) | Right-side X bounds (m) | Width (m) | Current summaries retained |
|---:|---:|---:|---:|---:|
| 0.0 | -1.4 to 0.0 | 0.0 to 1.4 | 1.4 | 546 |
| 0.1 | -1.4 to -0.1 | 0.1 to 1.4 | 1.3 | 546 |
| 0.2 | -1.4 to -0.2 | 0.2 to 1.4 | 1.2 | 546 |
| 0.3 | -1.4 to -0.3 | 0.3 to 1.4 | 1.1 | 546 |
| 0.4 | -1.4 to -0.4 | 0.4 to 1.4 | 1.0 | 546 |

`ray_box_diagnostics_near04.csv` contains 1,092 summary records: 546 stale records from an older near-0.0 run and 546 current near-0.4 records. I selected summaries using the actual absolute near bound and excluded the 546 stale rows. MTA-bin rows have X bounds and were filtered the same way. Appended layer rows do not carry X-bound identifiers, so I did not try to distinguish the two near04 layer sets by circularly matching their totals.

### Other controlled fields

For every one of the 546 matched targets, all five runs have exactly the same serialized values for:

- Y limits, Z limits, box height, box length, and estimated canopy height;
- 0.10-m PAI/Z-PAI layer thickness and target-specific layer count;
- spherical G function, `G = 0.5`, and 5.0-m maximum observation range;
- `local_grid` ray-box ground mode, 0.10-m bottom AGL, 0.05-m X/Z ground cells;
- local-ground reference/minimum/mean/maximum values and ground cell counts;
- MTA bin, fit-angle, minimum-ray/path, coverage, and range settings.

Across targets, the matched geometry spans Y = 0.0538–0.9254 m, Z = 1.0553–15.4123 m, canopy height = 0.0872–0.8254 m, and 1–9 PAI layers. Those target-to-target differences are identical in all five runs. Upstream result fields (`points`, plot length, scan identity, target identity, LiDAR scan/angle counts) also match target-for-target.

The diagnostic CSV does **not** serialize the IMU and point-filter options. The one available config snapshot—currently showing the final near-0.0 run—uses `imu_interp`, IMU enabled, `dense_median` zeroing with fraction 0.5, roll sign +1, pitch sign -1, local ground filtering, RSSI normalization/filtering disabled, and SOR enabled (`mean_k=4`, `std_ratio=2`). Because there are not five separately archived config snapshots, these settings cannot be proven from each diagnostic summary. The invariant upstream points and the exact matched geometry strongly support the intended controlled run, but the archive should not be described as five independently preserved configuration records.

The full field-by-field check is in `controlled_field_audit.csv`.

## 2. Boundary-response table

The machine-readable `boundary_response.csv` contains 2,730 rows—each of 546 targets at five boundaries—with all requested estimators, ray counts, path/chord quantities, support fields, convergence fields, design labels, and derived metrics.

The generic `total_observed_path_m` field is blank on diagnostic **summary** rows. The exact first-event summary does provide `z_pai_total_observed_path_m`; therefore, `observed_path_per_ray_m` is calculated as:

\[
\text{observed path per ray}=
\frac{\texttt{z\_pai\_total\_observed\_path\_m}}
     {\texttt{pai\_n\_rays\_observed}}.
\]

This substitution is explicitly recorded in `observed_path_source` rather than silently treating the blank generic field as zero.

### Overall matched-boundary summary

| Near-X (m) | Median pre-box | Median reach | Pooled pre-box | Median Z-PAI | Median whole-box | Median conditional | Median chord (m) | Median observed Z path/ray (m) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 48.83% | 51.17% | 52.30% | 2.973 | 1.203 | 2.655 | 0.303 | 0.242 |
| 0.3 | 27.82% | 72.18% | 36.69% | 3.824 | 1.796 | 3.755 | 0.314 | 0.224 |
| 0.2 | 5.35% | 94.65% | 15.46% | 3.409 | 2.038 | 3.471 | 0.310 | 0.214 |
| 0.1 | 0.31% | 99.69% | 2.32% | 2.026 | 1.591 | 2.086 | 0.304 | 0.242 |
| 0.0 | 0.004% | 99.996% | 0.034% | 1.157 | 0.893 | 1.160 | 0.268 | 0.231 |

The pooled fraction weights targets by their intersecting-ray count; the median gives every scan/marker/side target equal weight. Both lead to the same substantive conclusion.

All five runs report complete Z and conditional profiles and 100% layer support; all whole-box fits converged and none saturated. That is numerical support **among observed rays**, not evidence that pre-box-hidden target vegetation was observed.

## 3. Optical-access transition

The main transition is between near 0.2 and 0.3 m:

- median pre-box interception rises from 5.35% to 27.82%;
- median reach falls from 94.65% to 72.18%;
- pooled reach falls from 84.54% to 63.31%;
- observed-ray-weighted zenith angle shifts from 64.3° to 68.7°;
- the share of observed rays in the 75–90° bin rises from 29.65% to 36.52%;
- Row-2 Z-PAI correlation falls from 0.830 to 0.690 and MAE rises from 1.201 to 1.422 m² m⁻²;
- whole-box Row-2 correlation falls from 0.845 to 0.734.

At 0.4 m, censoring becomes severe: median reach is 51.17%, observed-ray-weighted angle is 71.6°, and 42.99% of observed rays occupy the 75–90° bin. Z-PAI Row-2 correlation falls to 0.532 and MAE rises to 1.671 m² m⁻².

| Near-X | Z Row-2 r | Z Row-2 median relative difference | Whole Row-2 r | Whole Row-2 median relative difference | Z repeat CV | Whole repeat CV |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 0.532 | 0.430 | 0.710 | 0.319 | 0.184 | 0.171 |
| 0.3 | 0.690 | 0.405 | 0.734 | 0.334 | 0.127 | 0.130 |
| 0.2 | 0.830 | 0.367 | 0.845 | 0.278 | 0.132 | 0.104 |
| 0.1 | 0.730 | 0.392 | 0.840 | 0.330 | 0.204 | 0.136 |
| 0.0 | 0.689 | 0.299 | 0.792 | 0.318 | 0.248 | 0.189 |

The pooled Row-2 correlations partly reflect large between-date growth differences. Date-specific agreement is poorer. At the true boundary, Z-PAI Row-2 r is 0.215, 0.193, 0.009, and 0.105 on July 1, 9, 16, and 23; corresponding median relative disagreements are 0.350, 0.430, 0.588, and 0.279. The July 16 result is especially important: the strong treatment gradient is accompanied by very poor opposite-view agreement.

The transition is not a smooth additive accumulation of foreground PAI. Median Z-PAI rises from 1.157 at near 0.0 to 3.824 at 0.3, then drops to 2.973 at 0.4. This peak-and-collapse behavior occurs because each boundary changes the eligible ray population, angular mix, chord distribution, observed exposure, and amount of biological material—not just one term in a fixed equation.

## 4. Optical correctness versus biological correctness

### Optical criterion

Near 0.0 and 0.1 have almost complete reach because the foreground canopy is brought inside the modeled volume. Near 0.2 is the best empirical compromise for view agreement and repeatability: median reach is 94.65%, whole-box Row-2 relative disagreement is lowest (0.278), and whole-box technical-repeat CV is lowest (0.104).

Those are valid statements about the **expanded volume**. They are not solutions for the treatment plot.

### Biological criterion

The treatment occupied 0.4–1.4 m. Only near 0.4 has the correct footprint. Every smaller near bound progressively adds full-grown, untreated alfalfa. The correct biological box is therefore optically compromised, while the best-observed boxes are biologically contaminated.

There is no boundary in this sweep that simultaneously provides the true plot footprint and low foreground censoring. Selecting near 0.0 or 0.2 because it improves agreement would answer a different biological question.

## 5. Treatment-response evidence

Treatment was mapped from the experiment design in `density.R`, including the July 23 odd/even reversal. Plot-side scans were first averaged to repeat/biological-row values, then to treatment means, so a high-ray target did not dominate the treatment relationship.

### At the true 0.4-m boundary

| Date | Median pre-box | Median reach | Z removal-vs-PAI Spearman | Z high-removal minus control | Whole-box Spearman | Whole high-removal minus control | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| Jul 1 | 2.58% | 97.42% | -0.714 | -0.032 | -0.714 | -0.034 | Correct order, very small early-canopy signal |
| Jul 9 | 42.17% | 57.83% | -1.000 | -3.058 | -0.964 | -1.304 | Strong treatment order despite censoring |
| Jul 16 | 67.68% | 32.32% | -0.893 | -3.480 | -0.964 | -1.624 | Strong order, but absolute PAI/view agreement unreliable |
| Jul 23 | 66.30% | 33.70% | -0.286 | -0.269 | -0.214 | -0.169 | Little treatment separation; scan 6 also absent |

The negative sign is expected: more removal should yield lower PAI.

### Dilution as foreground is admitted

For Z-PAI, the treatment Spearman sequence from near 0.4 → 0.3 → 0.2 → 0.1 → 0.0 is:

| Date | 0.4 | 0.3 | 0.2 | 0.1 | 0.0 |
|---|---:|---:|---:|---:|---:|
| Jul 1 | -0.714 | -0.286 | 0.250 | 0.321 | 0.286 |
| Jul 9 | -1.000 | -0.607 | -0.071 | 0.179 | 0.107 |
| Jul 16 | -0.893 | -0.179 | 0.786 | 0.750 | 0.393 |
| Jul 23 | -0.286 | 0.179 | 0.286 | 0.393 | -0.143 |

Whole-box PAI preserves the July 9/16 ordering slightly farther into the 0.3-m box (`rho=-1.000` and `-0.857`), but loses or reverses it by 0.2 m. Conditional PAI behaves like Z-PAI.

This is independent evidence that the 0.0–0.4 m material contains little thinning-treatment information and can overwhelm the treatment response. It also shows why near 0.0 cannot be called a successful plot-bounded result even though reach is nearly perfect.

The boundary dependence strengthens with canopy development. July 1 has 97.4% median reach at the true boundary; July 9 falls to 57.8%; July 16 and July 23 fall to roughly one-third.

## 6. What the foreground bands do—and what cannot be inferred

The cumulative pooled pre-box fractions at near 0.4, 0.3, 0.2, 0.1, and 0.0 are 52.30%, 36.69%, 15.46%, 2.32%, and 0.034%. This locates most of the foreground interception in the 0.2–0.4 m region. It does **not** make the differences exact band interception probabilities, because changing the box adds geometrically eligible rays as well as path length.

Likewise, differences such as `Z-PAI(0.3–1.4) - Z-PAI(0.4–1.4)` are not band PAI. PAI estimators are nonlinear hazard estimates, and each nested box has a different risk set, angle distribution, chord distribution, and denominator.

Quantities that are genuinely additive under a common ray cohort are:

- geometric path length in each X band;
- observed pre-event exposure in each X band;
- first-event counts assigned to the band containing the return;
- modeled optical depth along a ray, under an explicit sequential hazard model.

The summary files do not retain a common ray identifier with bandwise paths/events, so those band quantities cannot be reconstructed exactly from the five aggregate runs. A future raw-ray diagnostic could compute them without changing the production estimator. Even then, a foreground first return leaves all target events behind it unobserved.

The angular table demonstrates that the foreground also changes *which* rays reach the plot. Observed-ray-weighted angle moves from 50.1° at near 0.0 to 71.6° at near 0.4; path-weighted angle moves from 53.4° to 75.1°. At near 0.4, angle-bin pre-box fractions are approximately 25.6% at 30–45°, 47.5% at 45–60°, 52.6% at 60–75°, and 53.6% at 75–90°. Thus the target sample is both reduced and angularly selected.

## 7. Estimator reassessment

### Sensitivity over all five boundaries

| Estimator | Median within-target boundary CV | Median range/mean | Median absolute 0.4-vs-0.0 change | 0.4-vs-0.0 correlation |
|---|---:|---:|---:|---:|
| Z-PAI | 0.451 | 1.093 | 1.294 | 0.408 |
| Whole-box | 0.339 | 0.843 | 0.427 | 0.562 |
| Conditional | 0.446 | 1.084 | 1.159 | 0.384 |

Whole-box PAI changes least across boundaries and has the best repeatability/opposite-view agreement. That is consistent with its simpler, one-parameter homogeneous transmission model. It does not establish that whole-box is less biased for the true plot: a stable answer to a misspecified or selectively observed model is still not an unbiased biological total.

Z-PAI and conditional PAI remain closely related, but their agreement degrades as censoring grows. Mean absolute Z-minus-conditional differences rise from 0.016 m² m⁻² at near 0.0 to 0.349 at near 0.4. Exact hit distance matters more in the sparse survivor risk set.

### Final estimator roles

**Z-PAI / exact first-event profile**

- Best numerical and theoretical estimator when the volume is observable.
- Uses every observed free-path segment up to the first event or box exit.
- Preserves exact hit layer and hit distance.
- Supplies additive vertical contributions.
- Does not correct informative removal of rays before box entry.

**Whole-box PAI**

- Closest direct analogue to LAI-2200 gap/transmission theory for a finite box with exact ray chords.
- Best empirical precision and view stability in this sweep.
- Assumes one homogeneous PAD over the full height and loses vertical attribution.
- Should be a co-primary diagnostic/sensitivity result, not a replacement truth.

**Conditional-layer PAI**

- A valid interval-censored approximation to the same first-event process.
- Nearly identical to Z-PAI in corrected low-censoring geometry.
- Discards exact within-layer return distance and offers no compensating advantage here.
- Retain only as a compatibility/cross-check value.

## 8. Z-PAI additivity and biological meaning

For layer `k`, let `E_k` be total observed ray path before first event or exit, `H_k` the number of first returns in that layer, `G=0.5`, and `Delta h_k` the layer thickness. The exact first-event log likelihood separates by layer:

\[
\ell = \sum_k \{H_k\log(G\,PAD_k)-G\,PAD_kE_k\},
\qquad
\widehat{PAD}_k=\frac{H_k}{G E_k}.
\]

The reported contribution and total are:

\[
PAI_k=\widehat{PAD}_k\Delta h_k,
\qquad
PAI_{total}=\sum_k PAI_k.
\]

The four non-appended diagnostic files verify this identity to a maximum numerical discrepancy of 3.12 × 10⁻⁷ m² m⁻². The near04 summary says every Z profile is complete with support fraction 1.0, but its duplicated layer rows lack X-bound identifiers and were not used for a direct layer-sum check.

Methods-language interpretation:

> Z-PAI estimates a piecewise-vertical first-interception hazard from the observed ray path in each canopy-height layer. Multiplying each layer PAD by its thickness gives that layer's contribution to total effective PAI, and the contributions sum to total PAI for the bounded volume. The vertical values describe how the total interception hazard is distributed with height under the assumed spherical projection function and random-contact model; they are not independent destructive measurements of isolated 10-cm slabs.

That interpretation is biologically meaningful when the risk set represents the intended plot. A complete numerical profile cannot remove bias caused by rays missing before entry.

## 9. Identifiability at the true boundary

For a ray stopped in the foreground, the emitted direction and counterfactual plot chord are known. The missing variable is whether, where, and in which vertical layer that same ray would have first intersected target vegetation after entering the plot. First-return data contain no observation of that counterfactual.

| Proposed correction | What it can use | Unobserved quantity it needs | Identifiable here? |
|---|---|---|---|
| Inverse reach weighting | Direction, entry, chord, observed reach probability | Target outcome for foreground-stopped rays; equivalence of reached and unreached rays after conditioning | No, unless missing-at-random/exchangeability is assumed |
| Matched angle/chord cohorts | Balance measured ray geometry | Target occupancy behind foreground events | No; matching geometry does not reveal hidden vegetation |
| Standard censoring/first-event likelihood | Correctly handles events and exits inside the plot | Outcome after a pre-entry foreground event | No; Z-PAI already uses the observable likelihood |
| Opposite-view combination | Additional target exposures from another direction | Regions hidden from both views and relation between visible/hidden target | Improves coverage, not nonparametric identification |
| Foreground + target sequential hazards | Foreground event/exposure and target event/exposure for survivors | Target hazard for nonsurvivors | Parametrically identifiable only under homogeneity/independence assumptions |
| Nested-box PAI subtraction | Five aggregate estimates | Common-cohort band events/exposure | No; estimates and ray populations are nonlinear/different |

An inverse-probability correction could estimate `P(reach | angle, chord, entry point, ...)`, but unbiased weighting also requires the unobserved target outcome to be independent of reach conditional on those variables. Dense, clumped foreground gaps and target gaps can share row-scale structure, so that assumption cannot be tested from first returns.

The correct conclusion is not that target PAI is always impossible under a model. Under a piecewise-homogeneous independent Poisson model, foreground and target hazards can be estimated separately from their respective event counts and observed exposures. But the target estimate is then identified by the model assumption: it extrapolates the survivor-ray target hazard to the hidden volume. More rays narrow its model-based standard error; they do not validate the extrapolation.

Opposite views are valuable because a region hidden from one side may be visible from the other. They should be combined in one first-event likelihood or treated as designed replicate views. They cannot recover a region hidden from both, and the current Row-2 disagreement shows that the two views are not interchangeable measurements of a fully observed target.

## 10. Specific scan examples

1. **July 9, scan 001, marker 1, 0% removal (control).** Z-PAI rises from 0.741/0.873 (left/right) at near 0.0 to 4.280/4.030 at the true 0.4 boundary. True-boundary reach is 91.1% left and 80.3% right. Including foreground changes a dense control into an apparently low-PAI volume.
2. **July 9, scan 001, marker 2, 100% removal.** At near 0.4, Z-PAI is 0.482 left and 1.540 right, with reach 45.8% and 75.5%. At near 0.0 it becomes 1.298/1.590. The untreated foreground largely erases the contrast with marker 1.
3. **July 16, scan 007, marker 3, right.** At near 0.4, 94.99% of eligible rays are stopped before the box and only 5.01% reach it. Z-PAI is 1.649 and whole-box PAI is 1.213, but these values describe an extremely selected survivor set.
4. **July 16, scan 007, marker 4, left.** Moving from 0.3 to 0.4 reduces reach from 36.8% to 13.1% and changes Z-PAI from 11.788 to 3.146.
5. **July 16, scan 009, marker 7, left.** Over the same transition, reach falls from 75.0% to 47.3% while Z-PAI changes in the opposite direction, from 8.163 to 14.345. The opposite responses in examples 4 and 5 demonstrate why no deterministic nested-box correction is defensible.

## 11. Destructive measurements

No boundary-matched destructive PAI exists for the density plots, so destructive data cannot select the near-X setting. The independent biomass/partition experiments remain useful validation of estimator behavior:

- Z-PAI versus dry biomass: `r=0.950` (biomass, n=12) and `r=0.682` (partition, n=12).
- Conditional PAI versus dry biomass: `r=0.954` and `r=0.642`.
- Z-PAI versus destructive LAI: `r=0.799` (n=9), but LAI omits stems.
- Z-PAI versus destructive PAI: `r=0.527` (n=6); conditional: `r=0.415`.
- Stem area is 15.9–33.4% of destructive PAI, mean 21.7%, so LiDAR interception should be called PAI rather than LAI.

These small independent datasets support retaining first-event PAI and the PAI terminology. They do not validate any density boundary or remove the density experiment's foreground identifiability problem. The older one-scan whole-box biomass check (`r=0.964`, n=12) likewise supports the whole-box reference role, not boundary selection.

## 12. Usable range and proposed QC

The sweep supports an empirical operating screen, not a universal physical constant:

| Target reach / pre-box fraction | Classification | Evidence-based use |
|---|---|---|
| Reach ≥90% / pre-box ≤10% | Preferred | Absolute plot PAI may be reported if geometry is biologically correct and view diagnostics pass |
| Reach 75–90% / pre-box 10–25% | Warning | Report with sensitivity/opposite-view checks; emphasize possible selection bias |
| Reach <75% / pre-box >25% | Fail for unbiased absolute PAI | Relative treatment/rank analysis only if randomized design and views agree sufficiently |

Why those breakpoints:

- the near-0.2 condition lies on the high-reach side (median 94.65%);
- the next controlled step, near 0.3, crosses to 72.18% median reach and 27.82% pre-box interception;
- at that step the angular risk set shifts, whole/Z view correlations fall, and the true treatment response begins to collapse for Z-PAI;
- at near 0.4, reach is near 50% overall and near one-third on the two mature late dates.

These thresholds do not prove absence of bias above 90%, and they should not be hard-coded from one experiment without validation. They are appropriate prespecified flags for this paper and for a prospective pilot. `z_pai_profile_support_fraction=1` and convergence are necessary numerical checks but are not useful censoring screens here because all five runs pass them.

Date decisions at the correct boundary:

- **July 1:** use for absolute plot-specific PAI; median reach 97.4%. The canopy and treatment contrast are small, so uncertainty in biological separation remains.
- **July 9:** do not claim unbiased absolute PAI; median reach 57.8%. The perfect/near-perfect treatment ordering supports relative treatment inference with censoring disclosure.
- **July 16:** reject absolute PAI; median reach 32.3%, Z opposite-view disagreement is high. The treatment ordering is scientifically interesting but should be secondary/sensitivity evidence.
- **July 23:** reject absolute PAI; median reach 33.7%, treatment separation is weak, and scan 6 is missing. Do not interpret loss of separation as a pure biological effect because severe censoring remains.

## 13. Final answers to the requested decisions

1. **Best algorithm when the full volume is observable:** Z-PAI/exact first-event profile.
2. **Best algorithm for the 0.4–1.4 m plot here:** Z-PAI is the best-defined estimate for the reachable subset, but no existing estimator yields demonstrably unbiased total plot PAI under the observed censoring.
3. **Unbiased mature-canopy plot PAI:** not supported by these first-return data.
4. **Usable dates:** July 1 for absolute PAI; July 9 and July 16 for qualified relative treatment evidence; July 23 is weak for both absolute PAI and treatment response.
5. **Z-PAI primary:** yes, subject to reach/pre-box QC and correct biological bounds.
6. **Whole-box role:** LAI-2200-like reference, precision/QC benchmark, and sensitivity result.
7. **Conditional role:** legacy cross-check only.
8. **Vertical attribution:** additive and biologically interpretable as vertical contributions to the same effective PAI, not independent slab measurements; do not interpret failed-QC profiles as unbiased spatial truth.
9. **Censoring correction:** none is nonparametrically defensible. A sequential correction is model-based and must state its independence/homogeneity assumptions.
10. **Opposite views:** improve coverage and precision but do not guarantee identification; combine through one likelihood where possible and retain view-disagreement QC.
11. **QC:** preferred reach ≥90%, warning 75–90%, fail absolute PAI below 75%, paired with pre-box ≤10%, 10–25%, and >25%.
12. **Future geometry:** remove nonplot vegetation from the optical path or put the scanner at the plot boundary; acquire designed views from both plot sides and/or above canopy.

## Proposed paper analysis strategy

1. Define the biological estimand before analysis: total PAI in X=0.4–1.4 m, with Z-layer contributions summing to that total.
2. Use Z-PAI at near 0.4 as the primary estimator and whole-box PAI as the prespecified transmission sensitivity estimator. Put conditional PAI in supplementary validation only.
3. Report pre-box fraction, reach fraction, observed exposure, view disagreement, and support/convergence beside every PAI result.
4. Present the five-boundary sweep explicitly as an optical-versus-biological sensitivity analysis. Do not select a smaller near bound as the primary result.
5. Restrict main absolute-PAI claims to July 1. Analyze July 9/16 treatment ordering and contrasts as relative, randomized-treatment evidence; label July 16 secondary because of view dependence. Treat July 23 as failed absolute QC and inconclusive treatment response.
6. Show the treatment-gradient disappearance as foreground is admitted. This is evidence that the smaller boxes measure a mixed, biologically different volume.
7. State that a sequential foreground/target model is a sensitivity model, not an identified correction. If fitted later from raw rays, report results across explicit independence/clumping assumptions.
8. Validate PAI—not LAI—against destructively measured leaf+stem area where available and report stem contribution separately.

## Future acquisition recommendation

Position the LiDAR so the first vegetation along each measurement ray belongs to the experimental unit:

- place the scanner in an aisle immediately adjacent to the 0.4-m plot boundary, rather than looking through an untreated 0.4-m foreground strip;
- scan every plot from both lateral boundaries with registered geometry, or add an elevated/overhead view, so hidden regions from one origin are exposed to another;
- if the foreground strip cannot be avoided, include it in the treatment unit or physically clear a narrow optical corridor without altering the measured plot;
- run a pilot and reposition/augment acquisition if target reach is below 90%; do not continue relying on a single first-return view once reach approaches 75%;
- preserve ray-level event/exposure diagnostics by X band and view, and collect destructive leaf+stem area on geometry-matched plots/dates;
- consider multi-return/full-waveform or multi-position terrestrial scanning when total area behind dense foreground is the primary estimand.

The fundamental acquisition rule is simple: **the sensor must see the biological plot boundary directly**. Algorithmic refinement cannot reconstruct target returns that a first-return instrument never observed.

## Reproducibility artifacts

- `audit.py` reruns the complete read-only extraction, matching, checks, tables, and figures.
- `boundary_response.csv` is the full matched response table.
- `boundary_summary.csv`, `boundary_date_summary.csv`, and `boundary_transitions.csv` summarize the sweep.
- `view_agreement*.csv` and `technical_repeatability*.csv` contain pooled and date-specific precision results.
- `treatment_response.csv` and `treatment_means.csv` contain treatment analyses.
- `angular_composition.csv` and `angular_bins.csv` contain risk-set composition.
- `profile_support.csv` contains completeness/additivity checks.
- `estimator_sensitivity.csv` contains matched boundary sensitivity.
- Four PNGs show the boundary sweep, treatment ordering, angle shift, and a representative scan.
