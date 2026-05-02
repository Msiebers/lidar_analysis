# topology.py
"""
Topology-based stand/board counting utilities.

Exposes:
  - topology_stand_count(point_cloud_m_idx, mm_per_click, ...)
      -> dict with {count, count_raw, points}
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class UnionFind:
    """
    Minimal Union-Find / Disjoint-Set structure.

    Used by the 2D persistence algorithm. We only need:
      - add(x, weight)  -> register element
      - union(a, b)     -> merge sets
      - __contains__(x) -> membership check
      - __getitem__(x)  -> return representative of x's set
    """
    def __init__(self):
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}
        self.rank: dict[tuple[int, int], int] = {}

    def add(self, x, weight=None):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        # Path compression
        px = self.parent.get(x, x)
        if px != x:
            self.parent[x] = self.find(px)
        return self.parent.get(x, x)

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        # Union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def __contains__(self, x):
        return x in self.parent

    def __getitem__(self, x):
        return self.find(x)


def _pers_get(im: np.ndarray, p: tuple[int, int]) -> float:
    return im[p[0]][p[1]]


def _pers_iter_neighbors(p: tuple[int, int], w: int, h: int):
    y, x = p

    # 8-neighborhood
    neigh = [(y + j, x + i) for i in [-1, 0, 1] for j in [-1, 0, 1]]

    # To switch to 4-neighborhood instead, use:
    # neigh = [(y-1, x), (y+1, x), (y, x-1), (y, x+1)]

    for j, i in neigh:
        if j < 0 or j >= h:
            continue
        if i < 0 or i >= w:
            continue
        if j == y and i == x:
            continue
        yield j, i


def persistence(im: np.ndarray):
    """
    Compute 0D persistence for a 2D image (high-to-low filtration).

    Returns a list of tuples:
        (representative_pixel, birth_value, persistence_value, death_pixel)
    sorted by persistence_value descending.
    """
    im = np.asarray(im, dtype=float)
    h, w = im.shape

    # Get indices ordered by value from high to low
    indices = [(i, j) for i in range(h) for j in range(w)]
    indices.sort(key=lambda p: _pers_get(im, p), reverse=True)

    # Maintains the growing sets
    uf = UnionFind()
    groups0: dict[tuple[int, int], tuple[float, float, tuple[int, int] | None]] = {}

    def get_comp_birth(p):
        return _pers_get(im, uf[p])

    # Process pixels from high to low
    for i, p in enumerate(indices):
        v = _pers_get(im, p)
        ni = [uf[q] for q in _pers_iter_neighbors(p, w, h) if q in uf]
        nc = sorted([(get_comp_birth(q), q) for q in set(ni)], reverse=True)

        if i == 0:
            groups0[p] = (v, v, None)

        uf.add(p, -i)

        if len(nc) > 0:
            oldp = nc[0][1]
            uf.union(oldp, p)

            # Merge all others with oldp
            for bl, q in nc[1:]:
                if uf[q] not in groups0:
                    groups0[uf[q]] = (bl, bl - v, p)
                uf.union(oldp, q)

    groups_list = [
        (k, groups0[k][0], groups0[k][1], groups0[k][2])
        for k in groups0
    ]
    groups_list.sort(key=lambda g: g[2], reverse=True)

    return groups_list


def topology_stand_count(
    point_cloud_m_idx: np.ndarray,
    mm_per_click: float,
    min_persistence: float = 0.0,
    background_cut: float = 0.0,
    x_bin_m: float = 0.01,
    z_bin_m: float = 0.01,
) -> dict:
    """
    Topology-based stand/board counter.

    point_cloud_m_idx columns:
      0: x (meters, left/right)
      1: y (meters, height)  [not used directly here]
      2: z_clicks (encoder counts, NOT meters)

    Tunable grid:
      x_bin_m: width of X bins in meters (e.g. 0.02 = 2 cm)
      z_bin_m: length of Z bins in meters along travel (e.g. 0.02 = 2 cm)
    """
    if point_cloud_m_idx is None or point_cloud_m_idx.size == 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    pc_arr = np.asarray(point_cloud_m_idx, dtype=float)
    if pc_arr.ndim != 2 or pc_arr.shape[1] < 3:
        raise ValueError("point_cloud_m_idx must be (N,3) with x,y,z_index")

    # ---------------------------
    # 1) DataFrame + X / Z binning
    # ---------------------------
    # Interpret column 2 as encoder counts
    df = pd.DataFrame(pc_arr[:, :3], columns=("x", "y", "z_clicks"))

    # X binning (meters → binned)
    inv_x = 1.0 / float(x_bin_m)
    df["x_bin"] = np.floor(df["x"].to_numpy() * inv_x) / inv_x

    # Z binning: encoder counts → coarse index via z_bin_m and mm_per_click
    clicks = df["z_clicks"].to_numpy()
    if clicks.size == 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    clicks_min = np.min(clicks)
    clicks_rel = clicks - clicks_min

    # how many encoder clicks per Z bin?
    clicks_per_bin = max(int(round((z_bin_m * 1000.0) / float(mm_per_click))), 1)
    z_index = np.floor(clicks_rel / clicks_per_bin)
    df["z_bin"] = z_index

    # counts per (x_bin, z_bin)
    pc = df.groupby(["x_bin", "z_bin"], as_index=False).size()
    if pc.empty:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    # ---------------------------
    # 2) Pivot to 2D grid for persistence
    # ---------------------------
    grid = pc.pivot_table(
        index="x_bin",     # rows: X bins (left/right)
        columns="z_bin",   # cols: coarse Z bins along travel
        values="size",
        fill_value=0.0,
    )

    # sort X descending, Z ascending (to match old convention)
    grid = grid.sort_index(ascending=False)
    grid = grid.reindex(sorted(grid.columns), axis=1)

    im = grid.to_numpy(dtype=float)
    if im.size == 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    # ---------------------------
    # 3) Normalize + background cut
    # ---------------------------
    max_val = np.max(im)
    if max_val <= 0:
        return {"count": 0.0, "count_raw": 0.0, "points": []}

    im = im / max_val
    if background_cut is not None and background_cut > 0:
        im[im < background_cut] = 0.0

    # ---------------------------
    # 4) Run persistence
    # ---------------------------
    g0 = persistence(im)

    xs = grid.index.to_numpy()   # x_bin values (sorted descending)
    zs = grid.columns.to_numpy() # z_bin indices (sorted ascending)

    def ind_to_coord(p):
        return (xs[p[0]], zs[p[1]])

    points = []
    count = 0
    for i, (q, birth, per, death_pixel) in enumerate(g0):
        points.append(ind_to_coord(q))
        if per < min_persistence:
            count = i
            break
    else:
        count = len(g0)

    # ---------------------------
    # 5) Compute span in meters and normalize
    # ---------------------------
    z_vals_clicks = pc_arr[:, 2]
    if z_vals_clicks.size > 0:
        span_clicks = float(np.max(z_vals_clicks) - np.min(z_vals_clicks))
    else:
        span_clicks = 0.0

    distance_m = (span_clicks * mm_per_click) / 1000.0
    norm = count / distance_m if distance_m > 0 else float("nan")

    return {
        "count": norm,              # components per meter
        "count_raw": float(count),  # total components above min_persistence
        "points": points,           # (x_bin, z_bin_index) of each feature
    }
