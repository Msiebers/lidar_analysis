import numpy as np
import pandas as pd

from . import imagepers


def topology_stand_count(df_xyz_m: pd.DataFrame, min_persistence: float = 0.35):
    if len(df_xyz_m) == 0:
        return float("nan"), []

    req = ["x", "y", "z"]
    for c in req:
        if c not in df_xyz_m.columns:
            raise ValueError(f"topology_stand_count missing required column {c!r}")

    d = df_xyz_m[["x", "z"]].copy()
    d["round_x"] = np.floor(d["x"] * 50.0) / 50.0
    grp = d.groupby(["round_x", "z"], as_index=False).size().rename(columns={"size": "count"})

    x_vals = np.sort(grp["round_x"].unique())
    z_vals = np.sort(grp["z"].unique())
    full = pd.MultiIndex.from_product([x_vals, z_vals], names=["round_x", "z"]).to_frame(index=False)
    grid = full.merge(grp, how="left", on=["round_x", "z"]).fillna({"count": 0.0})

    im = grid.pivot(index="round_x", columns="z", values="count").to_numpy(dtype=float)
    m = float(np.max(im))
    if m > 0:
        im = im / m

    points = imagepers.persistence(im)
    ct = 0
    for _b, _d, p in points:
        if p < float(min_persistence):
            break
        ct += 1

    distance = float(np.max(z_vals) - np.min(z_vals)) if len(z_vals) else 0.0
    if distance <= 0:
        return float("nan"), points
    return float(ct) / distance, points
