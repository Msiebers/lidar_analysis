"""
Plot-scale LAI traits from spinning multi-beam LiDAR, as an analogue of the
LI-COR LAI-2200C inversion (Section 10 of the manual).

Primary entry point: compute_lai_trait_from_beam_rows(beam_rows, ...), which the
pipeline calls from analyze_plot(). compute_lai_trait_from_target() and
compute_lai_trait_from_lidar_data() are thin compatibility wrappers.

Schemes (all relevant for a ground cart, which must NOT use 75-90 deg rays):
  lai_even   : capped 0-74.5 deg, Miller sin-theta weights (spherical-tuned).
  lai_uneven : capped 0-74.5 deg, LAI-2200 PUBLISHED weights -- the LI-COR
               apples-to-apples comparison value.
  lai_full   : full 0-90 deg, Miller weights. Diagnostic only: more nearly
               leaf-angle-independent, but uses the contaminated near-horizon
               beams, so not the reported cart trait.

Equation references are to the transcribed Section 10 (10-1 ... 10-30).
Core relations, all confirmed against that transcription:
  K_i  = -ln(GAPS_i) * cos(theta_i)              (10-15)
  L    = 2 * sum_i W_i K_i,  sum W_i = 1          (10-13, 10-29)
  Le   uses arithmetic-mean gap (AVGTRANS)        (10-6, 10-11)
  L    uses log-mean gap (GAPS) -> reported       (10-7, 10-12)
  Omega_app = Le / L                              (10-8, 10-16, 10-17)
  G(theta) = -ln P * cos(theta) / L               (10-10)  [MTA uses this slope]
  DIFN = 2 * sum_i W'_i GAPS_i, sum W'_i = 1/2     (10-25, 10-26, 10-30)
  MTA  = poly(slope of G vs theta)                (10-22, 10-23)
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np

# --- Ring schemes -----------------------------------------------------------

# Capped at ~74.5 deg (outer edge of the LAI-2200 68 deg ring). Excludes the
# 74.5-90 deg wedge, which for a ground cart is the most contaminated.
CAPPED_ZENITH_BREAKS_RAD = np.deg2rad([0.0, 15.0, 30.0, 45.0, 60.0, 74.5])
# Full hemisphere, diagnostic only.
FULL_ZENITH_BREAKS_RAD = np.deg2rad([0.0, 15.0, 30.0, 45.0, 60.0, 90.0])

# Published LAI-2200C weights (Section 10 "Weighting Factors").
LAI2200_PUBLISHED_WEIGHTS = np.array([0.041, 0.131, 0.201, 0.290, 0.337])       # sum 1   (10-14)
LAI2200_PUBLISHED_DIFN_WEIGHTS = np.array([0.033, 0.097, 0.127, 0.141, 0.102])  # sum 1/2 (10-26)

# scheme name -> (zenith_breaks, lai_weight_override, difn_weight_override)
SCHEMES: dict[str, tuple[np.ndarray, np.ndarray | None, np.ndarray | None]] = {
    "lai_even": (CAPPED_ZENITH_BREAKS_RAD, None, None),
    "lai_uneven": (CAPPED_ZENITH_BREAKS_RAD, LAI2200_PUBLISHED_WEIGHTS, LAI2200_PUBLISHED_DIFN_WEIGHTS),
    "lai_full": (FULL_ZENITH_BREAKS_RAD, None, None),
}

_LAI_GAP_FRACTION_RINGS = 5

# Mean-tilt-angle polynomial alpha(m), Eq. 10-22 (after Lang 1986).
_MTA_POLY_COEFFS = (56.81964, 46.84833, -64.62133, -158.69141, 522.06260, 1008.14931)


# --- Weights ----------------------------------------------------------------

def _weights(breaks_rad: np.ndarray, override: np.ndarray | None, active: np.ndarray | None = None) -> np.ndarray:
    """LAI weights, normalized so active rings sum to 1 (10-29)."""
    if override is not None:
        base = np.asarray(override, dtype=float)
    else:
        base = np.cos(breaks_rad[:-1]) - np.cos(breaks_rad[1:])  # integral sin dtheta
    if active is not None:
        base = np.where(active, base, 0.0)
    s = base.sum()
    return base / s if s > 0 else base


def _difn_weights(breaks_rad: np.ndarray, override: np.ndarray | None, active: np.ndarray | None = None) -> np.ndarray:
    """DIFN weights, normalized so active rings sum to 1/2 (10-30)."""
    if override is not None:
        base = np.asarray(override, dtype=float)
    else:
        base = 0.5 * (np.sin(breaks_rad[1:]) ** 2 - np.sin(breaks_rad[:-1]) ** 2)  # integral sin*cos dtheta
    if active is not None:
        base = np.where(active, base, 0.0)
    s = base.sum()
    return base * (0.5 / s) if s > 0 else base


# --- Mean tilt angle --------------------------------------------------------

def _mta_poly(m: float) -> float:
    val = 0.0
    for k, a in enumerate(_MTA_POLY_COEFFS):
        val += a * (m ** k)
    return float(np.clip(val, 0.0, 90.0))


def _ols_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Least-squares slope and its standard error."""
    n = x.size
    xb = x.mean()
    Sxx = float(((x - xb) ** 2).sum())
    if Sxx <= 0.0:
        return float("nan"), float("nan")
    yb = y.mean()
    m = float(((x - xb) * (y - yb)).sum() / Sxx)
    if n > 2:
        resid = y - (m * x + (yb - m * xb))
        sse = float((resid ** 2).sum())
        mse = math.sqrt(sse / ((n - 2) * Sxx)) if sse > 0 else 0.0
    else:
        mse = float("nan")
    return m, mse


def _robust_mta(
    distances_m: np.ndarray,
    zeniths_rad: np.ndarray,
    gap_distance_m: float,
    treat_no_return_as_gap: bool,
    lai_ref: float,
    *,
    lo_deg: float = 25.0,   # accepted for signature compatibility; unused
    hi_deg: float = 65.0,   # accepted for signature compatibility; unused
    n_bins: int = 8,        # accepted for signature compatibility; unused
    min_rays_per_bin: int = 30,
) -> dict[str, Any]:
    """
    LI-COR LAI-2200-style MTA.

    Uses five LI-COR-style rings and regresses the recovered projection
    function:

        G(theta) = -ln(P) * cos(theta) / L

    against ring center angle in radians, then maps the slope through the
    LI-COR MTA polynomial.

    This intentionally does not use the exploratory fine-bin LiDAR regression.
    """
    nan = float("nan")

    if not np.isfinite(lai_ref) or lai_ref <= 0.0:
        return {
            "mta_deg": nan,
            "mta_sem_deg": nan,
            "slope": nan,
            "n_bins": 0,
        }

    centers_rad = np.deg2rad(np.array([7.0, 23.0, 38.0, 53.0, 68.0], dtype=float))
    cos_c = np.cos(centers_rad)

    # Use the same five-ring scheme as the capped/uneven LAI output.
    breaks = SCHEMES["lai_uneven"][0]

    n_total, n_gap = _scheme_counts(
        distances_m,
        zeniths_rad,
        breaks,
        gap_distance_m,
        treat_no_return_as_gap,
    )

    n_total = np.asarray(n_total, dtype=float)
    n_gap = np.asarray(n_gap, dtype=float)

    # _scheme_counts returns scan x ring counts for normal LAI.
    # MTA needs one count per ring, summed across scans.
    if n_total.ndim == 2:
        n_total = np.nansum(n_total, axis=0)
    else:
        n_total = n_total.ravel()

    if n_gap.ndim == 2:
        n_gap = np.nansum(n_gap, axis=0)
    else:
        n_gap = n_gap.ravel()

    n_total = np.asarray(n_total, dtype=float).ravel()
    n_gap = np.asarray(n_gap, dtype=float).ravel()

    if n_total.size != centers_rad.size or n_gap.size != centers_rad.size:
        raise ValueError(
            f"MTA expected {centers_rad.size} rings, "
            f"got n_total={n_total.shape}, n_gap={n_gap.shape}"
        )

    # Gap fraction with the same zero-gap correction style used for LAI.
    P = np.full(n_total.shape, nan, dtype=float)

    valid_ring = np.isfinite(n_total) & (n_total > 0.0)
    P[valid_ring] = n_gap[valid_ring] / n_total[valid_ring]

    zero_gap = valid_ring & (n_gap == 0.0)
    P[zero_gap] = 1.0 / (2.0 * n_total[zero_gap])

    # Keep only physically valid gap fractions.
    valid_p = valid_ring & np.isfinite(P) & (P > 0.0) & (P <= 1.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        G = (-np.log(P) * cos_c) / float(lai_ref)

    valid = (
        valid_p
        & np.isfinite(G)
        & (n_total >= float(min_rays_per_bin))
    )

    n_valid = int(np.sum(valid))

    if n_valid < 3:
        return {
            "mta_deg": nan,
            "mta_sem_deg": nan,
            "slope": nan,
            "n_bins": n_valid,
        }

    x = centers_rad[valid]
    y = G[valid]

    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    ssx = float(np.sum((x - x_mean) ** 2))

    if not np.isfinite(ssx) or ssx <= 0.0:
        return {
            "mta_deg": nan,
            "mta_sem_deg": nan,
            "slope": nan,
            "n_bins": n_valid,
        }

    slope = float(np.sum((x - x_mean) * (y - y_mean)) / ssx)
    intercept = float(y_mean - slope * x_mean)

    residuals = y - (intercept + slope * x)

    if n_valid > 2:
        mse = float(np.sum(residuals ** 2) / (n_valid - 2))
        slope_se = math.sqrt(mse / ssx) if np.isfinite(mse) and mse >= 0.0 else nan
    else:
        slope_se = nan

    mta_deg = _mta_poly(slope)

    if np.isfinite(slope_se):
        m_for_sem = slope - slope_se if slope > 0.0 else slope + slope_se
        mta_sem_deg = abs(float(mta_deg) - float(_mta_poly(m_for_sem)))
    else:
        mta_sem_deg = nan

    return {
        "mta_deg": float(mta_deg),
        "mta_sem_deg": float(mta_sem_deg),
        "slope": float(slope),
        "n_bins": n_valid,
    }

# --- Per-scheme LAI ---------------------------------------------------------

def _ring_index(zeniths_rad: np.ndarray, breaks_rad: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    n_rings = len(breaks_rad) - 1
    idx = np.digitize(zeniths_rad, breaks_rad)
    in_range = (idx >= 1) & (idx <= n_rings) & np.isfinite(zeniths_rad)
    idx = np.where(in_range, idx, 0)
    return idx, n_rings, in_range


def _scheme_counts(distances, zeniths_rad, breaks_rad, gap_distance_m, treat_no_return_as_gap):
    distances = np.atleast_2d(np.asarray(distances, dtype=float))
    zeniths_rad = np.asarray(zeniths_rad, dtype=float).ravel()

    if distances.shape[1] != zeniths_rad.size:
        raise ValueError(
            f"distances columns {distances.shape[1]} must match "
            f"zenith count {zeniths_rad.size}"
        )

    idx, n_rings, in_range = _ring_index(zeniths_rad, breaks_rad)

    finite_d = np.isfinite(distances) & (distances > 0.0)
    is_gap = (distances >= float(gap_distance_m)) | (
        bool(treat_no_return_as_gap) & ~finite_d
    )
    is_hit = finite_d & (distances < float(gap_distance_m))
    countable = is_gap | is_hit

    idx2 = np.broadcast_to(idx, distances.shape)
    inr2 = np.broadcast_to(in_range, distances.shape)

    n_scans = distances.shape[0]
    n_total = np.zeros((n_scans, n_rings), dtype=float)
    n_gap = np.zeros((n_scans, n_rings), dtype=float)

    for r in range(1, n_rings + 1):
        sel = inr2 & (idx2 == r)
        n_total[:, r - 1] = (sel & countable).sum(axis=1)
        n_gap[:, r - 1] = (sel & is_gap).sum(axis=1)

    return n_total, n_gap

def _gap_to_contact(P, cos_centers):
    K = np.full(P.shape, np.nan)
    ok = np.isfinite(P) & (P > 0.0)
    K[ok] = -np.log(P[ok]) * cos_centers[ok]
    return K


def _lai_scheme(n_total, n_gap, breaks_rad, weights_override=None, difn_override=None):
    n_rings = len(breaks_rad) - 1
    centers = 0.5 * (breaks_rad[:-1] + breaks_rad[1:])
    cos_c = np.cos(centers)

    def weights_for(active):
        return _weights(breaks_rad, weights_override, active)

    tot = n_total.sum(axis=0)
    gap = n_gap.sum(axis=0)
    P = np.full(n_rings, np.nan)
    valid = tot > 0
    P[valid] = gap[valid] / tot[valid]
    corrected = False
    zero = valid & (gap == 0)
    if np.any(zero):
        P[zero] = 1.0 / (2.0 * tot[zero])
        corrected = True

    K = _gap_to_contact(P, cos_c)
    active = valid & np.isfinite(K)
    W = weights_for(active)
    lai_pooled = float(2.0 * np.sum(K[active] * W[active])) if np.any(active) else float("nan")

    n_scans = n_total.shape[0]
    lai_eff = lai_pooled
    lai_clumped = lai_pooled
    clumping = 1.0
    sel = float("nan")

    if n_scans > 1:
        Ps = np.full(n_total.shape, np.nan)
        v = n_total > 0
        Ps[v] = n_gap[v] / n_total[v]
        z = v & (n_gap == 0)
        Ps[z] = 1.0 / (2.0 * n_total[z])
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            Pbar = np.nanmean(np.where(v, Ps, np.nan), axis=0)
            K_eff = _gap_to_contact(Pbar, cos_c)
            act_e = np.isfinite(K_eff)
            W_e = weights_for(act_e)
            lai_eff = float(2.0 * np.sum(K_eff[act_e] * W_e[act_e])) if np.any(act_e) else float("nan")
            Kln = np.where(v, -np.log(np.where(v, Ps, 1.0)), np.nan) * cos_c[None, :]
            K_act = np.nanmean(Kln, axis=0)
        act_c = np.isfinite(K_act)
        W_c = weights_for(act_c)
        lai_clumped = float(2.0 * np.sum(K_act[act_c] * W_c[act_c])) if np.any(act_c) else float("nan")
        if np.isfinite(lai_eff) and np.isfinite(lai_clumped) and lai_clumped > 0:
            clumping = float(lai_eff / lai_clumped)
        per_scan = []
        for s in range(n_scans):
            Ks = _gap_to_contact(Ps[s], cos_c)
            a_s = np.isfinite(Ks)
            if np.any(a_s):
                w_s = weights_for(a_s)
                per_scan.append(2.0 * np.sum(Ks[a_s] * w_s[a_s]))
        per_scan = np.asarray(per_scan, dtype=float)
        if per_scan.size > 1:
            sel = float(np.nanstd(per_scan, ddof=1) / math.sqrt(per_scan.size))

    lai = lai_clumped  # reported = log-averaged form (10-7); == pooled for 1 scan

    difn_active = valid & np.isfinite(P)
    Wp = _difn_weights(breaks_rad, difn_override, difn_active)
    difn = float(2.0 * np.sum(np.where(difn_active, Wp * P, 0.0))) if np.any(difn_active) else float("nan")

    return {
        "lai": lai,
        "lai_pooled": lai_pooled,
        "lai_effective": lai_eff,
        "lai_clumped": lai_clumped,
        "clumping": clumping,
        "sel": sel,
        "difn": difn,
        "corrected_zero_gap_bins": bool(corrected),
        "gap_fraction": P,
        "contact_number": K,
        "n_rays": tot,
    }


def compute_lai_all_schemes(
    *,
    distances_m,
    zeniths_rad,
    gap_distance_m=30.0,
    treat_no_return_as_gap=True,
    run_mta: bool = False,
    mta_lo_deg: float = 25.0,
    mta_hi_deg: float = 65.0,
    mta_n_bins: int = 8,
    mta_min_rays_per_bin: int = 30,
):
    distances_m = np.atleast_2d(np.asarray(distances_m, dtype=float))
    zeniths_rad = np.asarray(zeniths_rad, dtype=float).ravel()

    if distances_m.shape[1] != zeniths_rad.shape[0]:
        raise ValueError(
            f"distances columns {distances_m.shape} must match zeniths {zeniths_rad.shape}"
        )

    out: dict[str, Any] = {}

    for name, (breaks, wov, dov) in SCHEMES.items():
        n_total, n_gap = _scheme_counts(
            distances_m,
            zeniths_rad,
            breaks,
            gap_distance_m,
            treat_no_return_as_gap,
        )
        out[name] = _lai_scheme(
            n_total,
            n_gap,
            breaks,
            weights_override=wov,
            difn_override=dov,
        )

    if run_mta:
        # One robust MTA, normalized by the most G-independent available L.
        lai_ref = out.get("lai_uneven", {}).get("lai", float("nan"))
        if not np.isfinite(lai_ref):
            lai_ref = out.get("lai_even", {}).get("lai", float("nan"))

        out["_mta"] = _robust_mta(
            distances_m,
            zeniths_rad,
            gap_distance_m,
            treat_no_return_as_gap,
            lai_ref,
            lo_deg=mta_lo_deg,
            hi_deg=mta_hi_deg,
            n_bins=mta_n_bins,
            min_rays_per_bin=mta_min_rays_per_bin,
        )
    else:
        out["_mta"] = {
            "mta_deg": float("nan"),
            "mta_sem_deg": float("nan"),
            "slope": float("nan"),
            "n_bins": 0,
        }

    return out

# --- Trait flattening -------------------------------------------------------

def _scheme_keys(prefix):
    keys = [
        prefix, f"{prefix}_pooled", f"{prefix}_effective", f"{prefix}_clumped",
        f"{prefix}_clumping", f"{prefix}_sel", f"{prefix}_difn",
        f"{prefix}_corrected_zero_gap_bins",
    ]
    for i in range(1, _LAI_GAP_FRACTION_RINGS + 1):
        keys += [f"{prefix}_gap_fraction_ring_{i}", f"{prefix}_contact_number_ring_{i}", f"{prefix}_n_rays_ring_{i}"]
    return keys


def _empty_lai_traits(*, gap_distance_m, angle_column=None, distance_column=None,
                      n_missing_range=0, n_missing_angle=0, n_no_return=0):
    traits: dict[str, Any] = {
        "lai_n_scans": 0, "lai_n_angles": 0, "lai_n_rays": 0,
        "lai_gap_distance_m": float(gap_distance_m),
        "lai_angle_column_used": angle_column, "lai_distance_column_used": distance_column,
        "lai_n_missing_range": int(n_missing_range), "lai_n_missing_angle": int(n_missing_angle),
        "lai_n_no_return": int(n_no_return),
        "lai_mta_deg": float("nan"), "lai_mta_sem_deg": float("nan"),
        "lai_mta_slope": float("nan"), "lai_mta_n_bins": 0,
    }
    for prefix in SCHEMES:
        for key in _scheme_keys(prefix):
            traits[key] = False if key.endswith("_corrected_zero_gap_bins") else float("nan")
    return traits


def _flatten(schemes, *, gap_distance_m, n_scans, n_angles, n_rays,
             angle_column=None, distance_column=None, n_missing_range=0, n_missing_angle=0, n_no_return=0):
    traits = _empty_lai_traits(gap_distance_m=gap_distance_m, angle_column=angle_column,
                               distance_column=distance_column, n_missing_range=n_missing_range,
                               n_missing_angle=n_missing_angle, n_no_return=n_no_return)
    traits["lai_n_scans"] = int(n_scans)
    traits["lai_n_angles"] = int(n_angles)
    traits["lai_n_rays"] = int(n_rays)

    mta = schemes.get("_mta", {})
    traits["lai_mta_deg"] = float(mta.get("mta_deg", float("nan")))
    traits["lai_mta_sem_deg"] = float(mta.get("mta_sem_deg", float("nan")))
    traits["lai_mta_slope"] = float(mta.get("slope", float("nan")))
    traits["lai_mta_n_bins"] = int(mta.get("n_bins", 0))

    for prefix, res in schemes.items():
        if prefix == "_mta":
            continue
        traits[prefix] = float(res["lai"])
        traits[f"{prefix}_pooled"] = float(res["lai_pooled"])
        traits[f"{prefix}_effective"] = float(res["lai_effective"])
        traits[f"{prefix}_clumped"] = float(res["lai_clumped"])
        traits[f"{prefix}_clumping"] = float(res["clumping"])
        traits[f"{prefix}_sel"] = float(res["sel"])
        traits[f"{prefix}_difn"] = float(res["difn"])
        traits[f"{prefix}_corrected_zero_gap_bins"] = bool(res["corrected_zero_gap_bins"])
        gf = np.asarray(res["gap_fraction"], float).ravel()
        kn = np.asarray(res["contact_number"], float).ravel()
        nr = np.asarray(res["n_rays"], float).ravel()
        for i in range(1, _LAI_GAP_FRACTION_RINGS + 1):
            traits[f"{prefix}_gap_fraction_ring_{i}"] = float(gf[i - 1]) if i <= gf.size else float("nan")
            traits[f"{prefix}_contact_number_ring_{i}"] = float(kn[i - 1]) if i <= kn.size else float("nan")
            traits[f"{prefix}_n_rays_ring_{i}"] = float(nr[i - 1]) if i <= nr.size else float("nan")
    return traits


# --- Angle convention -------------------------------------------------------

def _zenith_from_angle(angle_rad: np.ndarray, convention: str) -> np.ndarray:
    """
    Map a beam angle column to LAI zenith (0 = straight up/sky).

    'sick'      : SICK cart theta, 0 = down, +-90 = horizon, +-180 = sky.
                  zenith = pi - |wrap(theta)|  (0 at sky, pi at ground).
    'elevation' : legacy phi-style, zenith = |pi/2 - angle|.
    """
    if convention == "sick":
        wrapped = (angle_rad + np.pi) % (2.0 * np.pi) - np.pi
        return np.pi - np.abs(wrapped)
    if convention == "elevation":
        return np.abs(0.5 * np.pi - angle_rad)
    raise ValueError(f"unknown zenith_convention {convention!r}")


_DISTANCE_COLUMNS = ("range_m", "dist_mm")
_ANGLE_COLUMNS = ("theta", "phi")


def _extract_range_and_angle(rows, distance_columns, angle_columns):
    """Pull range (m) and angle (rad) arrays from a DataFrame-like or dict-like."""
    cols = getattr(rows, "columns", None)
    has = (lambda c: c in cols) if cols is not None else (lambda c: c in rows)

    distance_column = None
    for c in distance_columns:
        if has(c):
            distance_column = c
            break
    if distance_column is None:
        return None, None, None, None

    arr = np.asarray(rows[distance_column], dtype=float)
    distances_m = arr / 1000.0 if distance_column == "dist_mm" else arr

    angle_column = next((c for c in angle_columns if has(c)), None)
    if angle_column is None:
        return distances_m, None, distance_column, None

    angle = np.asarray(rows[angle_column], dtype=float)
    finite_angle = angle[np.isfinite(angle)]
    if finite_angle.size and np.nanmax(np.abs(finite_angle)) > (2.0 * math.pi + 1e-6):
        angle = np.deg2rad(angle)  # degrees -> radians
    return distances_m, angle, distance_column, angle_column


# --- Entry points -----------------------------------------------------------

def compute_lai_trait_from_beam_rows(
    beam_rows=None,
    *,
    distances_m: np.ndarray | None = None,
    theta_rad: np.ndarray | None = None,
    phi_rad: np.ndarray | None = None,
    gap_distance_m: float = 30.0,
    treat_no_return_as_gap: bool = True,
    zenith_convention: str = "sick",
    distance_column: str | None = None,
    angle_column: str | None = None,
    distance_columns: tuple[str, ...] = _DISTANCE_COLUMNS,
    angle_columns: tuple[str, ...] = _ANGLE_COLUMNS,
    run_mta: bool = False,
    mta_lo_deg: float = 25.0,
    mta_hi_deg: float = 65.0,
    mta_n_bins: int = 8,
    mta_min_rays_per_bin: int = 30,
) -> dict[str, Any]:
    """
    PRIMARY entry point: compute LAI traits for one plot's beam rows.

    Supports both call styles:

    1. Current pipeline_core.py keyword-array style:
       compute_lai_trait_from_beam_rows(
           distances_m=...,      # already in meters
           theta_rad=...,
           gap_distance_m=30.0,
           distance_column="dist_mm",   # label only here
           run_mta=True/False,
       )

    2. DataFrame/dict style:
       compute_lai_trait_from_beam_rows(beam_rows)

       In this path, a 'dist_mm' column is converted from mm to m.
    """

    # ------------------------------------------------------------------
    # Current pipeline_core.py path: distances_m + theta_rad/phi_rad
    # ------------------------------------------------------------------
    if distances_m is not None:
        distances_m = np.asarray(distances_m, dtype=float).ravel()

        if theta_rad is not None:
            angle = np.asarray(theta_rad, dtype=float).ravel()
            angle_column = angle_column or "theta"
        elif phi_rad is not None:
            angle = np.asarray(phi_rad, dtype=float).ravel()
            angle_column = angle_column or "phi"
        else:
            raise ValueError("distances_m requires theta_rad or phi_rad")

        if angle.size != distances_m.size:
            raise ValueError(
                f"distances_m and angle arrays must have same length; "
                f"got {distances_m.size} and {angle.size}"
            )

        distance_column = distance_column or "distance_m"

    # ------------------------------------------------------------------
    # DataFrame/dict path: beam_rows
    # ------------------------------------------------------------------
    else:
        if beam_rows is None or len(beam_rows) == 0:
            return _empty_lai_traits(gap_distance_m=gap_distance_m)

        distances_m, angle, distance_column, angle_column = _extract_range_and_angle(
            beam_rows,
            distance_columns,
            angle_columns,
        )

        if distances_m is None:
            return _empty_lai_traits(gap_distance_m=gap_distance_m)

        if angle is None:
            return _empty_lai_traits(
                gap_distance_m=gap_distance_m,
                distance_column=distance_column,
                n_missing_angle=len(beam_rows),
            )

        distances_m = np.asarray(distances_m, dtype=float).ravel()
        angle = np.asarray(angle, dtype=float).ravel()

        if angle.size != distances_m.size:
            raise ValueError(
                f"beam row distance and angle arrays must have same length; "
                f"got {distances_m.size} and {angle.size}"
            )

    # ------------------------------------------------------------------
    # Shared angle handling
    # ------------------------------------------------------------------
    finite_angle = angle[np.isfinite(angle)]
    if finite_angle.size and np.nanmax(np.abs(finite_angle)) > (2.0 * math.pi + 1e-6):
        angle = np.deg2rad(angle)

    zeniths_rad = _zenith_from_angle(angle, zenith_convention)

    range_ok = np.isfinite(distances_m) & (distances_m > 0.0)
    angle_ok = np.isfinite(zeniths_rad)

    n_missing_angle = int((~angle_ok).sum())
    n_no_return = int((angle_ok & ~range_ok).sum())

    if not np.any(angle_ok):
        return _empty_lai_traits(
            gap_distance_m=gap_distance_m,
            angle_column=angle_column,
            distance_column=distance_column,
            n_missing_range=int((~range_ok).sum()),
            n_missing_angle=n_missing_angle,
            n_no_return=n_no_return,
        )

    # Keep all rays with valid angles.
    # Non-finite or zero ranges stay in the array and are counted as gaps
    # when treat_no_return_as_gap=True.
    keep = angle_ok

    schemes = compute_lai_all_schemes(
        distances_m=distances_m[keep][None, :],
        zeniths_rad=zeniths_rad[keep],
        gap_distance_m=gap_distance_m,
        treat_no_return_as_gap=treat_no_return_as_gap,
        run_mta=run_mta,
        mta_lo_deg=mta_lo_deg,
        mta_hi_deg=mta_hi_deg,
        mta_n_bins=mta_n_bins,
        mta_min_rays_per_bin=mta_min_rays_per_bin,
    )

    return _flatten(
        schemes,
        gap_distance_m=gap_distance_m,
        n_scans=1,
        n_angles=int(keep.sum()),
        n_rays=int(keep.sum()),
        angle_column=angle_column,
        distance_column=distance_column,
        n_missing_range=int((~range_ok).sum()),
        n_missing_angle=n_missing_angle,
        n_no_return=n_no_return,
    )

def compute_lai_trait_from_target(target, *, gap_distance_m: float = 30.0, **kwargs) -> dict[str, Any]:
    """Compatibility wrapper: pulls AnalysisTarget.raw_points and delegates."""
    points = getattr(target, "raw_points", None)
    if points is None or len(points) == 0:
        return _empty_lai_traits(gap_distance_m=gap_distance_m)
    return compute_lai_trait_from_beam_rows(points, gap_distance_m=gap_distance_m, **kwargs)


def compute_lai_trait_from_lidar_data(lidar_data, *, gap_distance_m: float = 30.0,
                                      treat_no_return_as_gap: bool = True) -> dict[str, Any]:
    """
    Compatibility wrapper for a dict with already-computed zeniths.
      lidar_data["distances"] -> (n_scans, n_angles) meters
      lidar_data["zeniths"]   -> (n_angles,) radians (true zenith, 0 = up)
    """
    if "distances" not in lidar_data or "zeniths" not in lidar_data:
        raise ValueError("lidar_data needs 'distances' and 'zeniths'")
    distances = np.atleast_2d(np.asarray(lidar_data["distances"], dtype=float))
    zeniths = np.asarray(lidar_data["zeniths"], dtype=float).ravel()
    n_no_return = int(np.sum(~(np.isfinite(distances) & (distances > 0.0))))
    schemes = compute_lai_all_schemes(
        distances_m=distances, zeniths_rad=zeniths,
        gap_distance_m=gap_distance_m, treat_no_return_as_gap=treat_no_return_as_gap,
    )
    return _flatten(schemes, gap_distance_m=gap_distance_m, n_scans=distances.shape[0],
                    n_angles=distances.shape[1], n_rays=int(distances.size), n_no_return=n_no_return)


def compute_legacy_lai_pair(
    *,
    distances_m: np.ndarray,
    zeniths_rad: np.ndarray,
    gap_distance_m: float = 30.0,
    treat_no_return_as_gap: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    Backward-compatible alias for older imports from lidar_analysis.lai.
    """
    return compute_lai_all_schemes(
        distances_m=distances_m,
        zeniths_rad=zeniths_rad,
        gap_distance_m=gap_distance_m,
        treat_no_return_as_gap=treat_no_return_as_gap,
    )
