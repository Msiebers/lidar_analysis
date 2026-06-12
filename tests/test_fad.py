import math

import numpy as np
import pytest

from lidar_analysis import fad
from lidar_analysis.fad import (
    Box3D,
    box_is_valid,
    compute_fad_in_box,
    compute_fad_traits,
    estimate_fad_height_from_points,
    estimate_fad_height_from_y,
    make_fad_box_from_footprint_and_height,
    make_layer_edges,
)


def test_estimate_fad_height_filters_y_min_and_adds_buffer():
    y_m = np.array([-0.1, 0.0, 0.02, 0.10, 0.20, 0.30])

    result = estimate_fad_height_from_y(
        y_m,
        percentile=100.0,
        y_min_m=0.03,
        buffer_m=0.05,
    )

    assert result.height_m == pytest.approx(0.30)
    assert result.y_max_m == pytest.approx(0.35)
    assert result.n_input == 3
    assert result.n_used == 3
    assert result.n_removed == 0


def test_estimate_fad_height_from_points_honors_xz_footprint():
    points_xyz_m = np.array(
        [
            [0.0, 0.20, 0.0],
            [0.5, 0.50, 0.5],
            [2.0, 1.50, 0.5],  # outside x footprint
            [0.5, 2.00, 2.0],  # outside z footprint
        ]
    )

    result = estimate_fad_height_from_points(
        points_xyz_m,
        x_min_m=-0.1,
        x_max_m=1.0,
        z_min_m=-0.1,
        z_max_m=1.0,
        percentile=100.0,
        y_min_m=0.03,
    )

    assert result.height_m == pytest.approx(0.50)
    assert result.n_input == 2


def test_make_fad_box_from_footprint_and_height_and_validity():
    height = estimate_fad_height_from_y(
        np.array([0.10, 0.40]),
        percentile=100.0,
        y_min_m=0.03,
    )

    box = make_fad_box_from_footprint_and_height(
        x_min_m=-0.5,
        x_max_m=0.5,
        z_min_m=0.0,
        z_max_m=1.0,
        height=height,
        y_min_m=0.03,
    )

    assert box == Box3D(
        x_min=-0.5,
        x_max=0.5,
        y_min=0.03,
        y_max=0.4,
        z_min=0.0,
        z_max=1.0,
    )
    assert box_is_valid(box)
    assert not box_is_valid(Box3D(0.0, 0.0, 0.03, 0.4, 0.0, 1.0))


def test_compute_fad_in_box_counts_hits_gaps_and_occlusions():
    box = Box3D(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, z_min=1.0, z_max=3.0)
    origins_m = np.array(
        [
            [0.0, 0.0, 0.0],  # hit inside: free path 1.5 - 1.0 = 0.5
            [0.0, 0.0, 0.0],  # full gap through box: free path 3.0 - 1.0 = 2.0
            [0.0, 0.0, 0.0],  # hit before box: occluded and excluded
            [2.0, 0.0, 0.0],  # misses box
        ]
    )
    directions_m = np.tile(np.array([0.0, 0.0, 1.0]), (4, 1))
    ranges_m = np.array([1.5, math.inf, 0.5, 2.0])
    raw_hit_mask = np.array([True, False, True, True])

    result = compute_fad_in_box(
        origins_m=origins_m,
        directions_m=directions_m,
        ranges_m=ranges_m,
        raw_hit_mask=raw_hit_mask,
        box=box,
        g_function="spherical",
    )

    assert result.n_rays_total == 4
    assert result.n_rays_intersecting_box == 3
    assert result.n_rays_observed_in_box == 2
    assert result.n_hits_inside_box == 1
    assert result.n_full_gaps_through_box == 1
    assert result.n_hits_before_box == 1
    assert result.total_free_path_length_m == pytest.approx(2.5)
    assert result.total_projected_path_length_m == pytest.approx(1.25)
    assert result.contact_density_m_inv == pytest.approx(0.4)
    assert result.fad_m2_m3 == pytest.approx(0.8)
    assert result.gap_fraction == pytest.approx(0.5)
    assert result.g_assumption == "spherical"


def test_compute_fad_traits_can_skip_layer_columns():
    box = Box3D(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, z_min=1.0, z_max=3.0)
    origins_m = np.array([[0.0, 0.0, 0.0]])
    directions_m = np.array([[0.0, 0.0, 1.0]])
    ranges_m = np.array([2.0])
    raw_hit_mask = np.array([True])

    traits = compute_fad_traits(
        origins_m=origins_m,
        directions_m=directions_m,
        ranges_m=ranges_m,
        raw_hit_mask=raw_hit_mask,
        box=box,
        layer_thickness_m=1.0,
        include_layer_columns=False,
    )

    assert traits["fad_app_m2_m3"] == pytest.approx(2.0)
    assert traits["fad_n_layers"] == 2
    assert traits["fad_lai_from_layers"] == pytest.approx(4.0)
    assert not any(key.startswith("fad_layer_") for key in traits)


def test_invalid_box_traits_return_empty_whole_box_result():
    invalid_box = Box3D(x_min=0.0, x_max=1.0, y_min=0.03, y_max=float("nan"), z_min=0.0, z_max=1.0)

    traits = fad.compute_fad_traits(
        origins_m=np.zeros((2, 3)),
        directions_m=np.zeros((2, 3)),
        ranges_m=np.zeros(2),
        raw_hit_mask=np.zeros(2, dtype=bool),
        box=invalid_box,
    )

    assert math.isnan(traits["fad_app_m2_m3"])
    assert traits["fad_n_rays_total"] == 2
    assert traits["fad_n_rays_observed"] == 0
    assert "fad_n_layers" not in traits


def test_make_layer_edges_forces_final_edge_to_y_max():
    edges = make_layer_edges(y_min_m=0.03, y_max_m=0.26, layer_thickness_m=0.10)

    np.testing.assert_allclose(edges, np.array([0.03, 0.13, 0.23, 0.26]))
