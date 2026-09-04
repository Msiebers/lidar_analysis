import numpy as np
import pytest

import lidar_analysis.pai as pai_module
from lidar_analysis.config import AnalysisConfig
from lidar_analysis.fad import Box3D
from lidar_analysis.pai import _fit_transmission, compute_pai_traits, layer_path_matrix
from lidar_analysis.pipeline_core import Plot, analyze_plot


BOX = Box3D(0.0, 1.0, 0.0, 1.0, 0.0, 1.0)


def _horizontal(ranges, y=0.5, layers=False, joint=False):
    ranges = np.asarray(ranges, dtype=float)
    n = len(ranges)
    traits = compute_pai_traits(
        origins_m=np.tile([-1.0, y, 0.5], (n, 1)),
        directions_m=np.tile([1.0, 0.0, 0.0], (n, 1)),
        ranges_m=ranges,
        raw_hit_mask=np.isfinite(ranges),
        box=BOX,
        layer_thickness_m=0.5 if layers else None,
        run_joint_profile=joint,
    )
    return traits


def test_all_gaps_return_zero_pai_and_return_beyond_box_is_gap():
    result = _horizontal([np.inf, 3.0, np.inf])
    assert result["pai_pad_m2_m3"] == 0.0
    assert result["pai_m2_m2"] == 0.0
    assert result["pai_gap_fraction"] == 1.0
    assert result["pai_n_full_gaps"] == 3


def test_mixed_hits_and_gaps_are_finite_and_hit_location_invariant():
    near = _horizontal([1.01, 1.02, np.inf, 3.0])
    far = _horizontal([1.98, 1.99, np.inf, 3.0])
    assert 0.0 < near["pai_pad_m2_m3"] < np.inf
    assert near["pai_pad_m2_m3"] == pytest.approx(far["pai_pad_m2_m3"])
    assert near["pai_log_likelihood"] == pytest.approx(far["pai_log_likelihood"])


def test_spherical_g_is_fixed_at_one_half_without_changing_results():
    default = _horizontal([1.2, np.inf])
    explicit = compute_pai_traits(
        origins_m=np.tile([-1.0, 0.5, 0.5], (2, 1)),
        directions_m=np.tile([1.0, 0.0, 0.0], (2, 1)),
        ranges_m=np.array([1.2, np.inf]), raw_hit_mask=np.array([True, False]),
        box=BOX, g_function="spherical", g_value=0.5, layer_thickness_m=None,
    )
    assert explicit["pai_pad_m2_m3"] == pytest.approx(default["pai_pad_m2_m3"])
    assert explicit["pai_g_function"] == "spherical"
    assert explicit["pai_g_value"] == 0.5
    with pytest.raises(ValueError, match="requires pai_g_value=0.5"):
        compute_pai_traits(
            origins_m=np.empty((0, 3)), directions_m=np.empty((0, 3)),
            ranges_m=np.empty(0), raw_hit_mask=np.empty(0, dtype=bool),
            box=BOX, g_function="spherical", g_value=0.4,
        )


def test_prehit_is_excluded_and_counted():
    result = _horizontal([0.5, 1.5, np.inf])
    assert result["pai_n_hits_before_box"] == 1
    assert result["pai_n_rays_observed"] == 2
    assert result["pai_n_hits"] == 1
    assert result["pai_n_full_gaps"] == 1


def test_all_hits_are_reported_as_saturated_not_finite():
    result = _horizontal([1.2, 1.8])
    assert result["pai_saturated"] is True
    assert result["pai_converged"] is False
    assert np.isnan(result["pai_pad_m2_m3"])
    assert result["pai_gap_fraction"] == 0.0


def test_variable_chords_are_not_replaced_by_their_mean():
    chords = np.array([0.2, 0.4, 1.5, 2.0])
    gaps = np.array([False, False, True, True])
    fitted, _, converged, _ = _fit_transmission(chords, gaps, 0.5)
    mean_chord_shortcut = -np.log(np.mean(gaps)) / (0.5 * np.mean(chords))
    assert converged
    assert fitted != pytest.approx(mean_chord_shortcut, rel=0.05)


def test_whole_box_known_simulation():
    rng = np.random.default_rng(42)
    known_mu = 1.4
    chords = rng.uniform(0.2, 2.0, 20000)
    gaps = rng.random(chords.size) < np.exp(-0.5 * known_mu * chords)
    fitted, _, converged, _ = _fit_transmission(chords, gaps, 0.5)
    assert converged
    assert fitted == pytest.approx(known_mu, rel=0.04)


def test_profile_path_geometry_and_identifiability():
    origins = np.array([[-1.0, 0.25, 0.5], [-1.0, 0.75, 0.5]])
    directions = np.tile([1.0, 0.0, 0.0], (2, 1))
    matrix = layer_path_matrix(origins, directions, BOX, [0.0, 0.5, 1.0])
    np.testing.assert_allclose(matrix, [[1.0, 0.0], [0.0, 1.0]])

    repeated_origins = np.repeat(origins, 2, axis=0)
    repeated_directions = np.repeat(directions, 2, axis=0)
    kwargs = dict(
        origins_m=repeated_origins, directions_m=repeated_directions,
        raw_hit_mask=np.array([True, False, True, False]), box=BOX,
        layer_thickness_m=0.5, run_joint_profile=True,
    )
    near = compute_pai_traits(ranges_m=np.array([1.1, np.inf, 1.1, np.inf]), **kwargs)
    far = compute_pai_traits(ranges_m=np.array([1.9, np.inf, 1.9, np.inf]), **kwargs)
    assert near["pai_profile_identifiable"] is True
    assert near["pai_profile_rank"] == 2
    assert np.isfinite(near["pai_profile_condition_number"])
    assert near["pai_profile_min_singular_value"] > 0.0
    assert near["pai_from_layers_m2_m2"] == pytest.approx(far["pai_from_layers_m2_m2"])


def test_rank_deficient_profile_is_not_fabricated():
    result = _horizontal([1.2, np.inf, 1.5, np.inf], y=0.25, layers=True, joint=True)
    assert result["pai_profile_rank"] == 1
    assert result["pai_profile_identifiable"] is False
    assert result["pai_profile_min_singular_value"] == 0.0
    assert np.isinf(result["pai_profile_condition_number"])
    assert np.isnan(result["pai_from_layers_m2_m2"])
    assert np.isnan(result["pai_layer_050_100_pad_m2_m3"])


def test_conditional_layer_gap_hit_and_censored_counts():
    ranges = np.array([3.0, 1.5, 0.5])
    result = compute_pai_traits(
        origins_m=np.tile([-1.0, 0.25, 0.5], (3, 1)),
        directions_m=np.tile([1.0, 0.0, 0.0], (3, 1)),
        ranges_m=ranges, raw_hit_mask=np.ones(3, dtype=bool), box=BOX,
        layer_thickness_m=0.5, run_conditional_profile=True,
    )
    prefix = "pai_layer_000_050_conditional_"
    assert result[prefix + "n_intersecting"] == 3
    assert result[prefix + "n_observed"] == 2
    assert result[prefix + "n_hits"] == 1
    assert result[prefix + "n_gaps"] == 1
    assert result[prefix + "n_censored"] == 1
    assert result["pai_layer_050_100_conditional_n_observed"] == 0
    assert np.isnan(result["pai_layer_050_100_conditional_pad_m2_m3"])


def test_conditional_profile_uses_layer_not_within_layer_hit_location():
    common = dict(
        origins_m=np.tile([-1.0, 0.25, 0.5], (4, 1)),
        directions_m=np.tile([1.0, 0.0, 0.0], (4, 1)),
        raw_hit_mask=np.array([True, True, False, True]), box=BOX,
        layer_thickness_m=0.5, run_conditional_profile=True,
    )
    near = compute_pai_traits(ranges_m=np.array([1.1, 1.2, np.inf, 3.0]), **common)
    far = compute_pai_traits(ranges_m=np.array([1.8, 1.9, np.inf, 3.0]), **common)
    key = "pai_layer_000_050_conditional_pad_m2_m3"
    assert near[key] == pytest.approx(far[key])
    assert near[key] == pytest.approx(2.0 * np.log(2.0), rel=1e-5)


def test_conditional_hit_in_later_layer_is_gap_in_prior_layer():
    direction = np.array([1.0, 0.5, 0.0])
    direction /= np.linalg.norm(direction)
    common = dict(
        origins_m=np.array([[-1.0, -0.25, 0.5]]),
        directions_m=direction[None, :], raw_hit_mask=np.array([True]), box=BOX,
        layer_thickness_m=0.5, run_conditional_profile=True,
    )
    upper_hit = compute_pai_traits(ranges_m=np.array([2.0]), **common)
    lower_hit = compute_pai_traits(ranges_m=np.array([1.4]), **common)
    assert upper_hit["pai_layer_000_050_conditional_n_gaps"] == 1
    assert upper_hit["pai_layer_050_100_conditional_n_hits"] == 1
    assert lower_hit["pai_layer_000_050_conditional_n_hits"] == 1
    assert lower_hit["pai_layer_050_100_conditional_n_censored"] == 1


def test_conditional_layer_all_gap_all_hit_edges_and_whole_box_invariance():
    common = dict(
        origins_m=np.tile([-1.0, 0.25, 0.5], (2, 1)),
        directions_m=np.tile([1.0, 0.0, 0.0], (2, 1)), box=BOX,
        layer_thickness_m=0.5,
    )
    gaps = compute_pai_traits(
        ranges_m=np.array([np.inf, 3.0]), raw_hit_mask=np.array([False, True]),
        run_conditional_profile=True, **common,
    )
    hits = compute_pai_traits(
        ranges_m=np.array([1.2, 1.8]), raw_hit_mask=np.array([True, True]),
        run_conditional_profile=True, **common,
    )
    assert gaps["pai_layer_000_050_conditional_pad_m2_m3"] == 0.0
    assert gaps["pai_layer_000_050_conditional_pai_m2_m2"] == 0.0
    assert np.isnan(hits["pai_layer_000_050_conditional_pad_m2_m3"])
    assert hits["pai_layer_000_050_conditional_saturated"] is True

    mixed_args = dict(
        ranges_m=np.array([1.2, np.inf]), raw_hit_mask=np.array([True, False]), **common,
    )
    existing = compute_pai_traits(run_conditional_profile=False, **mixed_args)
    experimental = compute_pai_traits(run_conditional_profile=True, **mixed_args)
    assert experimental["pai_whole_box_m2_m2"] == pytest.approx(existing["pai_m2_m2"])
    assert experimental["pai_whole_box_pad_m2_m3"] == pytest.approx(existing["pai_pad_m2_m3"])
    assert experimental["pai_conditional_profile_complete"] is False
    assert np.isnan(experimental["pai_m2_m2"])


def test_complete_conditional_sum_is_primary_pai():
    origins = np.array([[-1.0, 0.25, 0.5]] * 2 + [[-1.0, 0.75, 0.5]] * 2)
    result = compute_pai_traits(
        origins_m=origins,
        directions_m=np.tile([1.0, 0.0, 0.0], (4, 1)),
        ranges_m=np.array([1.5, np.inf, 1.5, np.inf]),
        raw_hit_mask=np.array([True, False, True, False]), box=BOX,
        layer_thickness_m=0.5, run_conditional_profile=True,
    )
    layer_sum = sum(
        result[f"pai_layer_{label}_conditional_pai_m2_m2"]
        for label in ("000_050", "050_100")
    )
    assert result["pai_conditional_profile_complete"] is True
    assert result["pai_conditional_from_layers_m2_m2"] == pytest.approx(layer_sum)
    assert result["pai_m2_m2"] == pytest.approx(layer_sum)
    assert result["pai_height_m"] == pytest.approx(1.0)
    assert result["pai_layer_thickness_m"] == pytest.approx(0.5)
    assert result["pai_n_layers"] == 2
    assert sum(layer["pai_layer_m2_m2"] for layer in result["_pai_layers"]) == pytest.approx(result["pai_m2_m2"])
    for layer in result["_pai_layers"]:
        assert layer["pai_layer_m2_m2"] == pytest.approx(
            layer["pad_layer_m2_m3"] * layer["layer_thickness_m"]
        )


def test_conditional_profile_honors_include_layer_columns_false():
    result = compute_pai_traits(
        origins_m=np.array([[-1.0, 0.25, 0.5]] * 2 + [[-1.0, 0.75, 0.5]] * 2),
        directions_m=np.tile([1.0, 0.0, 0.0], (4, 1)),
        ranges_m=np.array([1.5, np.inf, 1.5, np.inf]),
        raw_hit_mask=np.array([True, False, True, False]), box=BOX,
        layer_thickness_m=0.5, run_conditional_profile=True,
        include_layer_columns=False,
    )
    assert result["pai_conditional_profile_complete"] is True
    assert np.isfinite(result["pai_conditional_from_layers_m2_m2"])
    assert result["pai_m2_m2"] == pytest.approx(result["pai_conditional_from_layers_m2_m2"])
    assert not any(key.startswith("pai_layer_") and key != "pai_layer_thickness_m" for key in result)


def test_joint_profile_default_off_skips_matrix(monkeypatch):
    monkeypatch.setattr(
        pai_module, "layer_path_matrix",
        lambda *_args, **_kwargs: pytest.fail("joint matrix was constructed"),
    )
    result = _horizontal([1.2, np.inf], layers=True)
    assert result["pai_profile_rank"] == 0
    assert result["pai_profile_converged"] is False


def test_pipeline_result_row_contains_independent_pai_fields(tmp_path):
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=tmp_path, cart_id="test")
    cfg.run_pai = True
    cfg.pai_run_layers = False
    cfg.row_width_u = 1.5
    plot = Plot("scan", "1", (0.0, 1000.0), str(tmp_path), scan_base="scan_001")
    plot.side_label = "right"
    plot.side_sign = "positive"
    data = np.array([[500.0, 600.0, 500.0, 1.0]] * 4, dtype=np.float32)
    fused = np.array([
        [0.0, 0.0, np.pi / 2, 500.0, 1.0, 500.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, np.pi / 2, 800.0, 1.0, 500.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, np.pi / 2, 0.0, 1.0, 500.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, np.pi / 2, 0.0, 1.0, 500.0, 0.0, 0.0, 0.0],
    ], dtype=np.float32)
    row = analyze_plot(
        plot, data, np.arange(4), fused, "scan_001", cfg, ["scan", "scan"],
        lidar_height_mm=500.0, step_mm=1.0,
    )
    assert row["pai_n_hits"] == 2
    assert row["pai_n_full_gaps"] == 2
    assert row["pai_pad_m2_m3"] > 0.0
    assert row["pai_x_min_m"] == 0.0
    assert row["pai_x_max_m"] == 1.5
