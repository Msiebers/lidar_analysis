from __future__ import annotations

import numpy as np
import pandas as pd

from . import imagepers


def topology_stand_count(point_cloud_xyz_m: np.ndarray, min_persistence: float = 0.35) -> dict:
    if point_cloud_xyz_m is None:
        return {"count": 0.0, "count_raw": 0.0, "points": []}
    arr = np.asarray(point_cloud_xyz_m, dtype=float)
    if arr.size == 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError("point_cloud_xyz_m must be (N,3) with x,y,z columns")

    df = pd.DataFrame(arr[:, :3], columns=["x", "y", "z"])
    df["round_x"] = np.floor(df["x"].to_numpy() * 50.0) / 50.0
    pc = df.groupby(["round_x", "z"], as_index=False).size()
    if pc.empty:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    x_all = np.sort(pc["round_x"].unique())
    z_all = np.sort(pc["z"].unique())
    full = pd.MultiIndex.from_product([x_all, z_all], names=["round_x", "z"]).to_frame(index=False)
    pc_full = full.merge(pc, on=["round_x", "z"], how="left").fillna({"size": 0.0})

    grid = pc_full.pivot_table(index="round_x", columns="z", values="size", fill_value=0.0)
    im = grid.to_numpy(dtype=float)
    if im.size == 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}
    mx = float(np.max(im))
    if mx <= 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    im = im / mx
    g0 = imagepers.persistence(im)

    xs = grid.index.to_numpy()
    zs = grid.columns.to_numpy()
    points = []
    count = len(g0)
    for i, (q, _birth, per, _death) in enumerate(g0):
        points.append((float(xs[q[0]]), float(zs[q[1]])))
        if per < float(min_persistence):
            count = i
            break

    zvals = df["z"].to_numpy(dtype=float)
    distance = float(np.max(zvals) - np.min(zvals)) if zvals.size else 0.0
    norm = float(count) / distance if distance > 0 else 0.0
    return {"count": norm, "count_raw": float(count), "points": points}
