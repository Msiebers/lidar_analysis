from __future__ import annotations

import numpy as np

from .union_find import UnionFind


def _get(im: np.ndarray, p: tuple[int, int]) -> float:
    return im[p[0]][p[1]]


def _iter_neighbors(p: tuple[int, int], w: int, h: int):
    y, x = p
    for j in [-1, 0, 1]:
        for i in [-1, 0, 1]:
            ny, nx = y + j, x + i
            if ny < 0 or ny >= h or nx < 0 or nx >= w:
                continue
            if ny == y and nx == x:
                continue
            yield ny, nx


def persistence(im: np.ndarray):
    im = np.asarray(im, dtype=float)
    if im.ndim != 2:
        raise ValueError("persistence expects a 2D image")
    h, w = im.shape
    idx = [(i, j) for i in range(h) for j in range(w)]
    idx.sort(key=lambda p: _get(im, p), reverse=True)
    uf = UnionFind()
    groups0 = {}

    def comp_birth(p):
        return _get(im, uf[p])

    for i, p in enumerate(idx):
        v = _get(im, p)
        ni = [uf[q] for q in _iter_neighbors(p, w, h) if q in uf]
        nc = sorted([(comp_birth(q), q) for q in set(ni)], reverse=True)
        if i == 0:
            groups0[p] = (v, v, None)
        uf.add(p, -i)
        if nc:
            oldp = nc[0][1]
            uf.union(oldp, p)
            for bl, q in nc[1:]:
                if uf[q] not in groups0:
                    groups0[uf[q]] = (bl, bl - v, p)
                uf.union(oldp, q)

    out = [(k, groups0[k][0], groups0[k][1], groups0[k][2]) for k in groups0]
    out.sort(key=lambda g: g[2], reverse=True)
    return out
