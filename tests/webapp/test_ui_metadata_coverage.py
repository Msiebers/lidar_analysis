"""Schema-drift protection: the central guarantee of Web-P1A.

If a field is added to, removed from, or renamed in AnalysisConfig, these
tests fail immediately -- forcing a deliberate UI_METADATA update rather
than letting the web app silently drift out of sync with the real pipeline
configuration, the way this project has already been bitten twice before
(the result-identity mismatch and the genotype_id character-restriction
question, both from earlier milestones).
"""
from __future__ import annotations

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.webapp.config_schema import (
    analysis_config_field_names,
    introspect_analysis_config_fields,
)
from lidar_analysis.webapp.config_ui_metadata import (
    POINTCLOUD_OP_METADATA,
    POINTCLOUD_OP_ORDER,
    UI_METADATA,
    Tier,
)

# The authoritative supported-operation set lives in pointcloud_ops.py as a
# private (leading-underscore) module constant. Reaching into it directly
# here (test code, not shipped webapp code) gives this test real drift
# protection against that list changing, without the webapp package itself
# importing a private pipeline symbol.
from lidar_analysis import pointcloud_ops as _pointcloud_ops_module


def test_every_analysis_config_field_has_metadata():
    """The central P1A guarantee: set(AnalysisConfig fields) ==
    set(fields explicitly represented in UI_METADATA). No separate
    'explicitly unmapped' escape hatch -- every field, including every
    HIDDEN_SYSTEM one, gets a real, reviewed metadata entry."""
    real_fields = analysis_config_field_names()
    mapped_fields = set(UI_METADATA.keys())
    missing = real_fields - mapped_fields
    assert not missing, (
        f"AnalysisConfig field(s) added with no UI metadata: {sorted(missing)}. "
        "Add an entry to UI_METADATA in config_ui_metadata.py, classifying "
        "its tier deliberately -- do not default to BASIC."
    )


def test_no_stale_metadata_for_removed_fields():
    """The reverse direction: UI_METADATA must never describe a field that
    no longer exists on AnalysisConfig -- stale metadata is exactly the
    kind of silent-drift risk this whole layer exists to prevent."""
    real_fields = analysis_config_field_names()
    mapped_fields = set(UI_METADATA.keys())
    stale = mapped_fields - real_fields
    assert not stale, (
        f"UI_METADATA describes field(s) no longer on AnalysisConfig: {sorted(stale)}. "
        "Remove the stale entry (or confirm the field was intentionally renamed "
        "and update UI_METADATA to the new name)."
    )


def test_metadata_field_count_matches_live_schema():
    """Belt-and-suspenders on the two tests above: the counts themselves
    must match. Deliberately does NOT hardcode 110 -- that number is
    reported in the handoff as a fact about today's schema, not encoded
    here as a magic constant that would itself need manual bumping."""
    assert len(UI_METADATA) == len(analysis_config_field_names())


def test_metadata_name_field_matches_its_own_dict_key():
    """Catches a copy-paste error: an entry registered under one key but
    whose own .name attribute says something else."""
    for key, entry in UI_METADATA.items():
        assert entry.name == key, f"UI_METADATA[{key!r}].name is {entry.name!r}"


# --- Known, specific hidden/locked invariants from the Phase 1 audit -------

def test_reprocess_scans_is_hidden_system():
    entry = UI_METADATA["reprocess_scans"]
    assert entry.tier is Tier.HIDDEN_SYSTEM
    assert entry.read_only is True


def test_pai_run_conditional_profile_is_hidden_system():
    entry = UI_METADATA["pai_run_conditional_profile"]
    assert entry.tier is Tier.HIDDEN_SYSTEM
    assert entry.read_only is True


def test_data_dirs_calibration_dir_cart_id_are_hidden_system():
    """Not part of experiment_config.yaml at all -- build_config receives
    these as separate arguments, never read from the YAML dict."""
    for name in ("data_dirs", "calibration_dir", "cart_id"):
        assert UI_METADATA[name].tier is Tier.HIDDEN_SYSTEM, name


def test_deprecated_shims_are_hidden_system():
    """config.py's own comment: 'Deprecated compatibility shims... must
    stay false and should not appear in new experiment configs.'"""
    for name in ("write_o3d_ply", "run_o3d_metrics", "run_topology"):
        assert UI_METADATA[name].tier is Tier.HIDDEN_SYSTEM, name


def test_legacy_mta_alias_fields_are_hidden_system():
    """mta_lo_deg/mta_hi_deg/mta_n_bins are real AnalysisConfig fields (so
    they must be accounted for, per the P1A guarantee) but are deprecated
    aliases map_deprecated_analysis_keys() only reads as legacy input --
    never something this tool should present as an ordinary editable
    control alongside the current mta_fit_angle_min/max_deg fields."""
    for name in ("mta_lo_deg", "mta_hi_deg", "mta_n_bins"):
        assert UI_METADATA[name].tier is Tier.HIDDEN_SYSTEM, name


def test_mta_fit_angle_fields_are_locked_to_25_and_65():
    """validate_mta_config raises ValueError unless these are exactly
    25.0/65.0 -- 'bounded_lang_v1 requires the fixed 25-65 degree fitting
    interval.' Metadata must reflect the actual enforced values, not just
    claim the field is locked."""
    lo = UI_METADATA["mta_fit_angle_min_deg"]
    hi = UI_METADATA["mta_fit_angle_max_deg"]
    assert lo.tier is Tier.LOCKED and lo.locked_value == 25.0
    assert hi.tier is Tier.LOCKED and hi.locked_value == 65.0
    assert lo.read_only is True and hi.read_only is True


def test_locked_fields_are_consistent_with_validate_mta_config():
    """Cross-check against the real validator's actual behavior (not just
    trusting the metadata's own claim) -- constructs a config with the
    locked values and confirms validate_mta_config accepts them, then
    confirms it rejects a value one degree off in each direction. This
    doesn't duplicate the validator's logic, just proves the metadata's
    locked_value actually is what the pipeline enforces today."""
    from lidar_analysis.config import validate_mta_config

    base_kwargs = dict(data_dirs=[], calibration_dir=__import__("pathlib").Path("."), cart_id="CART")
    ok = AnalysisConfig(**base_kwargs, mta_fit_angle_min_deg=25.0, mta_fit_angle_max_deg=65.0)
    validate_mta_config(ok)  # must not raise

    import pytest as _pytest
    with _pytest.raises(ValueError):
        validate_mta_config(AnalysisConfig(**base_kwargs, mta_fit_angle_min_deg=24.0, mta_fit_angle_max_deg=65.0))
    with _pytest.raises(ValueError):
        validate_mta_config(AnalysisConfig(**base_kwargs, mta_fit_angle_min_deg=25.0, mta_fit_angle_max_deg=64.0))


def test_g_function_fields_locked_to_spherical():
    """Only 'spherical' is currently implemented for either PAI or FAD's
    projection-coefficient function (per the V3B audit's earlier finding,
    confirmed again during the Phase 1 audit)."""
    for name in ("pai_g_function", "fad_g_function"):
        entry = UI_METADATA[name]
        assert entry.tier is Tier.LOCKED, name
        assert entry.locked_value == "spherical", name


# --- Point-cloud operation coverage -----------------------------------------

def test_pointcloud_ops_metadata_matches_supported_ops():
    """Cross-checked against pointcloud_ops.py's own authoritative
    _SUPPORTED_OPS set, not just re-asserting what config_ui_metadata.py
    itself claims. voxel_volume/voxel_grid are accepted aliases for the
    same operation voxel_count represents here -- one metadata entry
    covers all three names."""
    supported = set(_pointcloud_ops_module._SUPPORTED_OPS)
    aliased = {"voxel_volume", "voxel_grid", "voxel_count"}
    canonical_supported = (supported - aliased) | {"voxel_count"}
    assert set(POINTCLOUD_OP_METADATA.keys()) == canonical_supported


def test_pointcloud_op_order_matches_metadata_keys():
    assert set(POINTCLOUD_OP_ORDER) == set(POINTCLOUD_OP_METADATA.keys())
    assert len(POINTCLOUD_OP_ORDER) == len(set(POINTCLOUD_OP_ORDER)), "duplicate op in order list"


def test_every_pointcloud_op_has_a_label_and_description():
    for op_name, meta in POINTCLOUD_OP_METADATA.items():
        assert meta.label.strip(), op_name
        assert meta.description.strip(), op_name
        assert meta.op_name == op_name


def test_every_pointcloud_op_parameter_has_a_label_and_description():
    for op_name, meta in POINTCLOUD_OP_METADATA.items():
        assert meta.parameters, f"{op_name} has no parameters registered"
        for param in meta.parameters:
            assert param.label.strip(), f"{op_name}.{param.name}"
            assert param.description.strip(), f"{op_name}.{param.name}"


# --- Every field has real presentation content, not a placeholder ----------

def test_every_field_has_a_nonempty_label_and_description():
    for name, entry in UI_METADATA.items():
        assert entry.label.strip(), name
        assert entry.description.strip(), name
        assert len(entry.description) > 10, f"{name}: suspiciously short description"


def test_select_fields_have_choices():
    from lidar_analysis.webapp.config_ui_metadata import ControlType

    for name, entry in UI_METADATA.items():
        if entry.control_type is ControlType.SELECT:
            assert entry.choices, f"{name} is a SELECT control with no choices"
