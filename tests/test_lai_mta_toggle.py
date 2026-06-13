from pathlib import Path

import numpy as np

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.lai import compute_lai_trait_from_beam_rows
from lidar_analysis.pipeline_core import trait_summary_row


MTA_COLUMNS = {"lai_mta_deg", "lai_mta_sem_deg", "lai_mta_slope", "lai_mta_n_bins"}


def _cfg(**kwargs):
    return AnalysisConfig(data_dirs=[], calibration_dir=Path("."), cart_id="CART", **kwargs)


def test_summary_row_omits_mta_columns_by_default():
    rec = {"lai_even": 1.0, "lai_uneven": 2.0, "lai_mta_deg": 55.3, "lai_mta_n_bins": 8}

    row = trait_summary_row(rec, _cfg())

    assert not (MTA_COLUMNS & set(row))


def test_summary_row_includes_mta_columns_when_enabled():
    rec = {
        "lai_even": 1.0,
        "lai_uneven": 2.0,
        "lai_mta_deg": 55.3,
        "lai_mta_sem_deg": 1.2,
        "lai_mta_slope": 0.4,
        "lai_mta_n_bins": 8,
    }

    row = trait_summary_row(rec, _cfg(run_mta=True))

    assert MTA_COLUMNS <= set(row)


def test_lai_beam_rows_keyword_array_interface_still_works():
    traits = compute_lai_trait_from_beam_rows(
        distances_m=np.array([0.0, 1.0, 35.0, 2.0], dtype=float),
        theta_rad=np.deg2rad(np.array([180.0, 165.0, 150.0, 120.0], dtype=float)),
        gap_distance_m=30.0,
        distance_column="dist_mm",
    )

    assert "lai_even" in traits
    assert "lai_uneven" in traits
    assert traits["lai_distance_column_used"] == "dist_mm"
    assert traits["lai_mta_n_bins"] == 0
