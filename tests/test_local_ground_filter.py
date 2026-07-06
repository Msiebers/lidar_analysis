import numpy as np
import pandas as pd
import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pointcloud_ops import add_local_ground_height, height_agl_filter, local_ground_filter


def _ground_fixture():
    z = np.repeat(np.arange(4, dtype=float) * 0.15, 6)
    ground = 0.01 * z
    y = np.tile([0.0, 0.01, 0.04, 0.08, 0.20, 0.35], 4) + ground
    return pd.DataFrame({
        "source_index": np.arange(z.size),
        "time_s": np.linspace(0, 1, z.size),
        "phi": 1.0,
        "theta": 2.0,
        "dist_mm": 100.0,
        "range_m": 0.1,
        "encoder": 5.0,
        "roll_deg": 0.0,
        "pitch_deg": 0.0,
        "yaw_deg": 0.0,
        "X": np.linspace(-0.1, 0.1, z.size),
        "Y": y,
        "Z": z,
        "RSSI": 42.0,
        "rssi_norm": 0.5,
    })


def test_add_local_ground_height_adds_columns_preserves_columns_and_rows():
    df = _ground_fixture()
    out = add_local_ground_height(df, bin_size_m=0.15, ground_quantile=0.03, smooth_bins=3, min_points_per_bin=3)

    assert "ground_Y" in out.columns
    assert "height_agl" in out.columns
    assert list(out.columns[: len(df.columns)]) == list(df.columns)
    assert len(out) == len(df)
    assert list(out["source_index"]) == list(df["source_index"])


def test_height_agl_filter_reduces_rows_and_preserves_metadata_columns():
    df = add_local_ground_height(_ground_fixture(), bin_size_m=0.15, ground_quantile=0.03, smooth_bins=1, min_points_per_bin=3)
    out = height_agl_filter(df, min_height_agl_m=0.08)

    assert 0 < len(out) < len(df)
    for col in ["source_index", "time_s", "phi", "theta", "dist_mm", "range_m", "encoder", "roll_deg", "pitch_deg", "yaw_deg", "X", "Y", "Z", "RSSI", "rssi_norm", "ground_Y", "height_agl"]:
        assert col in out.columns


def test_local_ground_filter_retains_ground_columns():
    out = local_ground_filter(_ground_fixture(), bin_size_m=0.15, ground_quantile=0.03, smooth_bins=1, min_points_per_bin=3, min_height_agl_m=0.08)
    assert {"ground_Y", "height_agl"}.issubset(out.columns)
    assert len(out) > 0


def test_empty_dataframe_gets_ground_columns_without_crashing():
    df = pd.DataFrame(columns=["X", "Y", "Z", "RSSI", "source_index"])
    out = add_local_ground_height(df)
    assert list(out.columns) == ["X", "Y", "Z", "RSSI", "source_index", "ground_Y", "height_agl"]
    assert out.empty


def test_height_agl_filter_missing_column_raises_clear_error():
    with pytest.raises(ValueError, match="height_agl_filter requires column"):
        height_agl_filter(pd.DataFrame({"X": [0.0], "Y": [0.0], "Z": [0.0]}))


def test_default_config_local_ground_filter_disabled():
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=".", cart_id="CART")
    assert cfg.use_local_ground_filter is False
    assert cfg.local_ground_z_bin_m == 0.15
    assert cfg.local_ground_pre_y_min_m is None
    assert cfg.local_ground_pre_y_max_m is None
    assert cfg.min_height_agl_m == 0.08
