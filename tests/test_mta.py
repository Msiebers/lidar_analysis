from pathlib import Path

import numpy as np
import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.fad import Box3D
from lidar_analysis.mta import (
    angle_bin_edges_deg,
    angle_bin_indices,
    classify_first_events,
    compute_mta_traits,
    fit_angle_bin_edges_deg,
    folded_zenith_deg,
    mta_from_g_slope,
)
from lidar_analysis.pipeline_core import Plot, analyze_plot, write_scan_outputs


def _cfg(**kwargs):
    return AnalysisConfig(data_dirs=[], calibration_dir=Path("."), cart_id="CART", **kwargs)


def test_ray_box_first_event_geometry_and_tolerance():
    box = Box3D(-1.0, 1.0, -1.0, 1.0, 1.0, 3.0)
    origins = np.array([
        [0.0, 0.0, 0.0],  # return before
        [0.0, 0.0, 0.0],  # return inside
        [0.0, 0.0, 0.0],  # return after
        [0.0, 0.0, 2.0],  # origin inside
        [2.0, 0.0, 0.0],  # parallel and outside
        [0.0, 0.0, 1.0],  # boundary origin, explicit no-return
        [0.0, 0.0, 0.0],  # within entry tolerance
    ])
    directions = np.tile([0.0, 0.0, 1.0], (len(origins), 1))
    ranges = np.array([0.5, 1.5, 4.0, 0.5, 2.0, np.inf, 0.99995])
    hits = np.array([True, True, True, True, True, False, True])
    no_returns = np.array([False, False, False, False, False, True, False])

    result = classify_first_events(
        origins_m=origins, directions_m=directions, ranges_m=ranges,
        raw_hit_mask=hits, explicit_no_return_mask=no_returns, box=box,
        max_observation_range_m=60.0,
    )

    assert result["before"].tolist() == [True, False, False, False, False, False, False]
    assert result["hit"].tolist() == [False, True, False, True, False, False, True]
    assert result["gap"].tolist() == [False, False, True, False, False, True, False]
    np.testing.assert_allclose(result["path_m"][[1, 2, 3, 5, 6]], [0.5, 2.0, 0.5, 2.0, 0.0])
    assert np.all(np.sum(np.column_stack([result[key] for key in ("before", "hit", "gap", "unknown")]), axis=1) <= 1)


def test_valid_return_and_explicit_no_return_are_rejected():
    with pytest.raises(ValueError, match="cannot be both"):
        classify_first_events(
            origins_m=np.zeros((1, 3)), directions_m=np.array([[1.0, 0.0, 0.0]]),
            ranges_m=np.array([0.5]), raw_hit_mask=np.array([True]),
            explicit_no_return_mask=np.array([True]), box=Box3D(-1, 1, -1, 1, -1, 1),
            max_observation_range_m=60.0,
        )


def test_downward_ray_below_scanner_is_retained():
    result = classify_first_events(
        origins_m=np.array([[0.0, 0.40, 0.0]]),
        directions_m=np.array([[0.0, -2.0, 0.0]]),
        ranges_m=np.array([0.30]), raw_hit_mask=np.array([True]),
        explicit_no_return_mask=np.array([False]),
        box=Box3D(-1.0, 1.0, 0.0, 1.0, -1.0, 1.0),
        max_observation_range_m=60.0,
    )
    assert result["hit"][0]
    assert result["path_m"][0] == pytest.approx(0.30)
    assert result["vertical_component"][0] == pytest.approx(-1.0)


def test_unknown_and_multiple_echo_rows_do_not_become_extra_gaps_or_hits():
    box = Box3D(-1.0, 1.0, -1.0, 1.0, 1.0, 3.0)
    result = classify_first_events(
        origins_m=np.zeros((4, 3)), directions_m=np.tile([0.0, 0.0, 1.0], (4, 1)),
        ranges_m=np.array([2.5, 1.5, np.inf, np.inf]),
        raw_hit_mask=np.array([True, True, False, False]),
        explicit_no_return_mask=np.array([False, False, False, True]),
        ray_ids=np.array([10, 10, 11, 12]), box=box, max_observation_range_m=60.0,
    )
    assert len(result["hit"]) == 3
    assert (result["hit"].sum(), result["gap"].sum(), result["unknown"].sum()) == (1, 1, 1)
    assert result["path_m"][result["hit"]][0] == pytest.approx(0.5)


def test_no_return_requires_known_range_beyond_exit():
    common = dict(
        origins_m=np.array([[0.0, 0.0, 0.0]]), directions_m=np.array([[0.0, 0.0, 1.0]]),
        ranges_m=np.array([np.inf]), raw_hit_mask=np.array([False]),
        explicit_no_return_mask=np.array([True]),
        box=Box3D(-1.0, 1.0, -1.0, 1.0, 1.0, 3.0),
    )
    assert classify_first_events(**common, max_observation_range_m=2.0)["unknown"][0]
    assert classify_first_events(**common, max_observation_range_m=3.0)["gap"][0]
    assert classify_first_events(**common, max_observation_range_m=None)["unknown"][0]


def test_directional_rate_is_hits_divided_by_observed_path():
    root = np.sqrt(0.5)
    traits, bins = compute_mta_traits(
        origins_m=np.zeros((3, 3)),
        directions_m=np.tile([root, root, 0.0], (3, 1)),
        ranges_m=np.array([0.5, np.inf, np.inf]),
        raw_hit_mask=np.array([True, False, False]),
        explicit_no_return_mask=np.array([False, True, False]),
        box=Box3D(-1.0, 1.0, -1.0, 1.0, -1.0, 1.0),
        min_rays_per_bin=1,
        min_solid_angle_coverage=0.01,
        max_observation_range_m=60.0,
        diagnostic=True,
    )
    row = bins[(bins.mta_direction_group == "all") & (bins.mta_bin_lower_deg == 45.0)].iloc[0]
    assert row.mta_bin_n_hits == 1
    assert row.mta_bin_n_full_gaps == 1
    assert row.mta_bin_n_unknown == 1
    assert row.mta_bin_total_path_m == pytest.approx(0.5 + np.sqrt(2.0))
    assert row.mta_bin_lambda_m_inv == pytest.approx(1.0 / (0.5 + np.sqrt(2.0)))
    assert traits["mta_n_rays_observed"] == 2


def test_angle_folding_normalization_and_bin_edges():
    root = np.sqrt(0.5)
    directions = np.array([
        [0.0, 1.0, 0.0], [0.0, -2.0, 0.0], [root, root, 0.0],
        [-root, -root, 0.0], [2.0, 0.0, 0.0],
    ])
    angles, vertical, valid = folded_zenith_deg(directions)
    np.testing.assert_allclose(angles, [0.0, 0.0, 45.0, 45.0, 90.0], atol=1e-8)
    assert np.all(valid)
    np.testing.assert_allclose(vertical, [1.0, -1.0, root, -root, 0.0])
    edges = angle_bin_edges_deg(7.0)
    assert edges[-2:].tolist() == [84.0, 90.0]
    assert angle_bin_indices(np.array([0.0, 4.999, 5.0, 89.0, 90.0]), angle_bin_edges_deg(5.0)).tolist() == [0, 0, 1, 17, 17]


def test_exact_solid_angle_weights_sum_to_one_and_default_fit_boundaries():
    edges = angle_bin_edges_deg(7.0)
    weights = np.cos(np.radians(edges[:-1])) - np.cos(np.radians(edges[1:]))
    assert weights.sum() == pytest.approx(1.0)

    traits, bins = _synthetic_canopy(mu=0.8, g_slope=0.0, width=5.0, directions="upward")
    used = bins[(bins.mta_direction_group == "all") & bins.mta_bin_used_for_fit]
    assert used.mta_bin_lower_deg.tolist() == list(np.arange(25.0, 65.0, 5.0))
    assert traits["mta_n_fit_bins"] == 8


def _synthetic_canopy(*, mu: float, g_slope: float, width: float = 5.0,
                      directions: str = "both", n_per_bin: int = 1600,
                      omit_bin_center: float | None = None, diagnostic: bool = True,
                      min_solid_angle_coverage: float = 0.99):
    edges = angle_bin_edges_deg(width)
    origins, unit, ranges, hits, no_returns = [], [], [], [], []
    for low, high in zip(edges[:-1], edges[1:]):
        theta = np.radians((low + high) / 2.0)
        if omit_bin_center is not None and np.isclose(np.degrees(theta), omit_bin_center):
            continue
        g_value = 0.5 + g_slope * (theta - 1.0)
        for sign in ([1.0, -1.0] if directions == "both" else [1.0 if directions == "upward" else -1.0]):
            direction = np.array([np.sin(theta), sign * np.cos(theta), 0.0])
            length = 1.0 / max(abs(direction[0]), abs(direction[1]))
            hit_path = 0.2 * length
            rate = mu * g_value
            hit_fraction = rate * length / (1.0 + rate * (length - hit_path))
            n_hits = int(round(n_per_bin * hit_fraction))
            origins.extend([[0.0, 0.0, 0.0]] * n_per_bin)
            unit.extend([direction] * n_per_bin)
            ranges.extend([hit_path] * n_hits + [np.inf] * (n_per_bin - n_hits))
            hits.extend([True] * n_hits + [False] * (n_per_bin - n_hits))
            no_returns.extend([False] * n_hits + [True] * (n_per_bin - n_hits))
    return compute_mta_traits(
        origins_m=np.asarray(origins), directions_m=np.asarray(unit), ranges_m=np.asarray(ranges),
        raw_hit_mask=np.asarray(hits), explicit_no_return_mask=np.asarray(no_returns),
        box=Box3D(-1.0, 1.0, -1.0, 1.0, -1.0, 1.0),
        angle_bin_deg=width, min_rays_per_bin=10,
        min_solid_angle_coverage=min_solid_angle_coverage,
        max_observation_range_m=100.0, diagnostic=diagnostic,
    )


def test_density_changes_mu_but_not_mta():
    results = [_synthetic_canopy(mu=mu, g_slope=-0.25)[0] for mu in (0.25, 0.5, 1.0)]
    assert all(result["mta_qc_pass"] for result in results)
    assert results[0]["mta_mu_m2_m3"] < results[1]["mta_mu_m2_m3"] < results[2]["mta_mu_m2_m3"]
    assert np.ptp([result["mta_deg"] for result in results]) < 1.0


def test_missing_fit_bin_keeps_calculable_mta_but_warns():
    traits, _ = _synthetic_canopy(
        mu=0.6, g_slope=0.0, omit_bin_center=27.5,
        min_solid_angle_coverage=0.8,
    )
    assert np.isfinite(traits["mta_deg"])
    assert not traits["mta_qc_pass"]
    assert traits["mta_status"] == "warning_fit_angle_coverage"


def test_diagnostics_do_not_change_mta_calculation():
    with_diagnostics, bins = _synthetic_canopy(mu=0.6, g_slope=-0.2)
    without_diagnostics, no_bins = _synthetic_canopy(
        mu=0.6, g_slope=-0.2, diagnostic=False
    )
    assert no_bins is None
    assert bins is not None
    for key in ("mta_deg", "mta_method", "mta_qc_pass", "mta_status"):
        assert without_diagnostics[key] == with_diagnostics[key]


def test_orientation_response_and_spherical_reference():
    planophile = _synthetic_canopy(mu=0.6, g_slope=-0.4)[0]
    spherical = _synthetic_canopy(mu=0.6, g_slope=0.0)[0]
    erectophile = _synthetic_canopy(mu=0.6, g_slope=0.3)[0]
    assert planophile["mta_deg"] < spherical["mta_deg"] < erectophile["mta_deg"]
    assert spherical["mta_deg"] == pytest.approx(56.81964, abs=0.5)


def test_slope_outside_calibration_is_reported_as_numeric_warning():
    traits, _ = _synthetic_canopy(mu=0.6, g_slope=0.46)
    assert np.isfinite(traits["mta_deg"])
    assert not traits["mta_qc_pass"]
    assert "slope_outside_calibration_range" in traits["mta_status"]


@pytest.mark.parametrize("slope, expected", [(-0.6964, 1.0), (-0.1547, 50.0), (0.4431, 89.0)])
def test_licor_polynomial_reference_pairs(slope, expected):
    assert mta_from_g_slope(slope) == pytest.approx(expected, abs=3.2)


def test_upward_downward_symmetry():
    traits, _ = _synthetic_canopy(mu=0.6, g_slope=0.2, directions="both")
    assert traits["mta_upward_qc_pass"] and traits["mta_downward_qc_pass"]
    assert traits["mta_upward_deg"] == pytest.approx(traits["mta_downward_deg"], abs=0.1)


def test_too_few_fit_bins_is_genuinely_not_computable():
    traits, _ = compute_mta_traits(
        origins_m=np.array([[0.0, 0.0, 0.0]] * 3),
        directions_m=np.array([[0.0, 1.0, 0.0]] * 3),
        ranges_m=np.array([0.5, np.inf, np.inf]), raw_hit_mask=np.array([True, False, False]),
        explicit_no_return_mask=np.array([False, True, True]),
        box=Box3D(-1.0, 1.0, -1.0, 1.0, -1.0, 1.0),
        min_rays_per_bin=1, min_solid_angle_coverage=0.9, max_observation_range_m=60.0,
    )
    assert not traits["mta_qc_pass"]
    assert traits["mta_status"] == "too_few_fit_bins"


@pytest.mark.parametrize("width", [2.5, 5.0, 10.0])
def test_supported_bin_widths_run(width):
    traits, bins = _synthetic_canopy(mu=0.5, g_slope=0.0, width=width, directions="upward")
    assert traits["mta_angle_bin_deg"] == width
    assert traits["mta_qc_pass"]
    assert not bins.empty


@pytest.mark.parametrize("width, expected_bins", [(2.5, 16), (5.0, 8), (10.0, 4)])
def test_fit_bins_are_anchored_to_complete_25_65_interval(width, expected_bins):
    edges = fit_angle_bin_edges_deg(width)
    assert edges[0] == 25.0
    assert edges[-1] == 65.0
    assert len(edges) - 1 == expected_bins
    traits, bins = _synthetic_canopy(mu=0.5, g_slope=0.0, width=width, directions="upward")
    used = bins[(bins.mta_direction_group == "all") & (bins.mta_bin_role == "fit") & bins.mta_bin_used_for_fit]
    assert len(used) == expected_bins
    assert used.mta_bin_lower_deg.min() == 25.0
    assert used.mta_bin_upper_deg.max() == 65.0
    assert traits["mta_fit_angle_coverage"] == pytest.approx(1.0)


def test_standard_method_rejects_nonstandard_fit_bounds():
    with pytest.raises(ValueError, match="fixed 25-65"):
        compute_mta_traits(
            origins_m=np.empty((0, 3)), directions_m=np.empty((0, 3)),
            ranges_m=np.empty(0), raw_hit_mask=np.empty(0, dtype=bool),
            explicit_no_return_mask=np.empty(0, dtype=bool),
            box=Box3D(-1, 1, -1, 1, -1, 1), fit_angle_min_deg=30.0,
        )


def test_pipeline_run_mta_is_independent_of_lai_and_quiet_by_default(tmp_path, capsys):
    cfg = _cfg(run_mta=True, make_point_cloud=False, mta_min_rays_per_bin=1)
    plot = Plot("row", "1", (0.0, 1000.0), str(tmp_path), scan_base="scan")
    data = np.array([[500.0, 500.0, 500.0, 1.0]], dtype=np.float32)
    fused = np.array([[0.0, 0.0, np.pi / 2.0, 500.0, 1.0, 500.0, 0.0, 0.0, 0.0]], dtype=np.float32)

    result = analyze_plot(
        plot, data, np.array([0], dtype=np.int32), fused, "scan", cfg,
        ["row", "row"], 400.0, 1.0,
    )
    assert result["mta_method"] == "bounded_lang_v1"
    assert result["mta_status"] != "invalid_plot_volume"
    assert "lai_even" in result  # unchanged placeholder; LAI was not run
    assert not hasattr(plot, "mta_bin_diagnostics")

    write_scan_outputs("scan", cfg, plot)
    assert not list(tmp_path.glob("*mta*"))
    output = capsys.readouterr().out
    assert "[MTA" not in output
    assert "MTA=" not in output


def test_pipeline_never_enables_legacy_lai_mta(monkeypatch, tmp_path):
    import lidar_analysis.pipeline_core as pipeline

    calls = []
    def fake_lai(**kwargs):
        calls.append(kwargs)
        return {"lai_even": 1.0, "lai_uneven": 1.0, "lai_n_scans": 1, "lai_n_angles": 1}

    monkeypatch.setattr(pipeline, "compute_lai_trait_from_beam_rows", fake_lai)
    cfg = _cfg(run_lai=True, run_mta=True, make_point_cloud=False, mta_min_rays_per_bin=1)
    plot = Plot("row", "1", (0.0, 1000.0), str(tmp_path), scan_base="scan")
    data = np.array([[500.0, 500.0, 500.0, 1.0]], dtype=np.float32)
    fused = np.array([[0.0, 0.0, np.pi / 2.0, 500.0, 1.0, 500.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    result = pipeline.analyze_plot(
        plot, data, np.array([0], dtype=np.int32), fused, "scan", cfg,
        ["row", "row"], 400.0, 1.0,
    )
    assert calls and calls[0]["run_mta"] is False
    assert result["mta_method"] == "bounded_lang_v1"
