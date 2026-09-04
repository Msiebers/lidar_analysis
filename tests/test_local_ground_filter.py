import numpy as np
import pandas as pd
import pytest

from lidar_analysis.pointcloud_ops import add_local_ground_height, local_ground_filter


def _cloud(missing=(), bad=None, reverse=False):
    rows = []
    for ix in range(-2, 3):
        for iz in range(5):
            x, z = (ix + .5) * 50, (iz + .5) * 50
            z = -z if reverse else z
            ground = -300 if bad == (ix, iz) else 100 + 5 * ix + 2 * iz
            if (ix, iz) not in missing:
                rows.extend((x, ground + j * .1, z, "ground") for j in range(5))
            rows.append((x, ground + 200, z, "canopy"))
    return pd.DataFrame(rows, columns=["X", "Y", "Z", "class"])


def _estimate(df, **kwargs):
    return add_local_ground_height(
        df, x_bin_size_m=50, z_bin_size_m=50, ground_quantile=.05,
        min_points_per_xz_bin=5, **kwargs)


def test_grid_ground_retains_rows_and_recovers_sloped_ground_and_canopy():
    df = _cloud()
    out = _estimate(df)
    assert len(out) == len(df)
    assert {"ground_Y", "height_agl", "ground_support"} <= set(out)
    assert out.loc[out["class"] == "ground", "height_agl"].abs().median() < 2
    assert out.loc[out["class"] == "canopy", "height_agl"].median() == pytest.approx(200, abs=2)


def test_grid_is_snapped_and_opposite_travel_is_symmetric():
    forward = _estimate(_cloud())
    reverse = _estimate(_cloud(reverse=True))
    assert forward.loc[forward["class"] == "canopy", "height_agl"].median() == pytest.approx(
        reverse.loc[reverse["class"] == "canopy", "height_agl"].median(), abs=1e-6)
    shifted = _cloud(); shifted["X"] += 10; shifted["Z"] += 10
    assert _estimate(shifted).height_agl.notna().all()


def test_missing_cells_fill_locally_but_large_holes_stay_unreliable():
    near = _estimate(_cloud(missing={(0, 2)}))
    assert (near.ground_support == "interpolated").any()
    far = _estimate(_cloud(missing={(ix, iz) for ix in (-1, 0, 1) for iz in (1, 2, 3)}))
    assert (far.ground_support == "unreliable").any() or far.ground_Y.isna().any()


def test_isolated_low_or_vegetation_only_candidate_is_not_trusted():
    low = _estimate(_cloud(bad=(0, 2)))
    cell = (low.X == 25) & (low.Z == 125)
    assert not (low.loc[cell, "ground_support"] == "observed").all()
    vegetation = _cloud(); vegetation.loc[cell, "Y"] += 300
    out = _estimate(vegetation)
    assert not (out.loc[cell, "ground_support"] == "observed").all()


def test_filter_uses_agl_after_estimation_and_unsupported_surface_stays_nan():
    out = local_ground_filter(
        _cloud(), x_bin_size_m=50, z_bin_size_m=50, ground_quantile=.05,
        min_points_per_xz_bin=5, min_height_agl_m=50)
    assert set(out["class"]) == {"canopy"}
    unsupported = add_local_ground_height(
        _cloud(), x_bin_size_m=50, z_bin_size_m=50, min_points_per_xz_bin=100)
    assert unsupported.ground_Y.isna().all()


def test_x_and_z_cell_sizes_are_independently_configurable():
    out = add_local_ground_height(
        _cloud(), x_bin_size_m=50, z_bin_size_m=100,
        ground_quantile=.05, min_points_per_xz_bin=5)
    assert out.height_agl.notna().all()
