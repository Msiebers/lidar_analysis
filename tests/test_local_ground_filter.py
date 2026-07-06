import numpy as np
import pandas as pd
import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pointcloud_ops import add_local_ground_height, height_agl_filter, local_ground_filter


def _tilted_ground_fixture():
    rows = []
    source_index = 0
    for z in np.linspace(0.0, 1000.0, 5):
        for x in np.linspace(-200.0, 200.0, 5):
            ground_y = 100.0 + 0.08 * x + 0.02 * z
            for rep in range(10):
                rows.append({
                    "source_index": source_index,
                    "time_s": source_index / 100.0,
                    "phi": 1.0,
                    "theta": 2.0,
                    "dist_mm": 100.0,
                    "range_m": 0.1,
                    "encoder": 5.0,
                    "roll_deg": 0.0,
                    "pitch_deg": 0.0,
                    "yaw_deg": 0.0,
                    "beam_id": rep,
                    "class": "ground",
                    "X": x + (rep - 4.5) * 0.5,
                    "Y": ground_y + ((rep % 3) - 1) * 1.0,
                    "Z": z + (rep - 4.5) * 1.0,
                    "RSSI": 42.0,
                    "rssi_norm": 0.5,
                })
                source_index += 1
            rows.append({
                "source_index": source_index,
                "time_s": source_index / 100.0,
                "phi": 1.0,
                "theta": 2.0,
                "dist_mm": 300.0,
                "range_m": 0.3,
                "encoder": 5.0,
                "roll_deg": 0.0,
                "pitch_deg": 0.0,
                "yaw_deg": 0.0,
                "beam_id": 99,
                "class": "canopy",
                "X": x,
                "Y": ground_y + 220.0,
                "Z": z,
                "RSSI": 84.0,
                "rssi_norm": 1.5,
            })
            source_index += 1
    return pd.DataFrame(rows)


def test_add_local_ground_height_adds_columns_preserves_columns_and_rows():
    df = _tilted_ground_fixture()
    out = add_local_ground_height(
        df,
        x_bin_size_m=100.0,
        z_bin_size_m=250.0,
        ground_quantile=0.10,
        smooth_bins=3,
        min_points_per_xz_bin=5,
        min_x_bins_per_z=3,
        seed_y_max=180.0,
    )

    assert "ground_Y" in out.columns
    assert "height_agl" in out.columns
    assert list(out.columns[: len(df.columns)]) == list(df.columns)
    assert len(out) == len(df)
    assert list(out["source_index"]) == list(df["source_index"])


def test_height_agl_filter_reduces_rows_and_preserves_metadata_columns():
    df = add_local_ground_height(
        _tilted_ground_fixture(),
        x_bin_size_m=100.0,
        z_bin_size_m=250.0,
        ground_quantile=0.10,
        smooth_bins=3,
        min_points_per_xz_bin=5,
        min_x_bins_per_z=3,
        seed_y_max=180.0,
    )
    out = height_agl_filter(df, min_height_agl_m=50.0)

    assert 0 < len(out) < len(df)
    for col in [
        "source_index", "time_s", "phi", "theta", "dist_mm", "range_m", "encoder",
        "roll_deg", "pitch_deg", "yaw_deg", "beam_id", "X", "Y", "Z", "RSSI",
        "rssi_norm", "ground_Y", "height_agl",
    ]:
        assert col in out.columns


def test_local_ground_filter_retains_ground_columns_and_removes_low_points():
    out = local_ground_filter(
        _tilted_ground_fixture(),
        x_bin_size_m=100.0,
        z_bin_size_m=250.0,
        ground_quantile=0.10,
        smooth_bins=3,
        min_points_per_xz_bin=5,
        min_x_bins_per_z=3,
        seed_y_max=180.0,
        min_height_agl_m=50.0,
    )
    assert {"ground_Y", "height_agl"}.issubset(out.columns)
    assert set(out["class"].unique()) == {"canopy"}


def test_empty_dataframe_gets_ground_columns_without_crashing():
    df = pd.DataFrame(columns=["X", "Y", "Z", "RSSI", "source_index"])
    out = add_local_ground_height(df)
    assert list(out.columns) == ["X", "Y", "Z", "RSSI", "source_index", "ground_Y", "height_agl"]
    assert out.empty


def test_height_agl_filter_missing_column_raises_clear_error():
    with pytest.raises(ValueError, match="height_agl_filter requires column"):
        height_agl_filter(pd.DataFrame({"X": [0.0], "Y": [0.0], "Z": [0.0]}))


def test_zx_line_estimates_tilted_ground_and_positive_canopy_heights():
    out = add_local_ground_height(
        _tilted_ground_fixture(),
        x_bin_size_m=100.0,
        z_bin_size_m=250.0,
        ground_quantile=0.10,
        smooth_bins=3,
        min_points_per_xz_bin=5,
        min_x_bins_per_z=3,
        seed_y_max=180.0,
    )
    ground_h = out.loc[out["class"] == "ground", "height_agl"]
    canopy_h = out.loc[out["class"] == "canopy", "height_agl"]

    assert float(ground_h.abs().median()) < 10.0
    assert float(canopy_h.median()) > 150.0


def test_seed_y_bounds_do_not_directly_discard_tall_canopy_before_agl_filtering():
    out = local_ground_filter(
        _tilted_ground_fixture(),
        x_bin_size_m=100.0,
        z_bin_size_m=250.0,
        ground_quantile=0.10,
        smooth_bins=3,
        min_points_per_xz_bin=5,
        min_x_bins_per_z=3,
        seed_y_min=50.0,
        seed_y_max=180.0,
        min_height_agl_m=150.0,
    )

    assert len(out) > 0
    assert set(out["class"].unique()) == {"canopy"}
    assert (out["Y"] > 180.0).all()


def test_default_config_local_ground_filter_disabled():
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=".", cart_id="CART")
    assert cfg.use_local_ground_filter is False
    assert cfg.local_ground_x_bin_m == 0.10
    assert cfg.local_ground_z_bin_m == 0.25
    assert cfg.local_ground_quantile == 0.10
    assert cfg.local_ground_smooth_bins == 5
    assert cfg.local_ground_min_points_per_xz_bin == 10
    assert cfg.local_ground_min_x_bins_per_z == 3
    assert cfg.local_ground_seed_y_min_m is None
    assert cfg.local_ground_seed_y_max_m is None
    assert cfg.min_height_agl_m == 0.10
