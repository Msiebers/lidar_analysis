#!/usr/bin/python3
"""A simple implementation of persistent homology on 2D images.

Optimized variant: identical output to the legacy implementation, but the
high-to-low ordering uses a vectorized argsort and the per-pixel neighbor
scan is inlined to remove generator/list-comprehension overhead. The
union-find semantics are unchanged.
"""
import numpy as np

from .union_find import UnionFind


def get(im, p):
    return im[p[0]][p[1]]


def iter_neighbors(p, w, h):
    # Kept for API/back-compat in case anything imports it directly.
    y, x = p
    neigh = [(y + j, x + i) for i in [-1, 0, 1] for j in [-1, 0, 1]]
    for j, i in neigh:
        if j < 0 or j >= h:
            continue
        if i < 0 or i >= w:
            continue
        if j == y and i == x:
            continue
        yield j, i


_OFFSETS = ((-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1))


def persistence(im):
    im = np.asarray(im)
    h, w = im.shape

    # High-to-low ordering of all pixels. The legacy code used list.sort with
    # reverse=True, which is stable; a stable argsort on negated values
    # reproduces the same tie ordering.
    flat = im.ravel()
    order = np.argsort(-flat, kind="stable")
    ys = (order // w).astype(np.intp)
    xs = (order % w).astype(np.intp)

    uf = UnionFind()
    groups0 = {}

    for i in range(order.size):
        y = int(ys[i])
        x = int(xs[i])
        p = (y, x)
        v = float(im[y, x])

        # Inline neighbor scan: bounds-check, dict membership, dedupe roots.
        seen = set()
        nc = []
        for dy, dx in _OFFSETS:
            ny = y + dy
            if ny < 0 or ny >= h:
                continue
            nx = x + dx
            if nx < 0 or nx >= w:
                continue
            q = (ny, nx)
            if q in uf:
                r = uf[q]
                if r not in seen:
                    seen.add(r)
                    nc.append((float(im[r[0], r[1]]), r))

        nc.sort(reverse=True)

        if i == 0:
            groups0[p] = (v, v, None)
        uf.add(p, -i)

        if nc:
            oldp = nc[0][1]
            uf.union(oldp, p)
            for bl, q in nc[1:]:
                rq = uf[q]
                if rq not in groups0:
                    groups0[rq] = (bl, bl - v, p)
                uf.union(oldp, q)

    groups0 = [(k, groups0[k][0], groups0[k][1], groups0[k][2]) for k in groups0]
    groups0.sort(key=lambda g: g[2], reverse=True)
    return groups0
