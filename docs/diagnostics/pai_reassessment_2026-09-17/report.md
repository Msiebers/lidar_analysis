# PAI estimator reassessment

Date: 2026-09-17

## Decision

The best primary estimator of total bounded-plot PAI is the **exact first-event,
piecewise-vertical likelihood already implemented as `z_pai_m2_m2`**. It is the
mathematically consistent joint PAD profile requested in the discussion: each
ray contributes free path until its first return or the box exit, each return is
assigned to its height layer, and the layer PAI values sum to one total PAI.

The **homogeneous whole-box estimator** is the closest direct analogue of the
LAI-2200's gap/transmission calculation and should remain a prominent reference
diagnostic. It is simpler and more repeatable in the current data, but converting
its one fitted PAD to `PAD * height` assumes that a single PAD adequately
represents all ray paths through a vertically heterogeneous finite box.

The current **conditional-layer total is defensible**. It is not a sum of
unrelated canopy quantities. It is an interval-censored version of the same
piecewise-constant first-event survival likelihood. Because the likelihood
separates by layer, fitting the layers separately gives the same maximum-
likelihood estimates as fitting that interval-censored likelihood jointly. It
does, however, discard the exact within-layer return distance that is already
available. It therefore should not be preferred over the exact first-event
estimator as the primary public value.

The dormant **existing joint-profile implementation is a different model**. It
uses each ray's full geometric path through all layers but retains only whole-box
hit/gap status. That is a valid heterogeneous binary-transmission inversion, but
it discards the known first-return layer and distance. Its design-matrix rank
check is not sufficient evidence of practical profile identifiability. It is not
recommended as the primary estimator or as the production vertical profile.

No production code or behavior was changed in this audit.

## 1. Theory and the four implementations

LI-COR states the basic model as

\[
P_{gap}(\theta)=\exp[-G(\theta)\mu S(\theta)],
\]

where `G` is projected-area fraction, `mu` is area density, and `S` is path
length. LI-COR also notes that the equation applies to general canopy shapes
when path length is known. The instrument integrates observations from several
view angles to estimate area index and orientation. See the official
[LAI-2200C theory of operation](https://www.licor.com/products/leaf-area/LAI-2200C/science)
and the [LAI-2200 manual](https://download.opensource.licor.com/projects/fv2200/docs/LAI-2200_Manual_v1.4.pdf).

The LiDAR adaptation replaces an inferred infinite-slab path with the exact
finite chord of each emitted ray. All current PAI estimators fix `G = 0.5`, the
spherical orientation assumption. They consequently estimate an effective PAI
when foliage is clumped or its orientation distribution is not spherical.

### A. Homogeneous whole-box likelihood

For observed ray `i`, with full box chord `L_i`, one PAD `mu`, and binary outcome
gap/hit, the implemented log likelihood is

\[
\ell(\mu)=
\sum_{i\in gap}-G\mu L_i+
\sum_{i\in hit}\log\{1-\exp(-G\mu L_i)\}.
\]

The reported value is `mu * box_height`. This is the cleanest bounded-volume
translation of LAI-2200 gap probability. It uses the correct actual chord and
does not substitute scanner height or `height / cos(theta)`.

Its limitation is model, not units: one constant PAD must explain every ray.
If PAD changes with height and finite rays traverse different mixtures of
layers, the fitted `mu * height` is a ray-weighted effective area index, not
necessarily the vertical integral of the true profile.

Source: `lidar_analysis/pai.py`, `_fit_transmission` and lines 317-347 of
`compute_pai_traits`.

### B. Current conditional layers

For a ray whose first hit is in layer `h`, the coarsened likelihood is

\[
\ell_i = -\sum_{k<h}G\mu_k L_{ik}
       + \log\{1-\exp(-G\mu_h L_{ih})\}.
\]

For a complete gap it is

\[
\ell_i = -\sum_k G\mu_k L_{ik}.
\]

The ray must survive to a layer before it enters that layer's risk set. Layers
before the hit are gaps, the hit layer is an interval-censored interception,
and later layers provide no information. This is exactly what the current
reclassification implements. Since each term contains only one `mu_k`, the
likelihood factorizes by layer; separate fitting is mathematically equivalent
to a simultaneous fit of this coarsened model.

Thus

\[
PAI_k=\mu_k\Delta h_k,\qquad
PAI_{total}=\sum_k PAI_k
\]

has a valid total-PAI interpretation under the same Poisson-contact, horizontal-
homogeneity, and fixed-`G` assumptions. The weakness is information loss: a hit
at the start and a hit at the end of a 10-cm layer are treated identically.

Source: `lidar_analysis/pai.py`, lines 398-468.

### C. Joint vertical profile

There are two distinct meanings of "joint" here.

The dormant implementation forms full layer chords for every observed ray and
uses only whether any interception occurred in the box:

\[
\eta_i=G\sum_k\mu_k L_{ik},\quad
P(gap_i)=\exp(-\eta_i).
\]

This binary model is valid, but hit rays contribute
`log(1 - exp(-eta_i))`; the known hit layer and hit distance are omitted. A
vertical profile is identified only through variation in the mixtures of layer
paths across rays. Full matrix rank is necessary but not sufficient: column
collinearity, likelihood curvature, boundary estimates, and uncertainty also
matter. Source: `lidar_analysis/pai.py`, lines 357-396.

The correct exact first-event likelihood uses observed path `E_ik` in each
layer only up to the first return or box exit. If `h_i` is the hit layer,

\[
\ell_i=-\sum_k G_i\mu_k E_{ik}
       + I(hit_i)\log(G_i\mu_{h_i}) + constant.
\]

Collecting layer exposure `E_k` and first hits `H_k`, with current fixed
`G = 0.5`,

\[
\ell=\sum_k[H_k\log(G\mu_k)-G\mu_kE_k],\qquad
\widehat\mu_k=\frac{H_k}{G E_k}.
\]

That is exactly the current Z-PAI calculation. If `G_i` later varies by ray,
the denominator must become `sum_i(G_i E_ik)`, not `G * sum_i(E_ik)`.

### D. Z-PAI

Z-PAI is therefore not a materially different biological quantity. It is the
maximum-likelihood PAD profile for the same Beer-Lambert/Poisson first-contact
process, using the exact first-return distance. Its layer values integrate to
one total PAI. It is the information-preserving limit toward which the
conditional layer estimator moves as layers become thinner.

Source: `lidar_analysis/pai.py`, lines 65-248.

## 2. Reference rays and censoring

The valid risk set consists of emitted rays that geometrically intersect the
box and whose first event can be observed through the box:

- A first return before box entry is **left-truncated with respect to the target
  volume** and supplies no target exposure. It must be excluded.
- A first return inside the box is an event. Exact first-event/Z-PAI contributes
  free path to the hit and one hit to its layer.
- A return beyond box exit, or a qualified no-return whose observable range
  passes the exit, is a right-censored full gap. It contributes the full observed
  path and no hit.
- An unqualified/short-range unknown cannot establish transmission through the
  box and must be excluded.
- After a first return, deeper layers are unobserved. Exact first-event survival
  analysis handles this by ending exposure at the return; it must not relabel
  the unseen continuation as a gap.

Excluding pre-box returns is unbiased only if reachability is non-informative
conditional on the modeled ray geometry. Vegetation before the target generally
violates that condition, as the earlier side-bias audit demonstrated. No
within-box likelihood can recover the rays selectively removed before entry.

In the corrected `density` run (`x_near_m = 0.0`), only 43,273 of 162,438,690
intersecting rays returned before the box: **0.02664%**. That nearly removes this
specific selective-censoring mechanism.

However, zeroing the near face is not automatically a biological fix. The draft
methods define the thinning experimental unit as beginning 0.4 m from the
sensor, with intervening alfalfa outside that unit. A box from the scanner to
1.3 m therefore measures a different volume unless the physical target boundary
also changed. The fresh July 9 results do not reproduce a decreasing response
to removal: Spearman removal-versus-PAI is 0.321 for whole-box and 0.000 for the
exact first-event total. This is consistent with target-volume contamination or
mapping/geometry mismatch, and it prevents using the new run as biological
proof that one estimator is correct. The robust solution is to make the target
near face physically observable (sensor at the boundary, sensor above canopy,
or suitable multiple views), not silently expand the biological plot.

## 3. Empirical results

### Corrected `density` run

The current diagnostic file contains 546 plot-side summaries.

| Estimator | Mean | Median | Range |
|---|---:|---:|---:|
| Whole-box | 0.934 | 0.895 | 0.008-4.132 |
| Conditional layers | 1.158 | 1.162 | 0.009-6.605 |
| Exact first-event / Z | 1.151 | 1.157 | 0.009-7.009 |

Conditional and exact first-event totals are effectively the same at the
current 10-cm resolution (`r = 0.9993`, mean exact-minus-conditional = -0.007,
MAE = 0.016). Their individual layer contributions are also nearly identical
(`r = 0.9988`, MAE = 0.0044 m2 m-2 per layer). This confirms the theoretical
relationship: current conditional PAI is a coarsened version of Z-PAI, not an
unrelated quantity.

The exact first-event total is higher than whole-box by 0.217 m2 m-2 on average;
the median ratio is 1.319. That difference is expected when the homogeneous
whole-box model smooths vertically heterogeneous attenuation.

The simpler whole-box estimator is empirically more stable:

| Estimator | Median technical-repeat CV | 90th-percentile CV | Opposite-view r | Opposite-view MAE |
|---|---:|---:|---:|---:|
| Whole-box | 0.178 | 0.363 | 0.795 | 0.285 |
| Conditional | 0.251 | 0.488 | 0.698 | 0.402 |
| Exact first-event / Z | 0.246 | 0.476 | 0.688 | 0.405 |

This favors whole-box for precision and QC, but does not remove its homogeneity
assumption. It is a reason to report both estimates and their disagreement, not
to choose solely by repeatability.

### Vertical-profile support

Every layer in all 546 current targets had positive observed exposure, so the
exact layer hazard was structurally estimable. In 374 targets every layer also
had at least one first hit. The other 172 targets contained at least one
zero-hit layer; those layers have a boundary MLE of zero and require one-sided
uncertainty rather than being treated as strongly resolved zero plant area.
There were 224 zero-hit cells among 2,953 target-layer cells.

Therefore the exact joint profile is usable at 10 cm for the total and for broad
vertical allocation, but not every 10-cm fraction is equally well resolved.
Profile uncertainty, support flags, and sensitivity to coarser layers should be
part of a later production decision.

### Destructive and biomass checks

The available destructive-analysis results predate the corrected density run
and use their saved biomass/partition geometries. They are independent checks,
not a controlled `x_near = 0` comparison. Values below use five-scan biological
plot/date means.

| Reference | n | Conditional r | Exact first-event/Z r |
|---|---:|---:|---:|
| Biomass-set dry biomass | 12 | 0.954 | 0.950 |
| Partition-set dry biomass | 12 | 0.642 | 0.682 |
| Destructive LAI | 9 | 0.762 | 0.799 |
| Destructive PAI | 6 | 0.415 | 0.527 |

Raw agreement with destructive area is poor despite positive correlation:
RMSE against destructive PAI is 2.70 m2 m-2 for conditional and 3.22 m2 m-2 for
exact first-event/Z. The sample is only six plot/date means, and the estimates
are systematically high. Fixed `G`, clumping, plot-volume mismatch, first-return
detection, and ground/height bounds all remain plausible contributors.

An older one-scan-per-plot diagnostic contains whole-box values for the biomass
plots: whole-box versus dry biomass `r = 0.964`, conditional versus dry biomass
`r = 0.984` (`n = 12`). It is useful context only; it is neither a five-repeat
comparison nor the corrected density geometry and should not decide the method.

## 4. PAI, not LAI

LiDAR first returns do not identify whether the intercepted element is a leaf,
petiole, or stem. In the six destructive whole-canopy samples with both leaf and
stem area, stem area was 15.9-33.4% of total plant area (mean 21.7%). Destructive
PAI was 18.9-50.3% larger than LAI. Calling the unseparated LiDAR metric LAI
would therefore create meaningful, treatment/date-dependent bias. The public
name should remain **PAI**, more precisely effective PAI under the fixed-`G` and
random-element assumptions.

## 5. Recommended output contract

If production behavior is changed later, the clean contract is:

- `pai_m2_m2`: primary total from the exact first-event profile (current Z-PAI
  calculation), with units m2 plant area per m2 ground area.
- `pai_whole_box_m2_m2`: homogeneous binary-transmission reference diagnostic.
- `pai_profile_complete`: every layer has positive observed exposure and the
  total equals the sum of finite layer estimates.
- `pai_profile_interior_complete`: optional stronger QC; every layer has at
  least one hit, so no layer has a boundary-only zero estimate.
- `pai_layer_<bottom>_<top>_pad_m2_m3`: layer PAD.
- `pai_layer_<bottom>_<top>_m2_m2`: `PAD * layer_thickness` contribution to the
  same total.
- `pai_fraction_<bottom>_<top>`: layer PAI divided by total PAI when total is
  positive.
- Ray/QC provenance: box bounds, fixed/estimated `G`, observed rays, hits, full
  gaps, unknowns, pre-box returns, per-layer exposure and hits.
- The current conditional total may be retained temporarily as an explicitly
  named legacy/interval-censored diagnostic, not as another definition of PAI.

Required identities, within numerical tolerance:

\[
\sum_k pai\_layer_k = pai\_m2\_m2,
\qquad
\sum_k pai\_fraction_k = 1.
\]

The dormant binary-only joint-profile fields should not be mixed with these
exact first-event layers under the same generic names.

## 6. Direct answers

1. **Which estimator most faithfully represents total plot PAI?** The exact
   first-event piecewise profile, currently called Z-PAI, provided the box is the
   biological plot and profile-support QC passes.
2. **Which is closest to LAI-2200 theory?** Homogeneous whole-box PAI is the
   closest direct gap/transmission analogue because it uses one canopy density,
   binary transmission, `G`, and exact finite chords. Z-PAI is the principled
   first-event generalization that uses more LiDAR information.
3. **Is conditional integrated PAI defensible?** Yes. It is an interval-censored
   piecewise PAD survival model whose layer contributions sum to total PAI. It
   is not the best use of the available exact return distance.
4. **Can one joint profile estimate total and vertical allocation?** Yes. The
   exact first-event likelihood does both, and the current Z-PAI calculation is
   its closed-form MLE under fixed `G`.
5. **Is it identifiable here?** Total PAI is well supported in the current run;
   every layer has exposure. Layer profiles are practically weaker: 172/546
   targets have one or more zero-hit boundary layers. The dormant whole-box
   binary joint inversion is not established as practically identifiable by its
   rank test and is not recommended.
6. **How should censoring be treated?** Exclude pre-box first returns and
   unknowns, include full gaps as right-censored exposure, and stop within-box
   exposure at the first return. Record all counts. Prevent selective pre-box
   loss mechanically or with valid multi-view geometry; do not redefine the
   biological plot merely to suppress the diagnostic count.
7. **LAI or PAI?** PAI. Stems are a material 16-33% of destructive PAI.
8. **What should columns mean?** One exact total, additive layer contributions
   and fractions from that same model, a clearly labeled homogeneous reference,
   and explicit support/censoring/G/geometry QC.

## Reproducibility and artifacts

Run:

```bash
PYTHONPATH="$PWD" python3 docs/diagnostics/pai_reassessment_2026-09-17/audit.py
```

The script only reads existing outputs and writes this diagnostic directory.
It produces the CSV tables and `pai_estimator_diagnostics.png` used above.
