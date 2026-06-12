from pathlib import Path
import math

import numpy as np
import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pipeline_core import (
    Plot,
    _fad_x_bounds_for_plot,
    reconstruct_world_points,
    reconstruct_world_rays,
)


def _cfg() -> AnalysisConfig:
    return AnalysisConfig(data_dirs=[], calibration_dir=Path("."), cart_id="CART")


def test_fad_world_rays_match_reconstructed_point_frame():
    cfg = _cfg()
    fused_np = np.array(
        [
            [0.0, 0.0, math.pi / 2.0, 1000.0, 1.0, 2.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )

    points_mm, _ = reconstruct_world_points(
        fused_np,
        cfg,
        step_mm=500.0,
        lidar_height_mm=2000.0,
        roll_offset=0.0,
        pitch_offset=0.0,
    )
    origins_m, directions_m = reconstruct_world_rays(
        fused_np,
        cfg,
        step_mm=500.0,
        lidar_height_mm=2000.0,
        roll_offset=0.0,
        pitch_offset=0.0,
    )

    reconstructed_from_ray_m = origins_m[0] + directions_m[0]
    np.testing.assert_allclose(reconstructed_from_ray_m, points_mm[0, :3] / 1000.0, atol=1e-6)


def test_fad_x_bounds_follow_plot_side_logic():
    row_width_m = 1.5
    left_plot = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    right_plot = Plot("right", "A", (0.0, 1000.0), out_dir=".")
    single_plot = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    positive_side = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    positive_side.side_sign = "positive"
    negative_side = Plot("left", "A", (0.0, 1000.0), out_dir=".")
    negative_side.side_sign = "negative"

    assert _fad_x_bounds_for_plot(left_plot, ["left", "right"], row_width_m) == pytest.approx((0.0, 1.5))
    assert _fad_x_bounds_for_plot(right_plot, ["left", "right"], row_width_m) == pytest.approx((-1.5, 0.0))
    assert _fad_x_bounds_for_plot(single_plot, ["left", "left"], row_width_m) == pytest.approx((-1.5, 1.5))
    assert _fad_x_bounds_for_plot(positive_side, ["left", "left"], row_width_m) == pytest.approx((0.0, 1.5))
    assert _fad_x_bounds_for_plot(negative_side, ["left", "left"], row_width_m) == pytest.approx((-1.5, 0.0))
