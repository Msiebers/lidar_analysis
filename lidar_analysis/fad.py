from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import math

import numpy as np


@dataclass(frozen=True)
class Box3D:
    """
    Axis-aligned FAD volume in meters.

    Coordinate convention should match the transformed LiDAR point cloud:
        x = left/right
        y = vertical
        z = forward / along plot
    """
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


@dataclass(frozen=True)
class HeightResult:
    """
    Robust canopy-height result used to define the FAD y-extent.

    height_m:
        Requested percentile of Grubbs-filtered Y values, in meters.

    y_max_m:
        FAD box top. By default this is exactly height_m because buffer_m
        defaults to zero.

    n_removed:
        Number of Y values removed by the Grubbs filter.
    """
    height_m: float
    y_max_m: float
    percentile: float
    buffer_m: float
    n_input: int
    n_used: int
    n_removed: int


@dataclass(frozen=True)
class FadResult:
    """
    Whole-box apparent foliage/plant area density result.

    fad_m2_m3:
        Apparent foliage/plant area density after G-function correction.
        Units are m^2 m^-3 when interceptions represent one-sided leaf area.

    contact_density_m_inv:
        Interceptions per meter of observed free ray path, before G correction.

    gap_fraction:
        Fraction of usable observed rays that crossed the whole box without a
        first return inside the box (ray-count gap fraction; reported as a
        diagnostic, not used directly in the FAD estimate).

    n_hits_inside_box:
        Number of raw first returns inside the FAD box. For this apparent-FAD
        implementation, every raw first return inside the canopy volume counts
        as an interception.
    """
    fad_m2_m3: float
    contact_density_m_inv: float
    gap_fraction: float

    n_rays_total: int
    n_rays_intersecting_box: int
    n_rays_observed_in_box: int
    n_hits_inside_box: int
    n_full_gaps_through_box: int
    n_hits_before_box: int

    total_free_path_length_m: float
    total_projected_path_length_m: float

    box: Box3D
    g_assumption: str


@dataclass(frozen=True)
class LayeredFadResult:
    """
    Vertical FAD profile from repeated FAD estimates in y-slices.
    """
    layer_edges_y_m: np.ndarray
    layer_centers_y_m: np.ndarray
    layer_thickness_m: np.ndarray

    fad_m2_m3: np.ndarray
    contact_density_m_inv: np.ndarray
    gap_fraction: np.ndarray

    n_rays_observed_in_box: np.ndarray
    n_hits_inside_box: np.ndarray
    n_full_gaps_through_box: np.ndarray
    total_free_path_length_m: np.ndarray
    total_projected_path_length_m: np.ndarray

    lai_from_fad: float


def _as_array_2d(name: str, value: np.ndarray, ncols: int = 3) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != ncols:
        raise ValueError(f"{name} must have shape n x {ncols}; got {arr.shape}")
    return arr


def _as_array_1d(name: str, value: np.ndarray, n: int | None = None) -> np.ndarray:
    arr = np.asarray(value)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1D array; got {arr.shape}")
    if n is not None and arr.shape[0] != n:
        raise ValueError(f"{name} must have length {n}; got {arr.shape[0]}")
    return arr


def _normalize_directions(directions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Normalize ray directions to unit length, robustly.

    Returns (unit_directions, valid_mask). Rays with non-finite or zero-length
    directions are flagged invalid and replaced with a finite placeholder so
    downstream geometry stays numerically well-behaved; callers must exclude
    them via the returned mask. This avoids letting a single malformed ray
    abort an entire plot, while keeping per-ray index alignment with
    origins/ranges/hit-mask intact.
    """
    directions = _as_array_2d("directions_m", directions)
    norms = np.linalg.norm(directions, axis=1)

    valid = np.isfinite(norms) & (norms > 0.0)
    safe_norms = np.where(valid, norms, 1.0)
    unit = directions / safe_norms[:, None]

    # Replace invalid rows with a placeholder unit vector; excluded later.
    if not np.all(valid):
        unit[~valid] = np.array([0.0, 0.0, 1.0], dtype=float)

    return unit, valid


def _mad_filter_1d(values: np.ndarray, *, z_thresh: float = 3.5) -> np.ndarray:
    """
    Median absolute deviation fallback filter for 1D values.

    This is only used if scipy is unavailable for the Grubbs critical value.
    The public FAD height method is still conceptually a Grubbs-filtered height.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)].copy()

    if x.size < 3:
        return x

    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))

    if not np.isfinite(mad) or mad <= 0.0:
        return x

    robust_z = 0.6745 * (x - med) / mad
    return x[np.abs(robust_z) <= float(z_thresh)]


def _grubbs_filter_1d(
    values: np.ndarray,
    *,
    alpha: float = 0.01,
    max_iter: int = 20,
) -> np.ndarray:
    """
    Iterative two-sided Grubbs outlier filter.

    Removes one extreme value at a time while the Grubbs statistic exceeds the
    critical value. If scipy is unavailable, falls back to a MAD filter so the
    pipeline can still run.

    Note: on large point clouds this removes at most `max_iter` points and is
    largely subsumed by the high percentile taken downstream; it is retained
    only as light hygiene against a few extreme fliers. See
    `estimate_fad_height_from_y` for the height definition.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)].copy()

    if x.size < 3:
        return x

    try:
        from scipy import stats
    except Exception:
        return _mad_filter_1d(x)

    alpha = float(alpha)
    max_iter = int(max_iter)

    if not np.isfinite(alpha) or alpha <= 0.0 or alpha >= 1.0:
        raise ValueError(f"alpha must be between 0 and 1; got {alpha}")

    for _ in range(max_iter):
        n = x.size
        if n < 3:
            break

        mean = float(np.mean(x))
        sd = float(np.std(x, ddof=1))

        if not np.isfinite(sd) or sd <= 0.0:
            break

        abs_dev = np.abs(x - mean)
        idx = int(np.argmax(abs_dev))
        g = float(abs_dev[idx] / sd)

        tcrit = float(stats.t.ppf(1.0 - alpha / (2.0 * n), n - 2))
        if not np.isfinite(tcrit):
            break

        numerator = (n - 1.0) * math.sqrt(tcrit * tcrit)
        denominator = math.sqrt(n) * math.sqrt(n - 2.0 + tcrit * tcrit)
        gcrit = numerator / denominator

        if g > gcrit:
            x = np.delete(x, idx)
        else:
            break

    return x


def estimate_fad_height_from_y(
    y_m: np.ndarray,
    *,
    percentile: float = 99.0,
    y_min_m: float = 0.03,
    buffer_m: float = 0.0,
    grubbs_alpha: float = 0.01,
) -> HeightResult:
    """
    Estimate canopy height for the FAD box from Y values.

    Default interpretation:
        1. keep finite Y values at or above y_min_m
        2. remove extreme Y outliers with iterative Grubbs
        3. take the configured percentile, default 99
        4. use that value as the FAD y_max

    buffer_m defaults to 0.0. It exists only as an escape hatch; the default
    theoretical trait is percentile-defined height with no added padding.

    Empty / all-filtered inputs return a HeightResult with NaN height so the
    caller can detect an empty plot before building a box (see `box_is_valid`).
    """
    y = np.asarray(y_m, dtype=float)
    y = y[np.isfinite(y) & (y >= float(y_min_m))]

    n_input = int(y.size)

    if n_input == 0:
        return HeightResult(
            height_m=float("nan"),
            y_max_m=float("nan"),
            percentile=float(percentile),
            buffer_m=float(buffer_m),
            n_input=0,
            n_used=0,
            n_removed=0,
        )

    pct = float(percentile)
    if not np.isfinite(pct) or pct <= 0.0 or pct > 100.0:
        raise ValueError(f"percentile must be in (0, 100]; got {percentile}")

    y_used = _grubbs_filter_1d(y, alpha=float(grubbs_alpha))

    if y_used.size == 0:
        height_m = float("nan")
    else:
        height_m = float(np.percentile(y_used, pct))

    y_max_m = (
        float(height_m + float(buffer_m))
        if np.isfinite(height_m)
        else float("nan")
    )

    return HeightResult(
        height_m=height_m,
        y_max_m=y_max_m,
        percentile=pct,
        buffer_m=float(buffer_m),
        n_input=n_input,
        n_used=int(y_used.size),
        n_removed=int(n_input - y_used.size),
    )


def estimate_fad_height_from_points(
    points_xyz_m: np.ndarray,
    *,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    z_min_m: float | None = None,
    z_max_m: float | None = None,
    percentile: float = 99.0,
    y_min_m: float = 0.03,
    buffer_m: float = 0.0,
    grubbs_alpha: float = 0.01,
) -> HeightResult:
    """
    Estimate FAD canopy height from points, optionally restricted to an X/Z
    footprint.

    points_xyz_m must be in meters and have columns X, Y, Z.

    If pipeline_core.py passes points that are already masked to the plot,
    x/z bounds can be omitted. If not, pass x_min/x_max/z_min/z_max.
    """
    pts = _as_array_2d("points_xyz_m", points_xyz_m)

    mask = np.ones(pts.shape[0], dtype=bool)

    if x_min_m is not None:
        mask &= pts[:, 0] >= float(x_min_m)
    if x_max_m is not None:
        mask &= pts[:, 0] <= float(x_max_m)
    if z_min_m is not None:
        mask &= pts[:, 2] >= float(z_min_m)
    if z_max_m is not None:
        mask &= pts[:, 2] <= float(z_max_m)

    return estimate_fad_height_from_y(
        pts[mask, 1],
        percentile=percentile,
        y_min_m=y_min_m,
        buffer_m=buffer_m,
        grubbs_alpha=grubbs_alpha,
    )


def make_fad_box_from_footprint_and_height(
    *,
    x_min_m: float,
    x_max_m: float,
    z_min_m: float,
    z_max_m: float,
    height: HeightResult,
    y_min_m: float = 0.03,
) -> Box3D:
    """
    Build the FAD Box3D from X/Z footprint bounds and a HeightResult.

    The returned box may be invalid (e.g. NaN y_max for an empty plot). Check
    with `box_is_valid` before passing it to the geometry routines; the trait
    wrapper `compute_fad_traits` does this automatically.
    """
    return Box3D(
        x_min=float(x_min_m),
        x_max=float(x_max_m),
        y_min=float(y_min_m),
        y_max=float(height.y_max_m),
        z_min=float(z_min_m),
        z_max=float(z_max_m),
    )


def box_is_valid(box: Box3D) -> bool:
    """
    Non-raising validity check: all bounds finite and strictly ordered.

    Use this to detect empty/degenerate plots (e.g. NaN y_max) before calling
    the geometry routines, which raise on invalid boxes.
    """
    vals = np.array(
        [box.x_min, box.x_max, box.y_min, box.y_max, box.z_min, box.z_max],
        dtype=float,
    )
    if not np.all(np.isfinite(vals)):
        return False
    return (box.x_max > box.x_min) and (box.y_max > box.y_min) and (box.z_max > box.z_min)


def validate_box(box: Box3D) -> None:
    if not box_is_valid(box):
        raise ValueError(f"Invalid FAD box (non-finite or unordered bounds): {box}")


def ray_box_intersection(
    *,
    origins_m: np.ndarray,
    directions_unit: np.ndarray,
    box: Box3D,
    eps: float = 1e-12,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Intersect rays with an axis-aligned box (slab method).

    directions_unit must be unit vectors, so returned t-values are distances
    in meters.
    """
    validate_box(box)

    origins_m = _as_array_2d("origins_m", origins_m)
    directions_unit = _as_array_2d("directions_unit", directions_unit)

    if origins_m.shape != directions_unit.shape:
        raise ValueError(
            "origins_m and directions_unit must have the same shape; "
            f"got {origins_m.shape} and {directions_unit.shape}"
        )

    bounds_min = np.array([box.x_min, box.y_min, box.z_min], dtype=float)
    bounds_max = np.array([box.x_max, box.y_max, box.z_max], dtype=float)

    n = origins_m.shape[0]
    t_min_axis = np.full((n, 3), -np.inf, dtype=float)
    t_max_axis = np.full((n, 3), np.inf, dtype=float)
    valid = np.ones(n, dtype=bool)

    for axis in range(3):
        o = origins_m[:, axis]
        d = directions_unit[:, axis]
        lo = bounds_min[axis]
        hi = bounds_max[axis]

        parallel = np.abs(d) < eps

        outside_parallel = parallel & ((o < lo) | (o > hi))
        valid[outside_parallel] = False

        non_parallel = ~parallel

        t1 = np.full(n, -np.inf, dtype=float)
        t2 = np.full(n, np.inf, dtype=float)

        t1[non_parallel] = (lo - o[non_parallel]) / d[non_parallel]
        t2[non_parallel] = (hi - o[non_parallel]) / d[non_parallel]

        t_min_axis[:, axis] = np.minimum(t1, t2)
        t_max_axis[:, axis] = np.maximum(t1, t2)

    t_enter = np.max(t_min_axis, axis=1)
    t_exit = np.min(t_max_axis, axis=1)

    intersects = valid
    intersects &= np.isfinite(t_enter)
    intersects &= np.isfinite(t_exit)
    intersects &= t_exit > np.maximum(t_enter, 0.0)

    return t_enter, t_exit, intersects


def g_spherical(directions_unit: np.ndarray) -> np.ndarray:
    """
    Spherical leaf-angle distribution assumption.

    Under the spherical leaf-angle assumption, G(theta) = 0.5 and is
    independent of view angle.
    """
    directions_unit = _as_array_2d("directions_unit", directions_unit)
    return np.full(directions_unit.shape[0], 0.5, dtype=float)


def resolve_g_function(
    g_function: str | Callable[[np.ndarray], np.ndarray],
) -> tuple[str, Callable[[np.ndarray], np.ndarray]]:
    """
    Resolve the projection function used to convert contact density to FAD.

    Currently supported string:
        "spherical" -> G(theta) = 0.5
    """
    if callable(g_function):
        return "custom", g_function

    name = str(g_function).strip().lower()

    if name in {"spherical", "sphere", "g_0.5", "0.5"}:
        return "spherical", g_spherical

    raise ValueError(
        f"Unsupported g_function {g_function!r}. "
        "Currently supported: 'spherical', or pass a callable."
    )


def _empty_fad_result(box: Box3D, g_name: str, n_total: int = 0) -> FadResult:
    """All-NaN/zero result for an empty plot or invalid box."""
    return FadResult(
        fad_m2_m3=float("nan"),
        contact_density_m_inv=float("nan"),
        gap_fraction=float("nan"),
        n_rays_total=int(n_total),
        n_rays_intersecting_box=0,
        n_rays_observed_in_box=0,
        n_hits_inside_box=0,
        n_full_gaps_through_box=0,
        n_hits_before_box=0,
        total_free_path_length_m=0.0,
        total_projected_path_length_m=0.0,
        box=box,
        g_assumption=g_name,
    )


def compute_fad_in_box(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    raw_hit_mask: np.ndarray,
    box: Box3D,
    g_function: str | Callable[[np.ndarray], np.ndarray] = "spherical",
    min_free_path_m: float = 1e-6,
    hit_tolerance_m: float = 1e-4,
) -> FadResult:
    """
    Estimate apparent foliage/plant area density inside one FAD box.

    This is a ray-path / contact-frequency estimator, not a point-density
    estimator.

    Ray classification
    ------------------
    A ray "has a return" if raw_hit_mask is True and its range is finite and
    positive. No-return rays (raw_hit_mask False, or non-finite range) are
    legitimate full gaps, not missing data.

    occluded before box:
        Has a return whose range is short of box entry -> excluded (the beam
        was blocked before sampling this plot volume).

    hit inside box:
        Has a return that lands between entry and exit -> interception.
        Free path = entry .. hit. Every such raw first return counts as an
        interception (apparent-FAD assumption).

    full gap:
        Any sampling ray that is not a hit inside the box -> i.e. no return at
        all, or a return beyond the far face. Free path = entry .. exit.

    Theory
    ------
    For a beam crossing the canopy volume, P_gap = exp(-G(theta) * FAD * L).
    The maximum-likelihood / contact-frequency estimator is:

        FAD = n_hits / sum_i ( G(theta_i) * free_path_i )

    where the sum runs over all usable (occlusion-free, box-sampling) rays.
    """
    origins_m = _as_array_2d("origins_m", origins_m)
    directions_unit, valid_dir = _normalize_directions(directions_m)

    if origins_m.shape != directions_unit.shape:
        raise ValueError(
            "origins_m and directions_m must have the same shape; "
            f"got {origins_m.shape} and {directions_unit.shape}"
        )

    n = origins_m.shape[0]

    ranges_m = _as_array_1d("ranges_m", ranges_m, n=n).astype(float)
    raw_hit_mask = _as_array_1d("raw_hit_mask", raw_hit_mask, n=n).astype(bool)

    g_name, g_callable = resolve_g_function(g_function)

    # A usable first return: the beam stopped at a finite, positive range.
    has_return = raw_hit_mask & np.isfinite(ranges_m) & (ranges_m > 0.0)

    t_enter, t_exit, intersects = ray_box_intersection(
        origins_m=origins_m,
        directions_unit=directions_unit,
        box=box,
    )
    intersects = intersects & valid_dir  # drop malformed-direction rays

    entry = np.maximum(t_enter, 0.0)

    # Occluded before box entry -> no information about the box interior.
    occluded_before_box = (
        intersects & has_return & (ranges_m < entry - hit_tolerance_m)
    )

    # Rays that actually probe the box volume.
    sampling = intersects & (~occluded_before_box)

    # First return inside the box -> interception.
    hits_inside = sampling & has_return & (ranges_m <= t_exit + hit_tolerance_m)

    # Everything else that samples the box is a full gap:
    #   - no return at all, or
    #   - first return beyond the far face.
    full_gaps = sampling & (~hits_inside)

    # Free path length: hit -> entry..hit ; gap -> entry..exit.
    path_end = np.where(hits_inside, ranges_m, t_exit)
    free_path = np.clip(path_end - entry, 0.0, None)

    # Per-ray projection coefficient.
    g_values = np.asarray(g_callable(directions_unit), dtype=float)
    if g_values.shape != (n,):
        raise ValueError(
            "g_function must return a 1D array with length n_rays; "
            f"got {g_values.shape}"
        )
    valid_g = np.isfinite(g_values) & (g_values > 0.0)

    # Usable rays: sample the box, have a meaningful path, and a valid G.
    usable = sampling & (free_path > float(min_free_path_m)) & valid_g

    n_hits = int(np.sum(hits_inside & usable))
    total_free_path = float(np.sum(free_path[usable]))
    total_projected_path = float(np.sum(g_values[usable] * free_path[usable]))

    contact_density = (
        float(n_hits / total_free_path) if total_free_path > 0.0 else float("nan")
    )
    fad = (
        float(n_hits / total_projected_path)
        if total_projected_path > 0.0
        else float("nan")
    )

    n_observed = int(np.sum(usable))
    n_full_gaps = int(np.sum(full_gaps & usable))
    gap_fraction = (
        float(n_full_gaps / n_observed) if n_observed > 0 else float("nan")
    )

    return FadResult(
        fad_m2_m3=fad,
        contact_density_m_inv=contact_density,
        gap_fraction=gap_fraction,
        n_rays_total=int(n),
        n_rays_intersecting_box=int(np.sum(intersects)),
        n_rays_observed_in_box=n_observed,
        n_hits_inside_box=n_hits,
        n_full_gaps_through_box=n_full_gaps,
        n_hits_before_box=int(np.sum(occluded_before_box)),
        total_free_path_length_m=total_free_path,
        total_projected_path_length_m=total_projected_path,
        box=box,
        g_assumption=g_name,
    )


def make_layer_edges(
    *,
    y_min_m: float,
    y_max_m: float,
    layer_thickness_m: float,
) -> np.ndarray:
    """
    Build vertical layer edges from y_min to y_max.

    The final layer edge is forced to equal y_max_m, so the last layer may be
    slightly thinner than layer_thickness_m.
    """
    y_min_m = float(y_min_m)
    y_max_m = float(y_max_m)
    layer_thickness_m = float(layer_thickness_m)

    if not np.isfinite(y_min_m) or not np.isfinite(y_max_m):
        raise ValueError("Layer y_min_m and y_max_m must be finite.")

    if y_max_m <= y_min_m:
        raise ValueError(
            f"Layer y_max_m must be greater than y_min_m; got {y_min_m}, {y_max_m}"
        )

    if not np.isfinite(layer_thickness_m) or layer_thickness_m <= 0.0:
        raise ValueError(f"layer_thickness_m must be > 0; got {layer_thickness_m}")

    edges = list(np.arange(y_min_m, y_max_m, layer_thickness_m, dtype=float))
    if not edges or not math.isclose(edges[0], y_min_m):
        edges.insert(0, y_min_m)

    if edges[-1] < y_max_m:
        edges.append(y_max_m)
    else:
        edges[-1] = y_max_m

    # Remove accidental duplicates from floating-point roundoff.
    clean = [edges[0]]
    for e in edges[1:]:
        if e > clean[-1] + 1e-12:
            clean.append(e)

    return np.asarray(clean, dtype=float)


def compute_layered_fad(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    raw_hit_mask: np.ndarray,
    base_box: Box3D,
    layer_edges_y_m: np.ndarray,
    g_function: str | Callable[[np.ndarray], np.ndarray] = "spherical",
    min_free_path_m: float = 1e-6,
    hit_tolerance_m: float = 1e-4,
) -> LayeredFadResult:
    """
    Estimate a vertical FAD profile by slicing base_box along the y-axis.

    The implied canopy area index / LAI-like integral is:

        sum(FAD_layer * layer_thickness)

    Layers with no usable rays yield NaN FAD and are treated as 0 in that
    integral (nansum). Inspect the per-layer observed-ray counts before
    trusting the integral when upper layers are sparsely sampled.
    """
    validate_box(base_box)

    layer_edges_y_m = np.asarray(layer_edges_y_m, dtype=float)

    if layer_edges_y_m.ndim != 1 or layer_edges_y_m.size < 2:
        raise ValueError("layer_edges_y_m must be a 1D array with at least two edges.")

    if not np.all(np.isfinite(layer_edges_y_m)):
        raise ValueError("layer_edges_y_m must be finite.")

    if not np.all(np.diff(layer_edges_y_m) > 0.0):
        raise ValueError("layer_edges_y_m must be strictly increasing.")

    results: list[FadResult] = []

    for y0, y1 in zip(layer_edges_y_m[:-1], layer_edges_y_m[1:]):
        layer_box = Box3D(
            x_min=base_box.x_min,
            x_max=base_box.x_max,
            y_min=float(y0),
            y_max=float(y1),
            z_min=base_box.z_min,
            z_max=base_box.z_max,
        )

        results.append(
            compute_fad_in_box(
                origins_m=origins_m,
                directions_m=directions_m,
                ranges_m=ranges_m,
                raw_hit_mask=raw_hit_mask,
                box=layer_box,
                g_function=g_function,
                min_free_path_m=min_free_path_m,
                hit_tolerance_m=hit_tolerance_m,
            )
        )

    fad = np.array([r.fad_m2_m3 for r in results], dtype=float)
    contact = np.array([r.contact_density_m_inv for r in results], dtype=float)
    gap = np.array([r.gap_fraction for r in results], dtype=float)

    n_observed = np.array([r.n_rays_observed_in_box for r in results], dtype=int)
    n_hits = np.array([r.n_hits_inside_box for r in results], dtype=int)
    n_full_gaps = np.array([r.n_full_gaps_through_box for r in results], dtype=int)

    free_path = np.array([r.total_free_path_length_m for r in results], dtype=float)
    projected_path = np.array([r.total_projected_path_length_m for r in results], dtype=float)

    layer_thickness = np.diff(layer_edges_y_m)

    lai_from_fad = float(np.nansum(fad * layer_thickness))

    return LayeredFadResult(
        layer_edges_y_m=layer_edges_y_m,
        layer_centers_y_m=(layer_edges_y_m[:-1] + layer_edges_y_m[1:]) / 2.0,
        layer_thickness_m=layer_thickness,
        fad_m2_m3=fad,
        contact_density_m_inv=contact,
        gap_fraction=gap,
        n_rays_observed_in_box=n_observed,
        n_hits_inside_box=n_hits,
        n_full_gaps_through_box=n_full_gaps,
        total_free_path_length_m=free_path,
        total_projected_path_length_m=projected_path,
        lai_from_fad=lai_from_fad,
    )


def height_result_to_traits(
    result: HeightResult,
    *,
    prefix: str = "fad",
) -> dict[str, Any]:
    """
    Convert FAD height result to flat result-row traits.
    """
    p = prefix.rstrip("_")
    return {
        f"{p}_height_m": result.height_m,
        f"{p}_height_y_max_m": result.y_max_m,
        f"{p}_height_percentile": result.percentile,
        f"{p}_height_buffer_m": result.buffer_m,
        f"{p}_height_filter": "grubbs",
        f"{p}_height_n_input": result.n_input,
        f"{p}_height_n_used": result.n_used,
        f"{p}_height_n_removed": result.n_removed,
    }


def fad_result_to_traits(result: FadResult, *, prefix: str = "fad") -> dict[str, Any]:
    """
    Convert a whole-box FAD result to flat result-row traits.
    """
    p = prefix.rstrip("_")

    return {
        f"{p}_app_m2_m3": result.fad_m2_m3,
        f"{p}_contact_density_m_inv": result.contact_density_m_inv,
        f"{p}_gap_fraction": result.gap_fraction,

        f"{p}_n_rays_total": result.n_rays_total,
        f"{p}_n_rays_intersecting_box": result.n_rays_intersecting_box,
        f"{p}_n_rays_observed": result.n_rays_observed_in_box,
        f"{p}_n_hits": result.n_hits_inside_box,
        f"{p}_n_full_gaps": result.n_full_gaps_through_box,
        f"{p}_n_hits_before_box": result.n_hits_before_box,

        f"{p}_total_free_path_m": result.total_free_path_length_m,
        f"{p}_total_projected_path_m": result.total_projected_path_length_m,

        f"{p}_x_min_m": result.box.x_min,
        f"{p}_x_max_m": result.box.x_max,
        f"{p}_y_min_m": result.box.y_min,
        f"{p}_y_max_m": result.box.y_max,
        f"{p}_z_min_m": result.box.z_min,
        f"{p}_z_max_m": result.box.z_max,

        f"{p}_g_assumption": result.g_assumption,
    }


def layered_fad_result_to_traits(
    result: LayeredFadResult,
    *,
    prefix: str = "fad",
    include_layer_columns: bool = True,
) -> dict[str, Any]:
    """
    Convert layered FAD result to flat result-row traits.

    By default, this writes wide columns like:
        fad_layer_003_010_m2_m3
        fad_layer_010_020_m2_m3

    The layer labels are based on centimeters, so keep layer thickness on clean
    centimeter boundaries to avoid label collisions across plots.
    """
    p = prefix.rstrip("_")

    traits: dict[str, Any] = {
        f"{p}_lai_from_layers": result.lai_from_fad,
        f"{p}_n_layers": int(result.fad_m2_m3.size),
    }

    if not include_layer_columns:
        return traits

    for i, (y0, y1) in enumerate(zip(result.layer_edges_y_m[:-1], result.layer_edges_y_m[1:])):
        cm0 = int(round(float(y0) * 100.0))
        cm1 = int(round(float(y1) * 100.0))
        label = f"{cm0:03d}_{cm1:03d}"

        traits[f"{p}_layer_{label}_m2_m3"] = float(result.fad_m2_m3[i])
        traits[f"{p}_layer_{label}_path_m"] = float(result.total_free_path_length_m[i])
        traits[f"{p}_layer_{label}_hits"] = int(result.n_hits_inside_box[i])
        traits[f"{p}_layer_{label}_observed_rays"] = int(result.n_rays_observed_in_box[i])

    return traits


def compute_fad_traits(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    raw_hit_mask: np.ndarray,
    box: Box3D,
    g_function: str | Callable[[np.ndarray], np.ndarray] = "spherical",
    layer_thickness_m: float | None = 0.10,
    include_layer_columns: bool = True,
    prefix: str = "fad",
) -> dict[str, Any]:
    """
    Convenience wrapper that returns a flat trait dictionary.

    pipeline_core.py should prepare plot-specific rays, raw_hit_mask, and the
    FAD box, then call this function.

    If the box is invalid (e.g. NaN y_max from an empty plot), this returns a
    NaN/zero whole-box trait row and skips the layered columns rather than
    raising, so a single empty plot does not abort the batch.
    """
    g_name, _ = resolve_g_function(g_function)

    n_total = int(np.asarray(origins_m).shape[0]) if np.asarray(origins_m).ndim == 2 else 0

    if not box_is_valid(box):
        whole = _empty_fad_result(box, g_name, n_total=n_total)
        return fad_result_to_traits(whole, prefix=prefix)

    whole = compute_fad_in_box(
        origins_m=origins_m,
        directions_m=directions_m,
        ranges_m=ranges_m,
        raw_hit_mask=raw_hit_mask,
        box=box,
        g_function=g_function,
    )

    traits = fad_result_to_traits(whole, prefix=prefix)

    if layer_thickness_m is not None:
        layer_thickness_m = float(layer_thickness_m)
        if np.isfinite(layer_thickness_m) and layer_thickness_m > 0.0:
            edges = make_layer_edges(
                y_min_m=box.y_min,
                y_max_m=box.y_max,
                layer_thickness_m=layer_thickness_m,
            )
            layered = compute_layered_fad(
                origins_m=origins_m,
                directions_m=directions_m,
                ranges_m=ranges_m,
                raw_hit_mask=raw_hit_mask,
                base_box=box,
                layer_edges_y_m=edges,
                g_function=g_function,
            )
            traits.update(
                layered_fad_result_to_traits(
                    layered,
                    prefix=prefix,
                    include_layer_columns=include_layer_columns,
                )
            )

    return traits