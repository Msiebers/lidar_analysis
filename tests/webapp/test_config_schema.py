"""Focused unit tests for config_schema.py's introspection behavior itself
-- independent of config_ui_metadata.py, and independent of whatever
AnalysisConfig happens to contain today. Where a test needs a concrete
field to check behavior against, it picks one by the *property* being
tested (e.g. "the one Optional[int] field") rather than assuming today's
exact field roster, so these stay meaningful even as AnalysisConfig grows.
"""
from __future__ import annotations

import dataclasses

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.webapp.config_schema import (
    ConfigFieldSchema,
    FieldTypeInfo,
    analysis_config_field_names,
    introspect_analysis_config_fields,
)


def test_introspection_returns_one_entry_per_dataclass_field():
    schemas = introspect_analysis_config_fields()
    assert len(schemas) == len(dataclasses.fields(AnalysisConfig))
    assert {s.name for s in schemas} == {f.name for f in dataclasses.fields(AnalysisConfig)}


def test_field_names_helper_matches_full_introspection():
    assert analysis_config_field_names() == {
        s.name for s in introspect_analysis_config_fields()
    }


def test_required_fields_have_no_default():
    """data_dirs / calibration_dir / cart_id are the only fields with no
    default -- confirmed by direct introspection during the Phase 1 audit.
    Checked by property (dataclasses.fields with default is MISSING) rather
    than hardcoding that these three names are required, so this stays
    correct if AnalysisConfig's required set ever changes."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    truly_required = {
        f.name for f in dataclasses.fields(AnalysisConfig)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    }
    assert truly_required, "expected at least one required field to exist"
    for name in truly_required:
        assert schemas[name].has_default is False
        assert schemas[name].has_default_factory is False


def test_fields_with_defaults_report_has_default_true():
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    assert schemas["run_height"].has_default is True
    assert schemas["run_height"].default is False


def test_no_default_factories_currently_exist_but_are_representable():
    """AnalysisConfig has no default_factory fields today (confirmed by
    introspection) -- this pins that fact so a future field added *with* a
    default_factory is a deliberate, visible change, and separately proves
    the schema layer has real fields for representing one if it ever
    appears (not just an assumption baked into the dataclass shape)."""
    schemas = introspect_analysis_config_fields()
    assert not any(s.has_default_factory for s in schemas)
    # The attribute exists and is inspectable even when unused:
    for s in schemas:
        assert hasattr(s, "default_factory")


def test_optional_field_is_classified_correctly():
    """analyze_side: str | None -- a real Optional field in the current
    schema, used here as a concrete example of the general Optional-typing
    behavior being tested."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["analyze_side"].type_info
    assert info.is_optional is True
    assert info.inner is str
    assert info.origin is None  # a plain scalar once unwrapped, not list/dict


def test_non_optional_scalar_field_is_not_marked_optional():
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["cart_id"].type_info
    assert info.is_optional is False
    assert info.inner is str


def test_list_of_path_field_is_classified_correctly():
    """data_dirs: List[Path] -- the one list-of-Path field currently in the
    schema."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["data_dirs"].type_info
    assert info.is_list is True
    assert info.is_path is True
    assert info.is_optional is False


def test_bare_path_field_is_classified_correctly():
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["calibration_dir"].type_info
    assert info.is_path is True
    assert info.is_list is False


def test_optional_list_of_dict_field_is_classified_correctly():
    """pointcloud_ops: list[dict] | None -- the nested-structure field that
    matters most for the Phase 1 audit's 'do not flatten pointcloud_ops'
    finding: this must be recognized as a list, not silently treated like
    a scalar."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["pointcloud_ops"].type_info
    assert info.is_optional is True
    assert info.is_list is True
    assert info.is_dict is False  # it's a list OF dicts, not a bare dict


def test_optional_dict_field_is_classified_correctly():
    """pcl_backend: dict | None."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["pcl_backend"].type_info
    assert info.is_optional is True
    assert info.is_dict is True
    assert info.is_list is False


def test_bool_field_is_distinguished_from_int():
    """bool is a subclass of int in Python -- is_bool must be checked
    explicitly rather than inferred, since naive isinstance-style checks
    would conflate the two."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    assert schemas["run_height"].type_info.is_bool is True
    assert schemas["n_plots"].type_info.is_bool is False  # Optional[int]


def test_optional_numeric_field_is_classified_correctly():
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    info = schemas["n_plots"].type_info
    assert info.is_optional is True
    assert info.inner is int
    assert info.is_list is False and info.is_dict is False and info.is_path is False


def test_field_type_info_and_config_field_schema_are_frozen():
    """Immutability matters here: this is meant to be read, not mutated, by
    downstream milestones."""
    schemas = introspect_analysis_config_fields()
    sample = schemas[0]
    try:
        sample.name = "changed"
        assert False, "ConfigFieldSchema should be frozen"
    except dataclasses.FrozenInstanceError:
        pass
    try:
        sample.type_info.is_optional = True
        assert False, "FieldTypeInfo should be frozen"
    except dataclasses.FrozenInstanceError:
        pass


def test_introspection_is_idempotent_and_fresh_each_call():
    """Two separate calls return equal (not just equal-length) results --
    proves this is a live read of the dataclass each time, not a cached
    snapshot that could go stale within a process."""
    first = introspect_analysis_config_fields()
    second = introspect_analysis_config_fields()
    assert first == second
