import numpy as np

from .union_find import UnionFind


_NEIGHBORS_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1)]


def persistence(im: np.ndarray):
    im = np.asarray(im, dtype=float)
    if im.ndim != 2:
        raise ValueError("persistence expects a 2D image")
    h, w = im.shape
    if h == 0 or w == 0:
        return []

    coords = [(r, c) for r in range(h) for c in range(w)]
    coords.sort(key=lambda rc: im[rc[0], rc[1]], reverse=True)

    uf = UnionFind()
    active = np.zeros((h, w), dtype=bool)
    birth = {}
    pers = []

    for r, c in coords:
        v = float(im[r, c])
        idx = (r, c)
        uf.make_set(idx)
        active[r, c] = True
        root = idx
        birth[root] = v

        neighbor_roots = set()
        for dr, dc in _NEIGHBORS_8:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and active[rr, cc]:
                neighbor_roots.add(uf.find((rr, cc)))
        if not neighbor_roots:
            continue

        roots = list(neighbor_roots)
        keep = max(roots, key=lambda rt: birth[rt])
        for rt in roots:
            if rt == keep:
                continue
            b = birth[rt]
            pers.append((b, v, b - v))
            keep = uf.union(keep, rt)
            birth[keep] = max(birth.get(keep, v), birth[rt])

        keep = uf.union(keep, idx)
        birth[keep] = max(birth.get(keep, v), v)

    for rt in list({uf.find(k) for k in uf.parent.keys()}):
        b = birth.get(rt, 0.0)
        pers.append((b, 0.0, b))

    pers.sort(key=lambda t: t[2], reverse=True)
    return pers
