from __future__ import annotations

import numpy as np
import pandas as pd


def _as_dataframe(points: pd.DataFrame | np.ndarray) -> pd.DataFrame:
    if isinstance(points, pd.DataFrame):
        return points.copy()
    arr = np.asarray(points)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError("points must be an NxM table with at least X,Y,Z columns")
    columns = ["X", "Y", "Z", "RSSI"] + [
        f"scalar_{i}" for i in range(max(0, arr.shape[1] - 4))
    ]
    return pd.DataFrame(arr, columns=columns[: arr.shape[1]])


def _robust_line_fit_x_ground(
    x: np.ndarray,
    y: np.ndarray,
    *,
    min_x_bins_per_z: int,
) -> tuple[float, float]:
    """Fit ground_Y = slope * X + intercept with one MAD rejection pass."""
    if x.size < min_x_bins_per_z:
        return 0.0, float(np.median(y))

    slope, intercept = np.polyfit(x, y, deg=1)
    residuals = y - (slope * x + intercept)
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - median)))
    if np.isfinite(mad) and mad > 0.0:
        keep = np.abs(residuals - median) <= (3.0 * 1.4826 * mad)
        if int(np.sum(keep)) >= min_x_bins_per_z:
            slope, intercept = np.polyfit(x[keep], y[keep], deg=1)
    return float(slope), float(intercept)


def add_local_ground_height(
    points: pd.DataFrame | np.ndarray,
    *,
    x_col: str = "X",
    y_col: str = "Y",
    z_col: str = "Z",
    z_bin_size_m: float = 0.25,
    x_bin_size_m: float = 0.10,
    ground_quantile: float = 0.10,
    smooth_bins: int = 5,
    min_points_per_xz_bin: int = 10,
    min_x_bins_per_z: int = 3,
    seed_y_min: float | None = None,
    seed_y_max: float | None = None,
) -> pd.DataFrame:
    """Add local ``ground_Y`` and ``height_agl`` without dropping points.

    The function operates in the units already used by the input coordinates.
    Pipeline callers convert metre configuration values to millimetres.
    """
    df = _as_dataframe(points)
    required = (x_col, y_col, z_col)
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"add_local_ground_height missing required column(s): {missing}")

    if df.empty:
        df["ground_Y"] = pd.Series(dtype=float, index=df.index)
        df["height_agl"] = pd.Series(dtype=float, index=df.index)
        return df

    x_bin_size = float(x_bin_size_m)
    z_bin_size = float(z_bin_size_m)
    if not np.isfinite(x_bin_size) or x_bin_size <= 0.0:
        raise ValueError("x_bin_size_m must be > 0")
    if not np.isfinite(z_bin_size) or z_bin_size <= 0.0:
        raise ValueError("z_bin_size_m must be > 0")
    quantile = float(ground_quantile)
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("ground_quantile must be between 0 and 1")

    smooth = max(int(smooth_bins), 1)
    min_points = max(int(min_points_per_xz_bin), 1)
    min_x_bins = max(int(min_x_bins_per_z), 1)
    x_all = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float)
    y_all = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
    z_all = pd.to_numeric(df[z_col], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(x_all) & np.isfinite(y_all) & np.isfinite(z_all)

    seeds = finite.copy()
    if seed_y_min is not None:
        seeds &= y_all >= float(seed_y_min)
    if seed_y_max is not None:
        seeds &= y_all <= float(seed_y_max)

    ground = np.full(len(df), np.nan, dtype=float)
    if not seeds.any():
        df["ground_Y"] = ground
        df["height_agl"] = y_all - ground
        return df

    seed_x = x_all[seeds]
    seed_y = y_all[seeds]
    seed_z = z_all[seeds]
    x_bin = np.floor((seed_x - float(np.min(seed_x))) / x_bin_size).astype(int)
    z_bin = np.floor((seed_z - float(np.min(seed_z))) / z_bin_size).astype(int)
    cells = (
        pd.DataFrame({"x_bin": x_bin, "z_bin": z_bin, "x": seed_x, "z": seed_z, "y": seed_y})
        .groupby(["z_bin", "x_bin"], sort=True)
        .agg(
            x_center=("x", "mean"),
            z_center=("z", "mean"),
            n=("y", "size"),
            ground_candidate=("y", lambda values: float(values.quantile(quantile))),
        )
        .reset_index()
    )
    valid_cells = cells.loc[cells["n"] >= min_points].copy()
    if valid_cells.empty:
        ground[finite] = float(pd.Series(seed_y).quantile(quantile))
        df["ground_Y"] = ground
        df["height_agl"] = y_all - ground
        return df

    profile_rows: list[dict[str, float]] = []
    for z_bin_value, group in valid_cells.groupby("z_bin", sort=True):
        group_x = group["x_center"].to_numpy(dtype=float)
        group_y = group["ground_candidate"].to_numpy(dtype=float)
        if group.shape[0] >= min_x_bins:
            slope, intercept = _robust_line_fit_x_ground(
                group_x,
                group_y,
                min_x_bins_per_z=min_x_bins,
            )
        else:
            slope, intercept = 0.0, float(np.median(group_y))
        profile_rows.append({
            "z_bin": float(z_bin_value),
            "z_center": float(group["z_center"].median()),
            "slope_x": slope,
            "intercept": intercept,
        })

    profile = pd.DataFrame(profile_rows).sort_values("z_center")
    for column in ("slope_x", "intercept"):
        profile[column] = (
            profile[column]
            .rolling(window=smooth, center=True, min_periods=1)
            .median()
            .interpolate(method="linear", limit_direction="both")
        )

    z_profile = profile["z_center"].to_numpy(dtype=float)
    slope_at_z = np.interp(z_all[finite], z_profile, profile["slope_x"].to_numpy(dtype=float))
    intercept_at_z = np.interp(z_all[finite], z_profile, profile["intercept"].to_numpy(dtype=float))
    ground[finite] = slope_at_z * x_all[finite] + intercept_at_z
    df["ground_Y"] = ground
    df["height_agl"] = y_all - ground
    return df
