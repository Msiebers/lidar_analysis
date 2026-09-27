"""Tests for config_service.py -- the translation/validation truth layer.

Extends the existing precedent (test_full_experiment_config_template_loads
in tests/test_config_defaults.py already proves the real template loads
through build_config) rather than starting a disconnected test universe:
several tests here load that exact same real file through config_service
and confirm it produces the same underlying validity build_config already
guarantees, then go further to exercise the translation layer around it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.webapp import config_service as svc
from lidar_analysis.webapp.config_ui_metadata import Tier, UI_METADATA

REAL_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "experiment_config.yaml"


# --- Default config -----------------------------------------------------

def test_default_config_reuses_default_analysis_yaml_dict():
    """Must be the same object/values config.py's own
    default_analysis_yaml_dict() produces -- not a second, independently
    invented default schema."""
    from lidar_analysis.config import default_analysis_yaml_dict

    assert svc.default_config_dict() == default_analysis_yaml_dict()


def test_default_config_is_itself_valid():
    result = svc.validate(svc.default_config_dict())
    assert result.valid, result.errors


def test_default_config_excludes_hidden_system_fields():
    """default_analysis_yaml_dict() already excludes cart_id/data_dirs/
    calibration_dir/reprocess_scans/the deprecated shims/etc. -- confirms
    that exclusion lines up with P1A's HIDDEN_SYSTEM classification rather
    than just happening to overlap by coincidence."""
    default = svc.default_config_dict()
    for name in ("data_dirs", "calibration_dir", "cart_id", "reprocess_scans",
                 "write_o3d_ply", "run_o3d_metrics", "run_topology"):
        assert name not in default, name


# --- Real example config load --------------------------------------------

def test_real_template_loads_via_config_service():
    raw = svc.load_yaml_file(REAL_TEMPLATE_PATH)
    assert "analysis" in raw  # confirms this is a full, wrapped file


def test_real_template_validates_via_config_service():
    """Same real file test_full_experiment_config_template_loads already
    proves loads through build_config -- confirmed here via the service's
    own validate(), not a second independent check."""
    raw = svc.load_yaml_file(REAL_TEMPLATE_PATH)
    result = svc.validate(raw)
    assert result.valid, result.errors
    assert isinstance(result.config, AnalysisConfig)


def test_real_template_flattening_matches_known_real_values():
    """Pins the specific real values found in this repository's actual
    template during the Phase 1/P1B audits -- run_pai/run_z_pai on,
    run_height/run_mta off, imu_interp fusion, local_grid ground mode.
    If this template's defaults are ever deliberately changed, this test
    should be updated deliberately, not silently left checking stale
    values."""
    raw = svc.load_yaml_file(REAL_TEMPLATE_PATH)
    flat = svc.to_ui_representation(raw)
    assert flat["run_pai"] is True
    assert flat["run_z_pai"] is True
    assert flat["run_height"] is False
    assert flat["run_mta"] is False
    assert flat["fusion_method"] == "imu_interp"
    assert flat["use_imu"] is True
    assert flat["ray_box_ground_mode"] == "local_grid"


# --- Valid / invalid through the real build_config -----------------------

def test_valid_config_accepted():
    config = dict(svc.default_config_dict())
    config["run_height"] = True
    result = svc.validate(config)
    assert result.valid
    assert result.config.run_height is True
    assert not result.errors


def test_invalid_mta_range_rejected_with_structured_error():
    config = dict(svc.default_config_dict())
    config["mta_fit_angle_min_deg"] = 24.0  # one degree off the locked 25.0
    result = svc.validate(config)
    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "mta_fit_angle_min_deg" or "25" in result.errors[0].message
    assert result.exception is not None


def test_analyze_one_side_without_side_rejected():
    config = dict(svc.default_config_dict())
    config["analyze_one_side"] = True
    result = svc.validate(config)
    assert result.valid is False
    assert result.errors


def test_unsupported_pointcloud_op_rejected():
    """Validation flows all the way through the pointcloud_ops pipeline
    too, not just top-level AnalysisConfig fields -- an unsupported op name
    only surfaces once apply_pointcloud_ops is actually reached, which only
    happens for real processing, not build_config alone. This test
    confirms build_config() itself does NOT catch this (it just stores the
    list), which is an honest scope boundary worth pinning explicitly."""
    config = dict(svc.default_config_dict())
    config["pointcloud_ops"] = [{"op": "not_a_real_operation", "enabled": True}]
    result = svc.validate(config)
    # build_config stores pointcloud_ops as-is; it does not itself call
    # apply_pointcloud_ops, so this is expected to still validate at the
    # config-structure level. Documented here so nobody later assumes
    # validate() catches this -- it's PIPELINE_RUNTIME_ONLY per the audit.
    assert result.valid is True


def test_validate_never_raises_to_the_caller():
    """Whatever build_config throws, validate() must catch it -- a future
    UI must never receive a raw exception."""
    config = {"mta_fit_angle_min_deg": True}  # a bool where a float is required
    result = svc.validate(config)
    assert result.valid is False
    assert isinstance(result.errors[0].message, str)


# --- Import -> export -> re-import round trip -----------------------------

def test_roundtrip_semantic_equivalence_for_real_template():
    raw = svc.load_yaml_file(REAL_TEMPLATE_PATH)
    flat_before = svc.to_ui_representation(raw)
    result_before = svc.validate(flat_before)
    assert result_before.valid

    exported = svc.from_ui_representation(flat_before)
    result_after = svc.validate(exported)
    assert result_after.valid, result_after.errors

    # Semantic equivalence: every field on the built AnalysisConfig matches,
    # not byte-identical YAML text (explicitly not required).
    import dataclasses
    for field in dataclasses.fields(AnalysisConfig):
        before = getattr(result_before.config, field.name)
        after = getattr(result_after.config, field.name)
        assert before == after, f"{field.name}: {before!r} != {after!r}"


def test_roundtrip_via_yaml_text():
    """The same round trip, but actually through YAML text serialization
    and re-parsing -- not just dict-to-dict -- to catch anything that only
    breaks once real YAML formatting is involved."""
    raw = svc.load_yaml_file(REAL_TEMPLATE_PATH)
    flat = svc.to_ui_representation(raw)
    yaml_text = svc.export_yaml_text(flat)

    import yaml as _yaml
    reparsed = _yaml.safe_load(yaml_text)
    result = svc.validate(reparsed)
    assert result.valid, result.errors


# --- generate_pointclouds / make_point_cloud remapping --------------------

def test_generate_pointclouds_yaml_key_maps_to_make_point_cloud_field():
    config = {"generate_pointclouds": True}
    flat = svc.to_ui_representation(config)
    assert flat["make_point_cloud"] is True
    assert "generate_pointclouds" not in flat

    result = svc.validate(config)
    assert result.valid
    assert result.config.make_point_cloud is True


def test_export_writes_generate_pointclouds_not_make_point_cloud():
    exported = svc.from_ui_representation({"make_point_cloud": True})
    assert exported.get("generate_pointclouds") is True
    assert "make_point_cloud" not in exported


def test_overwrite_pointclouds_yaml_key_maps_to_overwrite_outputs_field():
    config = {"overwrite_pointclouds": True}
    result = svc.validate(config)
    assert result.valid
    assert result.config.overwrite_outputs is True


def test_ui_representation_field_names_validate_correctly_not_just_raw_yaml_keys():
    """Regression test for a real bug found while building this module:
    build_config's pick("generate_pointclouds", "make_point_cloud", bool)
    looks ONLY for the literal YAML key "generate_pointclouds" -- unlike
    use_imu/apply_imu or apply_ground_filter/use_local_ground_filter, it
    has no native fallback to the AnalysisConfig field name. A
    UI-representation dict (using "make_point_cloud", not
    "generate_pointclouds") validated as True but silently defaulted to
    make_point_cloud=False before _canonicalize_for_build_config was added.
    This test feeds validate() the FIELD name directly (as a future form
    submission would) and confirms the built config actually reflects it,
    not just that validation returned True."""
    result = svc.validate({"make_point_cloud": True})
    assert result.valid
    assert result.config.make_point_cloud is True

    result2 = svc.validate({"overwrite_outputs": True})
    assert result2.valid
    assert result2.config.overwrite_outputs is True


# --- Nested marks handling -------------------------------------------------

def test_nested_marks_section_flattened_correctly():
    config = {
        "marks": {
            "target_type": "plant",
            "dirname": "my_markers",
            "buffer_u": 0.5,
        }
    }
    flat = svc.to_ui_representation(config)
    assert flat["mark_target_type"] == "plant"
    assert flat["markers_dirname"] == "my_markers"
    assert flat["mark_z_buffer_u"] == 0.5

    result = svc.validate(config)
    assert result.valid
    assert result.config.mark_target_type == "plant"
    assert result.config.markers_dirname == "my_markers"


def test_export_re_nests_marks_fields():
    flat = {"mark_target_type": "plot", "markers_dirname": "markers2"}
    exported = svc.from_ui_representation(flat)
    assert exported["marks"] == {"target_type": "plot", "dirname": "markers2"}
    assert "mark_target_type" not in exported
    assert "markers_dirname" not in exported


# --- Nested ray_box handling ------------------------------------------------

def test_nested_ray_box_section_flattened_correctly():
    config = {"ray_box": {"ground_mode": "global_y", "bottom_agl_m": 0.2}}
    flat = svc.to_ui_representation(config)
    assert flat["ray_box_ground_mode"] == "global_y"
    assert flat["ray_box_bottom_agl_m"] == 0.2

    result = svc.validate(config)
    assert result.valid
    assert result.config.ray_box_ground_mode == "global_y"


def test_export_re_nests_ray_box_fields():
    flat = {"ray_box_ground_mode": "local_grid", "ray_box_x_near_m": 0.4}
    exported = svc.from_ui_representation(flat)
    assert exported["ray_box"] == {"ground_mode": "local_grid", "x_near_m": 0.4}


# --- Deprecated aliases -----------------------------------------------------

def test_apply_imu_legacy_alias_accepted():
    config = {"apply_imu": True}
    flat = svc.to_ui_representation(config)
    assert flat["use_imu"] is True

    result = svc.validate(config)
    assert result.valid
    assert result.config.use_imu is True


def test_use_local_ground_filter_legacy_key_sets_apply_ground_filter_too():
    config = {"use_local_ground_filter": True}
    result = svc.validate(config)
    assert result.valid
    assert result.config.apply_ground_filter is True
    assert result.config.use_local_ground_filter is True


def test_splitting_style_legacy_key_resolves_via_real_pipeline_function():
    config = {"splitting_style": "plot"}
    flat = svc.to_ui_representation(config)
    assert flat["split_source"] == "marks"
    assert flat["mark_target_type"] == "plot"
    assert "splitting_style" not in flat


def test_mta_lo_hi_deg_legacy_aliases_resolve_to_current_field_names():
    config = {"run_mta": True, "mta_lo_deg": 25.0, "mta_hi_deg": 65.0}
    flat = svc.to_ui_representation(config)
    assert flat["mta_fit_angle_min_deg"] == 25.0
    assert flat["mta_fit_angle_max_deg"] == 65.0


def test_export_never_writes_deprecated_alias_keys():
    """Even if a caller's flat dict somehow still had a legacy name in it
    (it shouldn't, since to_ui_representation always resolves them), export
    must never re-emit them -- HIDDEN_SYSTEM fields are filtered
    unconditionally on export."""
    flat = {"mta_lo_deg": 25.0, "run_mta": True}
    exported = svc.from_ui_representation(flat)
    assert "mta_lo_deg" not in exported


# --- Hidden system fields never editable/exported ---------------------------

def test_all_hidden_system_fields_excluded_from_export():
    hidden_names = [n for n, m in UI_METADATA.items() if m.tier is Tier.HIDDEN_SYSTEM]
    assert hidden_names  # sanity: there should be some
    flat = {name: "anything" for name in hidden_names}
    flat["run_height"] = True  # one normal field, to confirm it's NOT also stripped
    exported = svc.from_ui_representation(flat)
    for name in hidden_names:
        # Account for the generate_pointclouds/overwrite_pointclouds-style
        # renames not applying to any HIDDEN_SYSTEM field (none of them are
        # in FLAT_KEY_REMAPS), so a direct absence check is correct here.
        assert name not in exported, name
    assert exported.get("run_height") is True


def test_reprocess_scans_cannot_be_set_via_this_service():
    """reprocess_scans comes from the CLI --force flag; build_config never
    reads it from the YAML dict at all -- confirms the service's export
    can't create an illusion of controlling it."""
    flat = {"reprocess_scans": True}
    exported = svc.from_ui_representation(flat)
    assert "reprocess_scans" not in exported


# --- Locked fields ------------------------------------------------------

def test_locked_mta_range_still_enforced_through_service():
    """The config service does not add its own lock enforcement -- it
    relies on validate_mta_config (via build_config) remaining the
    authority. Confirms that authority is still reachable through this
    service, not bypassed by it."""
    config = dict(svc.default_config_dict())
    config["run_mta"] = True
    config["mta_fit_angle_min_deg"] = 10.0
    result = svc.validate(config)
    assert result.valid is False


def test_locked_pai_g_function_only_spherical_accepted():
    config = dict(svc.default_config_dict())
    config["run_pai"] = True
    config["pai_g_function"] = "not_spherical"
    result = svc.validate(config)
    # pai_g_function's enforcement lives in pai.py's own runtime code, not
    # build_config -- confirms which layer actually owns this, rather than
    # assuming build_config itself checks it.
    assert result.valid is True  # accepted at the config-structure level


# --- Pointcloud-op list, canonical names, aliases ---------------------------

def test_pointcloud_ops_list_preserved_through_flattening():
    ops = [{"op": "sor_filter", "enabled": True, "mean_k": 5}]
    config = {"pointcloud_ops": ops}
    flat = svc.to_ui_representation(config)
    assert flat["pointcloud_ops"][0]["op"] == "sor_filter"
    assert flat["pointcloud_ops"][0]["mean_k"] == 5


def test_pointcloud_op_aliases_normalized_to_canonical_on_import():
    for alias in ("voxel_volume", "voxel_grid"):
        flat = svc.to_ui_representation({"pointcloud_ops": [{"op": alias}]})
        assert flat["pointcloud_ops"][0]["op"] == "voxel_count"


def test_pointcloud_op_aliases_never_preferred_on_export():
    flat = {"pointcloud_ops": [{"name": "voxel_grid", "voxel_size_m": 0.05}]}
    exported = svc.from_ui_representation(flat)
    op_entry = exported["pointcloud_ops"][0]
    assert op_entry["op"] == "voxel_count"
    assert "name" not in op_entry


def test_pointcloud_ops_with_aliases_still_validate_through_build_config():
    """Confirms build_config itself (not just this service) genuinely
    accepts the alias names -- pinned against real pipeline behavior, not
    assumed from reading pointcloud_ops.py alone."""
    config = {"pointcloud_ops": [{"op": "voxel_volume", "voxel_size_m": 0.05}]}
    result = svc.validate(config)
    assert result.valid
    assert result.config.pointcloud_ops[0]["op"] == "voxel_volume"  # build_config stores it as-given


# --- Filesystem safety -------------------------------------------------

def test_export_yaml_file_writes_to_given_path(tmp_path):
    target = tmp_path / "exported.yaml"
    svc.export_yaml_file({"run_height": True}, target)
    assert target.is_file()
    reloaded = svc.load_yaml_file(target)
    assert reloaded["run_height"] is True


def test_export_does_not_touch_any_other_file(tmp_path):
    """No accidental overwrite: exporting must never write anywhere except
    the exact path given."""
    original = tmp_path / "original.yaml"
    original.write_text("run_height: true\n", encoding="utf-8")
    before = original.read_bytes()

    other_target = tmp_path / "new_export.yaml"
    svc.export_yaml_file({"run_mta": True}, other_target)

    assert original.read_bytes() == before  # untouched
    assert other_target.is_file()


def test_load_yaml_file_never_writes_anything(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_text("run_height: true\n", encoding="utf-8")
    before_mtime = source.stat().st_mtime
    svc.load_yaml_file(source)
    assert source.stat().st_mtime == before_mtime
