"""Tests for pointcloud_ops_form.py -- adding, editing and removing
pointcloud_ops entries from browser forms (Web-P1D)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp import form_handling as fh
from lidar_analysis.webapp import pointcloud_ops_form as ops_form
from lidar_analysis.webapp.config_ui_metadata import POINTCLOUD_OP_METADATA, POINTCLOUD_OP_ORDER

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "lidar_analysis" / "example_configs"
REAL_CONFIG_PATHS = (
    REPO_ROOT / "experiment_config.yaml",
    EXAMPLES / "full_experiment_config_template.yaml",
    EXAMPLES / "premerge_pai_biomass.yaml",
    EXAMPLES / "additional_scans_marked_plants_pcl_side_split.yaml",
)


def _new_op_form(op_name: str, **overrides: str) -> dict[str, str]:
    form = {spec.form_key: value for spec, value in ops_form.new_op_prefill(op_name)}
    form.update({f"op.{k}": v for k, v in overrides.items()})
    return form


def _unchanged_op_form(op: dict) -> dict[str, str]:
    form = {}
    for spec in ops_form.editable_specs(op):
        state = ops_form.op_param_state(op, spec)
        form[spec.form_key] = fh.format_form_value(state.value) if state.present else ""
    return form


def _errors(errors) -> dict[str | None, str]:
    return {e.field: e.message for e in errors}


# --- Parameter types: every metadata parameter, typed from the consumers ----

def test_every_metadata_parameter_has_a_type_and_nothing_else_does():
    from_metadata = {
        (op, p.name) for op, meta in POINTCLOUD_OP_METADATA.items() for p in meta.parameters
    }
    assert set(ops_form.PARAM_TYPES) == from_metadata


@pytest.mark.parametrize(
    "op, param, kind, nullable",
    [
        ("sor_filter", "mean_k", fh.ValueKind.INT, False),
        ("sor_filter", "std_ratio", fh.ValueKind.FLOAT, False),
        ("scalar_range_filter", "min", fh.ValueKind.FLOAT, True),
        ("height_range_filter", "max_m", fh.ValueKind.FLOAT, True),
        ("bilateral_scalar_filter", "replace_scalar", fh.ValueKind.BOOL, False),
        ("bilateral_scalar_filter", "max_neighbors", fh.ValueKind.INT, False),
        ("slice_structure_trait", "clump_connectivity", fh.ValueKind.INT, False),
        ("slice_structure_trait", "min_points_per_slice", fh.ValueKind.INT, False),
        ("topology_trait", "include_per_m2", fh.ValueKind.BOOL, False),
        ("voxel_count", "voxel_size_m", fh.ValueKind.FLOAT, True),
    ],
)
def test_parameter_types_follow_the_pipeline_code(op, param, kind, nullable):
    assert ops_form.PARAM_TYPES[(op, param)] == (kind, nullable)


# --- Adding an operation ------------------------------------------------------

def test_new_op_is_prefilled_from_metadata_except_mean_k():
    prefill = {spec.name: value for spec, value in ops_form.new_op_prefill("sor_filter")}
    assert prefill["mean_k"] == ""
    assert prefill["std_ratio"] == "2.0"
    assert prefill["enabled"] == "true"


def test_mean_k_shows_reference_values_instead_of_a_default():
    spec = next(s for s, _ in ops_form.new_op_prefill("sor_filter") if s.name == "mean_k")
    assert spec.note and "12" in spec.note and "3" in spec.note and "5" in spec.note


def test_sor_filter_cannot_be_added_without_mean_k():
    op, errors = ops_form.build_new_op("sor_filter", _new_op_form("sor_filter"))
    assert op is None
    assert set(_errors(errors)) == {"mean_k"}


def test_new_op_writes_every_parameter_explicitly_with_real_types():
    op, errors = ops_form.build_new_op("sor_filter", _new_op_form("sor_filter", mean_k="12"))
    assert errors == ()
    assert op == {"op": "sor_filter", "enabled": True, "mean_k": 12, "std_ratio": 2.0}
    assert type(op["mean_k"]) is int


def test_new_bilateral_op_writes_replace_scalar_false_explicitly():
    """The code fallback for an absent replace_scalar is True; the metadata
    and template use False. Leaving it out would silently flip it."""
    op, errors = ops_form.build_new_op("bilateral_scalar_filter", _new_op_form("bilateral_scalar_filter"))
    assert errors == ()
    assert op["replace_scalar"] is False
    expected = {"op", "enabled"} | {p.name for p in POINTCLOUD_OP_METADATA["bilateral_scalar_filter"].parameters}
    assert set(op) == expected


def test_new_op_writes_clump_connectivity_as_an_int():
    op, _ = ops_form.build_new_op("slice_structure_trait", _new_op_form("slice_structure_trait"))
    assert op["clump_connectivity"] == 8 and type(op["clump_connectivity"]) is int


def test_clump_connectivity_must_be_4_or_8():
    op, errors = ops_form.build_new_op("slice_structure_trait", _new_op_form("slice_structure_trait", clump_connectivity="6"))
    assert op is None
    assert set(_errors(errors)) == {"clump_connectivity"}


def test_nullable_parameter_left_blank_is_written_as_null():
    op, errors = ops_form.build_new_op("scalar_range_filter", _new_op_form("scalar_range_filter"))
    assert errors == ()
    assert "max" in op and op["max"] is None


def test_required_parameter_left_blank_is_an_error():
    op, errors = ops_form.build_new_op("canopy_volume_2p5d", _new_op_form("canopy_volume_2p5d", cell_size_m=""))
    assert op is None
    assert set(_errors(errors)) == {"cell_size_m"}


def test_unknown_operation_cannot_be_added():
    with pytest.raises(KeyError):
        ops_form.build_new_op("not_an_op", {})


# --- Canonical-position insertion ------------------------------------------------

def _names(ops):
    return [op.get("op", op.get("name")) if isinstance(op, dict) else op for op in ops]


def test_insert_into_an_empty_pipeline():
    assert ops_form.insert_position([], "sor_filter") == 0


def test_insert_follows_canonical_order_among_recognized_ops():
    document = doc.load_document(EXAMPLES / "full_experiment_config_template.yaml")
    ops = document.analysis["pointcloud_ops"]
    assert _names(ops) == list(POINTCLOUD_OP_ORDER)
    # A second height_range_filter goes after the existing one, before voxel_count.
    assert ops_form.insert_position(ops, "height_range_filter") == 4


def test_insert_keeps_unknown_ops_where_they_are():
    ops = [{"op": "custom_thing"}, {"op": "sor_filter"}]
    assert ops_form.insert_position(ops, "scalar_range_filter") == 1
    assert ops_form.insert_position(ops, "canopy_volume_2p5d") == 2


def test_insert_never_reorders_an_out_of_order_pipeline():
    ops = [{"op": "canopy_volume_2p5d"}, {"op": "scalar_range_filter"}]
    before = copy.deepcopy(ops)
    assert ops_form.insert_position(ops, "sor_filter") == 0
    assert ops == before


def test_add_op_to_document_inserts_and_creates_the_list_if_needed():
    document = doc.new_document("X")
    document.analysis.pop("pointcloud_ops", None)
    op, _ = ops_form.build_new_op("voxel_count", _new_op_form("voxel_count"))
    index = ops_form.add_op(document, op)
    assert index == 0
    assert document.analysis["pointcloud_ops"] == [op]


# --- Editing an existing operation ----------------------------------------------------

def _all_real_ops():
    for path in REAL_CONFIG_PATHS:
        document = doc.load_document(path)
        for index, op in enumerate(document.analysis.get("pointcloud_ops") or []):
            if ops_form.is_recognized(op):
                yield pytest.param(path, index, id=f"{path.name}-{index}-{op.get('op')}")


@pytest.mark.parametrize("path, index", list(_all_real_ops()))
def test_unchanged_op_submission_changes_nothing(path, index):
    document = doc.load_document(path)
    before = copy.deepcopy(document.analysis["pointcloud_ops"])
    op = document.analysis["pointcloud_ops"][index]
    new_op, errors = ops_form.apply_op_form(op, _unchanged_op_form(op))
    assert errors == ()
    assert new_op == op
    assert document.analysis["pointcloud_ops"] == before


def test_editing_a_parameter_preserves_every_other_key():
    op = {"op": "bilateral_scalar_filter", "field": "rssi_norm", "sigma_s": 0.02, "radius": 0.1}
    form = _unchanged_op_form(op)
    form["op.radius"] = "0.2"
    new_op, errors = ops_form.apply_op_form(op, form)
    assert errors == ()
    assert new_op == {"op": "bilateral_scalar_filter", "field": "rssi_norm", "sigma_s": 0.02, "radius": 0.2}
    assert op["radius"] == 0.1  # the original dict is not mutated


def test_absent_parameter_left_blank_stays_absent():
    op = {"op": "topology_trait", "min_persistence": 0.35}
    new_op, errors = ops_form.apply_op_form(op, _unchanged_op_form(op))
    assert errors == ()
    assert "include_per_m2" not in new_op


def test_clearing_a_required_parameter_is_an_error():
    op = {"op": "sor_filter", "mean_k": 12, "std_ratio": 2.0}
    form = dict(_unchanged_op_form(op), **{"op.mean_k": ""})
    new_op, errors = ops_form.apply_op_form(op, form)
    assert new_op is None
    assert set(_errors(errors)) == {"mean_k"}


def test_enabled_is_a_real_bool_and_absent_enabled_stays_absent():
    op = {"op": "sor_filter", "mean_k": 3, "std_ratio": 2.0}
    new_op, _ = ops_form.apply_op_form(op, _unchanged_op_form(op))
    assert "enabled" not in new_op
    new_op, _ = ops_form.apply_op_form(op, dict(_unchanged_op_form(op), **{"op.enabled": "false"}))
    assert new_op["enabled"] is False


def test_the_name_key_style_of_an_imported_op_is_preserved():
    op = {"name": "voxel_count", "voxel_size_m": 0.05}
    new_op, _ = ops_form.apply_op_form(op, dict(_unchanged_op_form(op), **{"op.voxel_size_m": "0.1"}))
    assert new_op == {"name": "voxel_count", "voxel_size_m": 0.1}


def test_a_shadowed_parameter_is_not_editable():
    """_sor_filter reads stddev_mul_thresh before std_ratio."""
    op = {"op": "sor_filter", "mean_k": 3, "std_ratio": 2.0, "stddev_mul_thresh": 1.0}
    assert "std_ratio" not in {s.name for s in ops_form.editable_specs(op)}
    form = dict(_unchanged_op_form(op), **{"op.std_ratio": "9.0"})
    new_op, errors = ops_form.apply_op_form(op, form)
    assert errors == ()
    assert new_op["std_ratio"] == 2.0
    assert "stddev_mul_thresh" in ops_form.shadowing_note(op, "std_ratio")


def test_unrecognized_ops_have_no_editable_parameters():
    op = {"op": "custom_thing", "x": 1}
    assert ops_form.is_recognized(op) is False
    assert ops_form.editable_specs(op) == ()


def test_extra_keys_are_reported_for_display():
    op = {"op": "sor_filter", "mean_k": 12, "stddev_mul": 1.0}
    assert ops_form.extra_keys(op) == {"stddev_mul": 1.0}


def test_voxel_count_carries_a_position_note():
    assert "after all other operations" in ops_form.position_note("voxel_count")
    assert ops_form.position_note("sor_filter") is None
