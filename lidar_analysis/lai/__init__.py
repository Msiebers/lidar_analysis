from .lai import (
    CAPPED_ZENITH_BREAKS_RAD,
    FULL_ZENITH_BREAKS_RAD,
    LAI2200_PUBLISHED_WEIGHTS,
    LAI2200_PUBLISHED_DIFN_WEIGHTS,
    SCHEMES,
    compute_lai_all_schemes,
    compute_legacy_lai_pair,
    compute_lai_trait_from_beam_rows,
    compute_lai_trait_from_lidar_data,
    compute_lai_trait_from_target,
)

# Backward-compatible aliases for old imports.
# The current capped LAI implementation uses the same capped ring breaks
# for both lai_even and lai_uneven; the difference is the weighting scheme.
EVEN_ZENITH_BREAKS_RAD = CAPPED_ZENITH_BREAKS_RAD
UNEVEN_ZENITH_BREAKS_RAD = CAPPED_ZENITH_BREAKS_RAD

__all__ = [
    "CAPPED_ZENITH_BREAKS_RAD",
    "FULL_ZENITH_BREAKS_RAD",
    "EVEN_ZENITH_BREAKS_RAD",
    "UNEVEN_ZENITH_BREAKS_RAD",
    "LAI2200_PUBLISHED_WEIGHTS",
    "LAI2200_PUBLISHED_DIFN_WEIGHTS",
    "SCHEMES",
    "compute_lai_all_schemes",
    "compute_legacy_lai_pair",
    "compute_lai_trait_from_beam_rows",
    "compute_lai_trait_from_lidar_data",
    "compute_lai_trait_from_target",
]