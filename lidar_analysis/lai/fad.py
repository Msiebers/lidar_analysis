from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Box3D:
    """
    Axis-aligned canopy/plot box in meters.

    Coordinate convention should match the transformed point cloud:
        x = left/right
        y = vertical
        z = forward/along plot
    """
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


@dataclass(frozen=True)
class FadResult:
    fad_m2_m3: float
    contact_density_m_inv: float
    gap_fraction: float
    n_rays_intersecting_box: int
    n_rays_observed_in_box: int
    n_hits_inside_box: int
    n_full_gaps_through_box: int
    n_hits_before_box: int
    n_censored_inside_box: int
    total_free_path_length_m: float
    total_projected_path_length_m: float
    g_assumption: str


def _as_array_2d(name: str, value: np.ndarray, ncols: int = 3) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != ncols:
        raise ValueError(f"{name} must have shape n x {ncols}")
    return arr


def _normalize_directions(directions: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(directions, axis=1)
    bad = ~np.isfinite(norms) | (norms <= 0)
    if np.any(bad):
        raise ValueError("All ray directions must be finite non-zero vectors.")
    return directions / norms[:, None]


def ray_box_intersection(
    *,
    origins_m: np.ndarray,
    directions_unit: np.ndarray,
    box: Box3D,
    eps: float = 1e-12,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Intersect rays with an axis-aligned box.

    Returns:
        t_enter:
            Distance along ray to box entry, meters.

        t_exit:
            Distance along ray to box exit, meters.

        intersects:
            Boolean mask for rays that intersect the box in front of the origin.

    directions_unit must be unit vectors so that t is in meters.
    """
    origins_m = _as_array_2d("origins_m", origins_m)
    directions_unit = _as_array_2d("directions_unit", directions_unit)

    if origins_m.shape != directions_unit.shape:
        raise ValueError("origins_m and directions_unit must have the same shape")

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

        # Parallel rays only intersect the slab if already inside it.
        outside_parallel = parallel & ((o < lo) | (o > hi))
        valid[outside_parallel] = False

        non_parallel = ~parallel
        t1 = np.empty(n, dtype=float)
        t2 = np.empty(n, dtype=float)
        t1[:] = -np.inf
        t2[:] = np.inf

        t1[non_parallel] = (lo - o[non_parallel]) / d[non_parallel]
        t2[non_parallel] = (hi - o[non_parallel]) / d[non_parallel]

        t_min_axis[:, axis] = np.minimum(t1, t2)
        t_max_axis[:, axis] = np.maximum(t1, t2)

    t_enter = np.max(t_min_axis, axis=1)
    t_exit = np.min(t_max_axis, axis=1)

    intersects = valid & np.isfinite(t_enter) & np.isfinite(t_exit)
    intersects &= t_exit > np.maximum(t_enter, 0.0)

    return t_enter, t_exit, intersects


def spherical_g_function(directions_unit: np.ndarray) -> np.ndarray:
    """
    Spherical leaf-angle distribution assumption.

    For a spherical leaf-angle distribution, G(theta) is conventionally 0.5
    and independent of view angle.
    """
    return np.full(directions_unit.shape[0], 0.5, dtype=float)


def compute_fad_in_box(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    hit_mask: np.ndarray,
    box: Box3D,
    g_function: str = "spherical",
    min_free_path_m: float = 1e-6,
    hit_tolerance_m: float = 1e-4,
) -> FadResult:
    """
    Estimate apparent foliage/plant area density inside a plot/canopy box.

    Parameters
    ----------
    origins_m:
        n x 3 ray origins in transformed plot coordinates.

    directions_m:
        n x 3 ray direction vectors in the same coordinate system.
        They do not need to be unit length; this function normalizes them.

    ranges_m:
        n measured first-return ranges, in meters.
        For no-return/max-range rays, use the sensor max range or the recorded
        max-distance value.

    hit_mask:
        n boolean array.
        True = the range is an actual first return.
        False = no return / max range / valid non-hit ray.

    box:
        Plot/canopy bounding box.

    g_function:
        Currently only "spherical" is implemented. This gives G(theta)=0.5.

    Returns
    -------
    FadResult:
        fad_m2_m3 is apparent FAD under the selected G assumption.
        contact_density_m_inv is hits per meter of free path before G correction.

    Theory
    ------
    This treats beam interception as a survival/contact-frequency process.

    For a ray segment crossing the canopy volume:
        no-hit probability = exp(-G(theta) * FAD * path_length)

    The maximum-likelihood estimator is:
        FAD = n_hits / sum(G(theta_i) * free_path_length_i)

    For hit rays, free_path_length is only the distance from box entry to
    first return. For non-hit rays, it is the observed path through the box.
    """
    origins_m = _as_array_2d("origins_m", origins_m)
    directions_unit = _normalize_directions(_as_array_2d("directions_m", directions_m))

    ranges_m = np.asarray(ranges_m, dtype=float)
    hit_mask = np.asarray(hit_mask, dtype=bool)

    n = origins_m.shape[0]

    if ranges_m.ndim != 1 or ranges_m.shape[0] != n:
        raise ValueError("ranges_m must be a 1D array with length n_rays")

    if hit_mask.ndim != 1 or hit_mask.shape[0] != n:
        raise ValueError("hit_mask must be a 1D boolean array with length n_rays")

    finite_range = np.isfinite(ranges_m) & (ranges_m > 0)

    t_enter, t_exit, intersects = ray_box_intersection(
        origins_m=origins_m,
        directions_unit=directions_unit,
        box=box,
    )

    entry = np.maximum(t_enter, 0.0)

    # Rays with a first return before the canopy box are occluded before
    # sampling this box. They should not count as gaps or hits for this box.
    hits_before_box = intersects & finite_range & hit_mask & (ranges_m < entry - hit_tolerance_m)

    # A ray is observed in the box if it intersects the box and its observed
    # distance reaches at least the box entry.
    observed_in_box = intersects & finite_range & (ranges_m >= entry - hit_tolerance_m)

    # First return inside the box.
    hits_inside = observed_in_box & hit_mask
    hits_inside &= ranges_m >= entry - hit_tolerance_m
    hits_inside &= ranges_m <= t_exit + hit_tolerance_m

    # Full gap through the box: observed ray reaches the far side with no
    # first return inside the box.
    full_gaps = observed_in_box & (~hits_inside) & (ranges_m >= t_exit - hit_tolerance_m)

    # Censored inside: useful partial no-hit path, but the ray did not reach
    # the far side. This should usually be rare if max range exceeds the box.
    censored_inside = observed_in_box & (~hits_inside) & (ranges_m < t_exit - hit_tolerance_m)

    # Free path length:
    # - hit inside box: entry -> hit
    # - no hit before exit: entry -> exit
    # - censored no-hit inside box: entry -> observed range
    path_end = np.minimum(ranges_m, t_exit)
    free_path = path_end - entry
    free_path = np.where(observed_in_box, free_path, 0.0)
    free_path = np.where(free_path > min_free_path_m, free_path, 0.0)

    usable = observed_in_box & (free_path > 0)

    n_hits = int(np.sum(hits_inside & usable))
    total_free_path = float(np.sum(free_path[usable]))

    if g_function != "spherical":
        raise NotImplementedError("Only g_function='spherical' is currently implemented.")

    g_values = spherical_g_function(directions_unit)
    total_projected_path = float(np.sum(g_values[usable] * free_path[usable]))

    if total_free_path <= 0:
        contact_density = float("nan")
    else:
        contact_density = n_hits / total_free_path

    if total_projected_path <= 0:
        fad = float("nan")
    else:
        fad = n_hits / total_projected_path

    n_observed = int(np.sum(usable))
    n_full_gaps = int(np.sum(full_gaps & usable))

    if n_observed == 0:
        gap_fraction = float("nan")
    else:
        gap_fraction = n_full_gaps / n_observed

    return FadResult(
        fad_m2_m3=float(fad),
        contact_density_m_inv=float(contact_density),
        gap_fraction=float(gap_fraction),
        n_rays_intersecting_box=int(np.sum(intersects)),
        n_rays_observed_in_box=n_observed,
        n_hits_inside_box=n_hits,
        n_full_gaps_through_box=n_full_gaps,
        n_hits_before_box=int(np.sum(hits_before_box)),
        n_censored_inside_box=int(np.sum(censored_inside & usable)),
        total_free_path_length_m=total_free_path,
        total_projected_path_length_m=total_projected_path,
        g_assumption=g_function,
    )


@dataclass(frozen=True)
class LayeredFadResult:
    layer_edges_y_m: np.ndarray
    layer_centers_y_m: np.ndarray
    fad_m2_m3: np.ndarray
    contact_density_m_inv: np.ndarray
    gap_fraction: np.ndarray
    n_hits_inside_box: np.ndarray
    total_free_path_length_m: np.ndarray
    lai_from_fad: float


def compute_layered_fad(
    *,
    origins_m: np.ndarray,
    directions_m: np.ndarray,
    ranges_m: np.ndarray,
    hit_mask: np.ndarray,
    base_box: Box3D,
    layer_edges_y_m: np.ndarray,
    g_function: str = "spherical",
) -> LayeredFadResult:
    """
    Estimate a vertical FAD profile by slicing the canopy box along y.

    LAI implied by the profile is:
        sum(FAD_layer * layer_thickness)

    This is useful as a bridge between FAD and your existing LAI result.
    """
    layer_edges_y_m = np.asarray(layer_edges_y_m, dtype=float)

    if layer_edges_y_m.ndim != 1 or len(layer_edges_y_m) < 2:
        raise ValueError("layer_edges_y_m must be a 1D array with at least two edges")

    if not np.all(np.diff(layer_edges_y_m) > 0):
        raise ValueError("layer_edges_y_m must be strictly increasing")

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
                hit_mask=hit_mask,
                box=layer_box,
                g_function=g_function,
            )
        )

    fad = np.array([r.fad_m2_m3 for r in results], dtype=float)
    contact = np.array([r.contact_density_m_inv for r in results], dtype=float)
    gap = np.array([r.gap_fraction for r in results], dtype=float)
    hits = np.array([r.n_hits_inside_box for r in results], dtype=int)
    path = np.array([r.total_free_path_length_m for r in results], dtype=float)

    layer_thickness = np.diff(layer_edges_y_m)
    lai_from_fad = float(np.nansum(fad * layer_thickness))

    return LayeredFadResult(
        layer_edges_y_m=layer_edges_y_m,
        layer_centers_y_m=(layer_edges_y_m[:-1] + layer_edges_y_m[1:]) / 2.0,
        fad_m2_m3=fad,
        contact_density_m_inv=contact,
        gap_fraction=gap,
        n_hits_inside_box=hits,
        total_free_path_length_m=path,
        lai_from_fad=lai_from_fad,
    )