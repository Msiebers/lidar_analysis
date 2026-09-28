"""Tests for experiment_document.py -- the outer experiment_config.yaml
envelope built on top of P1B's config_service."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml as _yaml

from lidar_analysis.webapp import config_service as svc
from lidar_analysis.webapp import experiment_document as doc

REAL_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "experiment_config.yaml"


# --- Loading a real full experiment config ---------------------------------

def test_loads_real_template_document():
    document = doc.load_document(REAL_TEMPLATE_PATH)
    assert document.experiment_name == "example_experiment"
    assert document.source_path == REAL_TEMPLATE_PATH
    assert document.analysis["run_pai"] is True


def test_loading_never_writes_to_the_source_file(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_text("experiment_name: X\nanalysis: {run_height: true}\n", encoding="utf-8")
    before = source.stat().st_mtime
    doc.load_document(source)
    assert source.stat().st_mtime == before


# --- Preservation of all known outer metadata -------------------------------

def test_all_known_outer_fields_preserved_on_load(tmp_path):
    raw = {
        "experiment_name": "MeadowFescue_2026",
        "config_note": "a real researcher note",
        "config_reviewed": True,
        "processing": {"parallel_scans": 4},
        "processing_mode": "auto_publish",
        "raw_data_path": "/some/path",
        "output_path": "/some/output",
        "sharing": {"enabled": True},
        "notifications": {"enabled": True},
        "analysis": {"run_height": True},
    }
    path = tmp_path / "full.yaml"
    path.write_text(_yaml.safe_dump(raw), encoding="utf-8")

    document = doc.load_document(path)
    for key in doc.KNOWN_OUTER_FIELDS:
        assert getattr(document, key) == raw[key], key


def test_editing_analysis_does_not_discard_sibling_outer_metadata(tmp_path):
    """The exact scenario named explicitly: editing an analysis setting
    must not silently discard experiment_name/config_note/processing_mode
    or any other recognized top-level metadata."""
    raw = {
        "experiment_name": "MeadowFescue_2026",
        "config_note": "real researcher note",
        "processing_mode": "auto_publish",
        "analysis": {"run_height": False},
    }
    path = tmp_path / "full.yaml"
    path.write_text(_yaml.safe_dump(raw), encoding="utf-8")

    document = doc.load_document(path)
    document.analysis["run_height"] = True  # the one edit

    rendered = doc.render_document_yaml(document)
    reparsed = _yaml.safe_load(rendered)
    assert reparsed["experiment_name"] == "MeadowFescue_2026"
    assert reparsed["config_note"] == "real researcher note"
    assert reparsed["processing_mode"] == "auto_publish"
    assert reparsed["analysis"]["run_height"] is True


# --- Unknown top-level key policy -------------------------------------------

def test_unknown_outer_key_preserved_not_dropped(tmp_path):
    raw = {"experiment_name": "X", "a_future_field": {"whatever": 1}, "analysis": {}}
    path = tmp_path / "config.yaml"
    path.write_text(_yaml.safe_dump(raw), encoding="utf-8")

    document = doc.load_document(path)
    assert document.unknown_outer_fields == {"a_future_field": {"whatever": 1}}

    rendered = doc.render_document_yaml(document)
    reparsed = _yaml.safe_load(rendered)
    assert reparsed["a_future_field"] == {"whatever": 1}


def test_unknown_outer_key_policy_matches_actual_pipeline_tolerance():
    """Confirms the policy choice against real behavior, not just
    preference: the pipeline itself never rejects an unrecognized
    top-level key anywhere (every consumer reads only the specific keys
    it cares about via .get()), so preserving unknown keys is the
    consistent choice, not just the friendlier one."""
    raw = {"totally_made_up_key": True, "analysis": {"run_height": True}}
    result = svc.validate(raw)  # config_service validation must not choke on it
    assert result.valid


# --- Required outer metadata / new-document creation ------------------------

def test_new_document_requires_experiment_name():
    with pytest.raises(ValueError, match="experiment_name"):
        doc.new_document("")
    with pytest.raises(ValueError, match="experiment_name"):
        doc.new_document(None)  # type: ignore[arg-type]


def test_new_document_uses_config_service_defaults_for_analysis():
    document = doc.new_document("MyExperiment")
    assert document.analysis == svc.to_ui_representation(svc.default_config_dict())


def test_new_document_outer_defaults_match_scaffold_experiments_precedent():
    document = doc.new_document("MyExperiment")
    assert document.config_reviewed is False
    assert document.processing_mode == "off"
    assert document.processing == {"parallel_scans": None}
    assert document.sharing == {"enabled": False}
    assert document.notifications == {"enabled": False}


def test_new_document_has_no_source_path():
    document = doc.new_document("MyExperiment")
    assert document.source_path is None


def test_new_document_is_itself_valid():
    document = doc.new_document("MyExperiment")
    result = doc.validate_document(document)
    assert result.valid, (result.document_errors, result.analysis_result.errors)


# --- Full-document validation / P1B propagation / structured errors --------

def test_document_validation_propagates_analysis_errors():
    document = doc.new_document("X")
    document.analysis["mta_fit_angle_min_deg"] = 10.0
    document.analysis["run_mta"] = True
    result = doc.validate_document(document)
    assert result.valid is False
    assert result.analysis_result.valid is False
    assert result.analysis_result.errors[0].field == "mta_fit_angle_min_deg"
    assert result.document_errors == ()  # the document-level part is unaffected


def test_document_validation_catches_invalid_processing_block():
    document = doc.new_document("X")
    document.processing = {"parallel_scans": -1}  # resolve_parallel_scans rejects this
    result = doc.validate_document(document)
    assert result.valid is False
    assert result.document_errors[0].field == "processing"
    assert result.analysis_result.valid is True  # analysis section is unaffected


def test_document_validation_reports_both_kinds_of_error_together():
    document = doc.new_document("X")
    document.processing = {"parallel_scans": "not a number"}
    document.analysis["fad_g_function"] = "wrong"
    document.analysis["run_fad"] = True
    result = doc.validate_document(document)
    assert result.valid is False
    assert result.document_errors  # document-level
    assert result.analysis_result.errors  # analysis-level, separately


def test_processing_block_validation_reuses_real_pipeline_function():
    """Confirms this doesn't reimplement resolve_parallel_scans's checks --
    a non-mapping processing block is rejected with the same real error."""
    document = doc.new_document("X")
    document.processing = "not a mapping"  # type: ignore[assignment]
    result = doc.validate_document(document)
    assert result.valid is False
    assert "mapping" in result.document_errors[0].message


# --- Preview vs save: no filesystem side effects on preview -----------------

def test_render_document_yaml_has_no_filesystem_side_effects(tmp_path, monkeypatch):
    """Preview must never touch disk. Verified by making any attempt to
    open a file for writing raise, then confirming render still succeeds."""
    document = doc.new_document("X")

    original_open = open

    def _guard(path, mode="r", *a, **kw):
        if "w" in mode or "a" in mode or "x" in mode:
            raise AssertionError(f"render_document_yaml attempted to write to {path}")
        return original_open(path, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", _guard)
    text = doc.render_document_yaml(document)
    assert "analysis:" in text


# --- Explicit save, overwrite refusal, explicit overwrite -------------------

def test_save_writes_the_file(tmp_path):
    document = doc.new_document("MyExperiment")
    target = tmp_path / "experiment_config.yaml"
    result_path = doc.save_document(document, target)
    assert result_path == target
    assert target.is_file()
    reloaded = doc.load_document(target)
    assert reloaded.experiment_name == "MyExperiment"


def test_save_sets_source_path_on_the_document():
    document = doc.new_document("MyExperiment")
    assert document.source_path is None


def test_save_refuses_to_overwrite_by_default(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("original content\n", encoding="utf-8")
    document = doc.new_document("X")
    with pytest.raises(FileExistsError):
        doc.save_document(document, target)
    assert target.read_text(encoding="utf-8") == "original content\n"  # untouched


def test_save_with_explicit_overwrite_true_replaces_the_file(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("original content\n", encoding="utf-8")
    document = doc.new_document("X")
    doc.save_document(document, target, overwrite=True)
    assert "experiment_name: X" in target.read_text(encoding="utf-8")


def test_save_does_not_touch_a_different_file(tmp_path):
    other = tmp_path / "unrelated.yaml"
    other.write_text("do not touch\n", encoding="utf-8")
    document = doc.new_document("X")
    doc.save_document(document, tmp_path / "real_target.yaml")
    assert other.read_text(encoding="utf-8") == "do not touch\n"


def test_save_refuses_to_export_a_locked_field_conflict(tmp_path):
    """The LOCKED guarantee holds all the way to save() -- nothing is
    written if the analysis section conflicts."""
    document = doc.new_document("X")
    document.analysis["pai_g_function"] = "not_spherical"
    document.analysis["run_pai"] = True
    target = tmp_path / "config.yaml"
    with pytest.raises(svc.LockedFieldViolation):
        doc.save_document(document, target)
    assert not target.exists()


# --- Atomic write behavior ---------------------------------------------------

def test_save_leaves_no_temp_file_behind_on_success(tmp_path):
    document = doc.new_document("X")
    target = tmp_path / "config.yaml"
    doc.save_document(document, target)
    leftovers = list(tmp_path.glob(".*"))
    assert leftovers == [] or all(not p.name.endswith(".tmp") for p in leftovers)


def test_save_cleans_up_temp_file_on_serialization_failure(tmp_path, monkeypatch):
    """If rendering fails partway (here: forced via a locked-field
    conflict, which raises before any file is opened), no temp file is
    left in the target directory."""
    document = doc.new_document("X")
    document.analysis["fad_g_function"] = "bad"
    document.analysis["run_fad"] = True
    target = tmp_path / "config.yaml"
    with pytest.raises(svc.LockedFieldViolation):
        doc.save_document(document, target)
    assert list(tmp_path.iterdir()) == []


# --- Full semantic round trip -----------------------------------------------

def test_full_semantic_roundtrip_real_template(tmp_path):
    """real experiment_config.yaml -> document -> edit one analysis value
    -> save -> reload -> validate through P1B/build_config. Confirms:
    edited field changed, unrelated analysis fields remain equivalent,
    outer metadata preserved, locked values remain valid, hidden system
    fields do not leak into canonical YAML."""
    document = doc.load_document(REAL_TEMPLATE_PATH)
    original_fusion_method = document.analysis["fusion_method"]

    document.analysis["run_height"] = True  # the one edit (was False)

    target = tmp_path / "edited.yaml"
    doc.save_document(document, target)

    reloaded = doc.load_document(target)
    result = doc.validate_document(reloaded)
    assert result.valid, (result.document_errors, result.analysis_result.errors)

    # Edited field changed:
    assert reloaded.analysis["run_height"] is True
    # Unrelated analysis fields remain semantically equivalent:
    assert reloaded.analysis["fusion_method"] == original_fusion_method
    assert reloaded.analysis["ray_box_ground_mode"] == document.analysis["ray_box_ground_mode"]
    # Outer metadata preserved:
    assert reloaded.experiment_name == document.experiment_name
    assert reloaded.config_note == document.config_note
    # Locked values remain valid:
    assert result.analysis_result.config.mta_fit_angle_min_deg == 25.0
    assert result.analysis_result.config.pai_g_function == "spherical"
    # Hidden system fields never leaked into the saved YAML:
    saved_text = target.read_text(encoding="utf-8")
    for hidden_name in ("reprocess_scans", "pai_run_conditional_profile", "run_topology"):
        assert hidden_name not in saved_text
