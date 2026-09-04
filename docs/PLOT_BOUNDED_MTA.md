# Plot-Bounded Mean Tilt Angle (`bounded_lang_v1`)

## Interpretation

This trait is the effective mean tilt angle of LiDAR-intercepting plant elements
within the bounded experimental plot, inferred from the angular dependence of
first-interception frequency per meter of observed ray path.

MTA is reported in degrees from horizontal: 0° is planophile/horizontal and 90°
is erectophile/vertical. It is not a fit to return-point normals. The current
LiDAR records do not distinguish leaves from stems, petioles, or other plant
material, so all detected plant elements may contribute.

## Theoretical connection

The model follows the canopy-transmission relation documented in the
[LI-COR LAI-2200C theory](https://www.licor.com/support/LAI-2200C/topics/theory.html):

\[
P(\theta)=\exp[-\mu G(\theta)S(\theta)],
\]

where `P` is non-interception probability, `mu` is plant-area density,
`G(theta)` is the projection function, and `S` is path length. LI-COR notes
that measured/nonstandard path lengths produce an area-density quantity rather
than the area index associated with the infinite horizontal-slab substitution
`S=h/cos(theta)`. See also LI-COR's
[LAI inversion discussion](https://www.licor.com/support/LAI-2200C/topics/computing-lai.html)
and Lang (1986),
[doi:10.1071/BT9860349](https://doi.org/10.1071/BT9860349).

This implementation uses each ray's actual path through a finite plot box. It
does not substitute scanner height or canopy height for that path.

## Coordinates and bounded volume

Pipeline coordinates are:

- `X`: lateral/left-right;
- `Y`: vertical;
- `Z`: cart travel.

MTA reuses the canonical FAD plot volume, including its configured side:

\[
[x_{min},x_{max}]\times[y_{ground},y_{top}]\times[z_{start},z_{end}].
\]

Thus `fad_x_near_m`, `row_width_u`, the target's Z interval, and the FAD height
settings also define the MTA volume. `y_top` is the existing per-target,
Grubbs-filtered `fad_height_percentile` plus `fad_height_buffer_m`. MTA computes
this geometry even when height and FAD result output are disabled. Bounds are
kept in the optional diagnostic output, not the primary result.

The existing slab ray-box intersection clips rays that begin outside, on, or
inside the box. For an origin inside the box, observed path starts at the
origin (`max(t_entry, 0)`), not at the backward box face.

## Immutable first-event classification

MTA reads the unfiltered fused LiDAR rows. SOR, RSSI, local-ground, and other
point-cloud filters therefore cannot turn a rejected return into a gap.

For each geometrically intersecting emitted ray:

1. A first return before `t_entry` is `before_box`. It contributes neither
   exposure nor an event.
2. A first return from `t_entry` through `t_exit` is a hit. It contributes one
   event and free path `t_return - max(t_entry, 0)`.
3. A first return beyond `t_exit` is a right-censored full gap. It contributes
   path `t_exit - max(t_entry, 0)` and no event.
4. A row explicitly encoded with zero range is a no-return. It is a full gap
   only when `mta_max_observation_range_m` reaches beyond `t_exit`; otherwise it
   is unknown and excluded.
5. Missing rows are never manufactured. Nonzero invalid ranges are unknown.
6. When a caller supplies repeated stable ray IDs, only the earliest finite,
   positive return is retained.

The current logger CSV contains one range per row and no pulse/echo identifier.
The pipeline therefore uses the immutable source-row index as its stable ray
ID. It cannot retrospectively associate multiple echoes that were not retained
by the logger.

## Folded zenith angle

Directions are normalized after the same calibration, IMU, pose, and lever-arm
transform used by bounded FAD. With vertical unit vector along Y:

\[
\theta=\cos^{-1}(|u_y|).
\]

The absolute value folds upward and downward opposing views because an
unoriented surface obeys `|n dot u| = |n dot (-u)|`. The sign of `u_y` is kept
for optional upward-only and downward-only diagnostics. Downward rays
between the approximately 0.40 m scanner height and configured ground boundary
are included; scanner height is not a vegetation cutoff.

Folding assumes one effective orientation distribution in the bounded volume.
Vertical stratification or directional occlusion can violate that assumption.

## Angular bins and first-event rate

Bins cover 0–90° at `mta_angle_bin_deg`. They are half-open `[low, high)`,
except the final bin includes 90°. A partial last bin is retained. The default
is 5°.

For bin `i`, the constant-hazard maximum-likelihood estimate is

\[
\widehat{\lambda_i}=\frac{H_i}{T_i},
\]

where `H_i` is the number of first returns inside the box and `T_i` is summed
observed free path (metres), including right-censored full gaps. Therefore
`lambda` has units `m^-1`. Raw point count is not the denominator.

A bin is exposed when it contains at least 30 observed rays and 1 m of total
observed path. Bin counts, paths, rates, and QC flags are retained only when
`mta_diagnostic: true`.

## Separating amount from orientation

Exact solid-angle weights are

\[
w_i=\cos(\theta_{low})-\cos(\theta_{high}).
\]

They sum to one over 0–90°. Plant-area density is estimated with the Miller
identity:

\[
\widehat\mu=2\sum_iw_i\widehat\lambda_i.
\]

When part of the angular domain is missing, represented weights are explicitly
renormalized by the reported coverage fraction:

\[
\widehat\mu=2\frac{\sum_{i\in valid}w_i\widehat\lambda_i}
{\sum_{i\in valid}w_i}.
\]

Missing regions are never filled with zero; incomplete coverage is recorded as
a diagnostic warning. The directional projection estimate is then

\[
\widehat G_i=\widehat\lambda_i/\widehat\mu.
\]

This normalization is essential: the Lang conversion receives the slope of
`G`, never the density-dependent slope of `lambda`.

## Lang fit and conversion

Equal directional-bin weighting fits

\[
\widehat G_i=a+m_G\theta_i
\]

with bin centers in radians. Fitting bins are constructed separately and
anchored at 25°, so 2.5°, 5°, and 10° widths all cover the complete fixed
25–65° interval. The bounds are fixed for `bounded_lang_v1` because the
empirical Lang relationship was developed there.

The conversion is

\[
MTA=56.81964+46.84833m_G-64.62133m_G^2-158.69141m_G^3
 +522.06260m_G^4+1008.14931m_G^5.
\]

The numerical polynomial result is clipped to 0–90° as in LI-COR's published
implementation. A slope outside the Table J-1 calibration range
`[-0.6964, 0.4431]` is retained as a numeric estimate but marked with a
diagnostic warning. A missing MTA is reserved for cases where the fit cannot be
calculated, such as fewer than two usable angle bins.

## Configuration

```yaml
analysis:
  run_mta: false
  mta_angle_bin_deg: 5.0
  mta_diagnostic: false
```

`mta_angle_bin_deg` accepts any finite positive number, including 2.5, 5, and
10. Internal compatibility settings remain readable, but the standard Lang fit
bounds are fixed at 25° and 65°. `mta_diagnostic` is deliberately off by
default.

Older `mta_lo_deg`, `mta_hi_deg`, and `mta_n_bins` YAML keys remain readable.
New configs should use only the three fields above.

## Outputs and QC

The normal one-row-per-target result contains `mta_deg` and `mta_qc_pass`.
Method, coverage, fit, and ray-classification values remain internal or are
written to the diagnostic file. Legacy `lai_mta_*` values may remain internal
but are not written to the graph-ready CSV.

With `mta_diagnostic: true`, the parent process writes one aggregate
`mta_diagnostics.csv`. It contains the angular-bin, fit, ray-classification,
coverage, and box fields needed for auditing, together with `experiment`,
`date`, `scan_name`, `scan_number`, `plot`, and `side`. Diagnostics do not alter
the calculation or the primary schema. No MTA diagnostic file is created when
the toggle is false.

The standard QC prefers at least 30 observed rays and 1 m of path per valid
bin, at least three fit bins, strong hemispherical solid-angle coverage, and a
slope within the calibration range. A calculable result is retained and marked
as a warning if those preferred criteria are not met. A finite positive density
and at least two usable fit bins are still required to calculate MTA.

Statuses include `ok`, `invalid_plot_volume`, `no_rays_intersect_box`,
`insufficient_observed_path`, `insufficient_angular_coverage`, `nonpositive_mu`,
`too_few_fit_bins`, `singular_fit`, and `slope_outside_calibration_range`.

## Assumptions and limitations

- Plant elements are small relative to the sampled volume.
- Directional first-event rates follow the Beer–Lambert/contact-frequency model.
- One effective orientation distribution represents the bounded volume.
- Plant-element azimuth is random or adequately averaged by scan geometry.
- Clumping, vertical stratification, nonrandom arrangement,
  reflectance-dependent detection, and occlusion may bias the result.
- First-event censoring handles known path hidden beyond an interception but
  does not make a heterogeneous canopy homogeneous.
- All intercepted plant elements contribute; this is not pure leaf inclination.
- Upward/downward subset agreement is a diagnostic, not proof of model validity.
- Ray-level fit residuals do not represent biological uncertainty. Repeated plot
  scans or a defensible clustered bootstrap should support paper uncertainty.

## Draft methods wording (pending field validation)

> Effective plant-element mean tilt angle was inferred within each finite plot
> volume from first-return LiDAR contact frequency. Raw emitted rays were
> intersected with the side- and mark-bounded three-dimensional plot box, and
> first returns before entry were excluded. Returns within the box contributed
> one interception and exposure up to the return; rays known to traverse the
> box contributed right-censored full-chord exposure. Directional interception
> rates were estimated as events per metre of observed path in 5° folded-zenith
> bins. Plant-area density was separated using exact Miller solid-angle weights,
> and the slope of the normalized projection function over 25–65° was converted
> to effective MTA using the Lang/LI-COR fifth-order polynomial. Results failing
> preferred coverage or slope-calibration criteria were retained with diagnostic
> warnings; estimates were omitted only when the fit could not be calculated.
