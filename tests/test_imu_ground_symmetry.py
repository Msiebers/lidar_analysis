import numpy as np
from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pipeline_core import reconstruct_world_points


def _cfg(roll_sign=1.0, pitch_sign=-1.0):
    return AnalysisConfig(
        data_dirs=[], calibration_dir=".", cart_id="test", use_imu=True,
        imu_zero_mode="calibration", roll_sign=roll_sign, pitch_sign=pitch_sign,
    )


def test_roll_uses_travel_axis_and_sign_controls_left_right_vertical_shift():
    # theta +/-pi/2 produces symmetric +/-X beams before IMU rotation.
    fused = np.array([
        [0, 0, np.pi / 2, 1000, 1, 0, 10, 0, 0],
        [0, 0, -np.pi / 2, 1000, 1, 0, 10, 0, 0],
    ], dtype=np.float32)
    positive, _ = reconstruct_world_points(fused, _cfg(1), 0, 0, 0, 0)
    negative, _ = reconstruct_world_points(fused, _cfg(-1), 0, 0, 0, 0)

    assert positive[0, 1] > 0 > positive[1, 1]
    np.testing.assert_allclose(negative[:, 1], -positive[:, 1], atol=1e-4)
    np.testing.assert_allclose(positive[:, 2], 0, atol=1e-5)
