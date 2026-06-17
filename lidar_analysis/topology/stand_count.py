import numpy as np
import pandas as pd

from .imagepers import persistence


class TopologyResult(dict):
    def __iter__(self):
        yield self["count"]
        yield self["points"]


def topology_stand_count(
    point_cloud,
    min_persistence: float = 0.35,
    max_grid_cells: int = 500_000,
    debug: bool = True,
):
    """
    Legacy topology stand count.

    Expects x, y, z in meters.
      x = lateral position
      y = height
      z = travel/scan-position axis, preferably already discretized/binned

    Returns:
        {"count": count_per_meter, "points": birth_points, "count_raw": raw_count}
    """
    if point_cloud is None:
        return TopologyResult({"count": float("nan"), "points": [], "count_raw": float("nan")})

    if isinstance(point_cloud, pd.DataFrame):
        df = point_cloud.copy()
        required = ["x", "y", "z"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"topology_stand_count missing required columns: {missing}")
        arr = df[["x", "y", "z"]].to_numpy(dtype=float, copy=False)
    else:
        arr = np.asarray(point_cloud, dtype=float)
        if arr.ndim != 2 or arr.shape[1] < 3:
            raise ValueError("topology_stand_count expects Nx3 point cloud with x,y,z in meters")
        arr = arr[:, :3]

    if arr.shape[0] == 0:
        return TopologyResult({"count": float("nan"), "points": [], "count_raw": float("nan")})

    z = arr[:, 2]
    distance = float(np.nanmax(z) - np.nanmin(z))
    if not np.isfinite(distance) or distance <= 0:
        return TopologyResult({"count": float("nan"), "points": [], "count_raw": float("nan")})

    df = pd.DataFrame(arr, columns=("x", "y", "z"))
    # Legacy behavior: 0.02 m x bins.
    df["round_x"] = np.floor(df["x"] * 50.0) / 50.0
    pc = df.groupby(["round_x", "z"], as_index=False).size()

    xs = pd.DataFrame(sorted(set(pc["round_x"]), reverse=True), columns=("round_x",))
    zs = pd.DataFrame(sorted(set(pc["z"])), columns=("z",))

    n_x = len(xs)
    n_z = len(zs)
    grid_cells = n_x * n_z

    if debug:
        print(
            f"[TOPO_DEBUG] points={arr.shape[0]} "
            f"unique_x_bins={n_x} unique_z={n_z} grid_cells={grid_cells} "
            f"distance_m={distance:.3f}"
        )

    if grid_cells > max_grid_cells:
        raise RuntimeError(
            f"Topology grid too large: {grid_cells} cells "
            f"({n_x} x-bins × {n_z} z-bins). "
            f"Increase z_bin_m, use scan_position_m/travel_z_m, or raise max_grid_cells."
        )

    # Complete x/z grid.
    dims = xs.merge(zs, how="cross")
    grid_as_table = pc.merge(
        dims,
        left_on=("round_x", "z"),
        right_on=("round_x", "z"),
        how="outer",
    )
    grid_as_table = grid_as_table.sort_values(
        by=["round_x", "z"],
        ascending=(False, True),
    )

    im = np.array(grid_as_table["size"])
    im.shape = (len(xs), len(zs))
    im[np.isnan(im)] = 0

    max_im = float(np.max(im))
    if max_im <= 0:
        return TopologyResult({"count": float("nan"), "points": [], "count_raw": float("nan")})
    im = im / max_im

    g0 = persistence(im)

    xs = xs.sort_values(by="round_x", ascending=False).reset_index(drop=True)
    zs = zs.sort_values(by="z").reset_index(drop=True)

    # Index plain numpy arrays instead of pandas .iloc per component.
    xs_arr = xs["round_x"].to_numpy()
    zs_arr = zs["z"].to_numpy()

    def ind_to_coord(p):
        return (xs_arr[p[0]], zs_arr[p[1]])

    birth_points = []
    raw_count = 0
    for i, item in enumerate(g0):
        # Legacy imagepers returns:
        #   (birth_pixel, birth_level, persistence, death_pixel)
        q, birth_level, pers, death_pixel = item
        birth_points.append(ind_to_coord(q))
        if pers < float(min_persistence):
            raw_count = i
            break
    else:
        # If none dropped below threshold, count all components.
        raw_count = len(g0)

    return TopologyResult({
        "count": float(raw_count) / distance,
        "points": birth_points,
        "count_raw": float(raw_count),
    })
