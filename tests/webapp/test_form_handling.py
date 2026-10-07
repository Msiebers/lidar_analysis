"""Tests for form_handling.py -- turning browser form strings into typed
changes on an ExperimentConfigDocument (Web-P1D).

The two properties everything else rests on:

* A blank required field is a structured, field-attributed form error --
  never a value handed to build_config(), whose pick() would otherwise
  raise "float() argument must be a string or a real number, not
  'NoneType'" with no attributable field.
* A form submitted without changes leaves the analysis mapping exactly as
  it was -- in particular, keys absent from the file stay absent, because
  build_config() has fallbacks (write_reference_points, missing_mark_file,
  ray_box.*) that only apply when a key is absent.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lidar_analysis.webapp import config_service as svc
from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp import form_handling as fh
from lidar_analysis.webapp.config_ui_metadata import ControlType, Tier, UI_METADATA

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_TEMPLATE_PATH = REPO_ROOT / "experiment_config.yaml"
REAL_CONFIG_PATHS = (
    REAL_TEMPLATE_PATH,
    REPO_ROOT / "lidar_analysis" / "example_configs" / "full_experiment_config_template.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "premerge_pai_biomass.yaml",
)


def _specs_by_name() -> dict[str, fh.FormFieldSpec]:
    return {spec.name: spec for spec in fh.analysis_field_specs()}


def _unchanged_form(document: doc.ExperimentConfigDocument) -> dict[str, str]:
    """What a browser posts back for the editor exactly as rendered: the
    current value for every set field, an empty string for every field
    absent from the document."""
    form: dict[str, str] = {}
    for spec in fh.analysis_field_specs():
        if spec.read_only:
            continue
        state = fh.analysis_field_state(document.analysis, spec)
        form[spec.form_key] = fh.format_form_value(state.value) if state.present else ""
    for spec in fh.outer_field_specs():
        state = fh.outer_field_state(document, spec)
        form[spec.form_key] = fh.format_form_value(state.value) if state.present else ""
    return form


def _field_errors(result: fh.FormApplyResult) -> dict[str | None, str]:
    return {error.field: error.message for error in result.errors}


# --- Field specs are derived from the P1A schema + metadata ----------------

def test_specs_never_include_hidden_system_fields():
    names = set(_specs_by_name())
    hidden = {n for n, m in UI_METADATA.items() if m.tier is Tier.HIDDEN_SYSTEM}
    assert hidden
    assert not names & hidden


def test_specs_cover_every_visible_scalar_field():
    """Every non-hidden field is rendered except the ones handled
    elsewhere: pointcloud_ops (its own pipeline editor), pcl_backend
    (RAW, read-only display) and use_local_ground_filter (mirrored by
    apply_ground_filter)."""
    expected = {
        n for n, m in UI_METADATA.items()
        if m.tier is not Tier.HIDDEN_SYSTEM
    } - {"pointcloud_ops", "pcl_backend", "use_local_ground_filter"}
    assert set(_specs_by_name()) == expected


def test_spec_kinds_agree_with_control_types():
    for spec in fh.analysis_field_specs():
        control = spec.metadata.control_type
        if control is ControlType.TOGGLE:
            assert spec.kind is fh.ValueKind.BOOL, spec.name
        elif control is ControlType.NUMBER:
            assert spec.kind in (fh.ValueKind.INT, fh.ValueKind.FLOAT), spec.name
        else:
            assert control in (ControlType.SELECT, ControlType.TEXT), spec.name
            assert spec.kind is fh.ValueKind.STR, spec.name


def test_spec_types_and_requiredness_come_from_the_dataclass():
    specs = _specs_by_name()
    assert specs["row_width_u"].kind is fh.ValueKind.FLOAT
    assert specs["row_width_u"].required is True
    assert specs["local_ground_min_points_per_xz_bin"].kind is fh.ValueKind.INT
    assert specs["n_plots"].kind is fh.ValueKind.INT
    assert specs["n_plots"].required is False
    assert specs["analyze_side"].kind is fh.ValueKind.STR
    assert specs["analyze_side"].required is False


def test_locked_fields_are_read_only_specs():
    specs = _specs_by_name()
    for name, meta in UI_METADATA.items():
        if meta.tier is Tier.LOCKED:
            assert specs[name].read_only is True


def test_n_plots_carries_a_not_currently_applied_note():
    note = _specs_by_name()["n_plots"].note
    assert note and "not currently applied" in note.lower()


# --- Regression: clearing a required numeric field -------------------------

def test_lower_layer_still_reports_blank_numeric_as_unattributed_type_error():
    """Characterizes the P1B/build_config behavior the form layer exists to
    keep users away from. Not changed by P1D; if this starts failing, the
    lower layer changed and this form-layer guard should be revisited."""
    analysis = svc.to_ui_representation(svc.default_config_dict())
    analysis["row_width_u"] = None
    result = svc.validate(analysis)
    assert not result.valid
    assert result.errors[0].field is None
    assert "NoneType" in result.errors[0].message


def test_clearing_a_required_numeric_field_is_a_field_error_not_a_type_error():
    document = doc.new_document("X")
    before = copy.deepcopy(document.analysis)
    form = _unchanged_form(document)
    form["analysis.row_width_u"] = ""

    result = fh.apply_field_form(document, form)

    assert result.applied is False
    errors = _field_errors(result)
    assert set(errors) == {"row_width_u"}
    assert "required" in errors["row_width_u"].lower()
    assert "NoneType" not in errors["row_width_u"]
    assert "float()" not in errors["row_width_u"]
    assert document.analysis == before


def test_whitespace_only_counts_as_blank():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.row_width_u": "   "})
    assert set(_field_errors(result)) == {"row_width_u"}


# --- Absence semantics -------------------------------------------------------

@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_unchanged_submission_preserves_real_documents_exactly(path):
    document = doc.load_document(path)
    analysis_before = copy.deepcopy(document.analysis)
    yaml_before = doc.render_document_yaml(document)

    result = fh.apply_field_form(document, _unchanged_form(document))

    assert result.errors == ()
    assert result.changed_fields == ()
    assert document.analysis == analysis_before
    assert set(document.analysis) == set(analysis_before)
    assert doc.render_document_yaml(document) == yaml_before


def test_unchanged_submission_preserves_a_new_document_exactly():
    document = doc.new_document("X")
    yaml_before = doc.render_document_yaml(document)
    result = fh.apply_field_form(document, _unchanged_form(document))
    assert result.changed_fields == ()
    assert doc.render_document_yaml(document) == yaml_before


def test_blank_on_an_absent_field_keeps_it_absent():
    document = doc.new_document("X")
    assert "mta_max_observation_range_m" not in document.analysis
    assert "write_reference_points" in document.analysis
    del document.analysis["write_reference_points"]

    result = fh.apply_field_form(
        document,
        {"analysis.mta_max_observation_range_m": "", "analysis.write_reference_points": ""},
    )

    assert result.errors == ()
    assert "mta_max_observation_range_m" not in document.analysis
    assert "write_reference_points" not in document.analysis


def test_fields_missing_from_the_post_are_left_unchanged():
    document = doc.new_document("X")
    before = copy.deepcopy(document.analysis)
    result = fh.apply_field_form(document, {})
    assert result.applied is True
    assert result.changed_fields == ()
    assert document.analysis == before


def test_setting_an_absent_field_writes_only_that_key():
    document = doc.new_document("X")
    keys_before = set(document.analysis)
    result = fh.apply_field_form(document, {"analysis.mta_max_observation_range_m": "40"})
    assert result.changed_fields == ("mta_max_observation_range_m",)
    assert set(document.analysis) == keys_before | {"mta_max_observation_range_m"}
    assert document.analysis["mta_max_observation_range_m"] == 40.0


def test_unchanged_int_valued_float_field_keeps_its_original_type():
    document = doc.new_document("X")
    document.analysis["row_width_u"] = 5
    result = fh.apply_field_form(document, {"analysis.row_width_u": "5"})
    assert result.changed_fields == ()
    assert type(document.analysis["row_width_u"]) is int


# --- Optional fields ----------------------------------------------------------

def test_clearing_a_set_optional_numeric_field_writes_explicit_null():
    document = doc.load_document(REAL_TEMPLATE_PATH)
    assert document.analysis["local_ground_seed_y_min_m"] == -0.08
    result = fh.apply_field_form(document, {"analysis.local_ground_seed_y_min_m": ""})
    assert result.errors == ()
    assert "local_ground_seed_y_min_m" in document.analysis
    assert document.analysis["local_ground_seed_y_min_m"] is None


def test_clearing_an_optional_select_writes_explicit_null():
    document = doc.load_document(REAL_TEMPLATE_PATH)
    assert document.analysis["analyze_side"] == "right"
    result = fh.apply_field_form(document, {"analysis.analyze_side": ""})
    assert result.errors == ()
    assert document.analysis["analyze_side"] is None


# --- Strict parsing ----------------------------------------------------------

@pytest.mark.parametrize("raw", ["abc", "1,5", "true", "1_000"])
def test_non_numeric_text_is_rejected_for_numeric_fields(raw):
    """start_u is passed through build_config() without a cast, so an
    unparsed string would validate and be written to YAML as a string."""
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.start_u": raw})
    assert set(_field_errors(result)) == {"start_u"}
    assert document.analysis["start_u"] == 0.0


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_non_finite_numbers_are_rejected(raw):
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.row_width_u": raw})
    assert set(_field_errors(result)) == {"row_width_u"}


@pytest.mark.parametrize("raw", ["3.5", "50.0", "5e1", "abc"])
def test_int_fields_are_parsed_strictly(raw):
    """build_config() would int() a float and silently truncate it."""
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.local_ground_min_points_per_xz_bin": raw})
    assert set(_field_errors(result)) == {"local_ground_min_points_per_xz_bin"}


def test_valid_numbers_are_stored_with_their_real_types():
    document = doc.new_document("X")
    result = fh.apply_field_form(
        document,
        {"analysis.local_ground_min_points_per_xz_bin": " 50 ", "analysis.row_width_u": "0.75"},
    )
    assert result.errors == ()
    assert document.analysis["local_ground_min_points_per_xz_bin"] == 50
    assert type(document.analysis["local_ground_min_points_per_xz_bin"]) is int
    assert document.analysis["row_width_u"] == 0.75
    assert type(document.analysis["row_width_u"]) is float


def test_booleans_are_real_bools():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.run_height": "true", "analysis.use_imu": "false"})
    assert result.errors == ()
    assert document.analysis["run_height"] is True
    assert document.analysis["use_imu"] is False


@pytest.mark.parametrize("raw", ["yes", "on", "1", "False", "TRUE"])
def test_non_canonical_boolean_strings_are_rejected(raw):
    """The editor's own <select> only ever sends "true"/"false"; anything
    else is not guessed at (bool("false") is True in Python)."""
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.run_height": raw})
    assert set(_field_errors(result)) == {"run_height"}


def test_select_values_must_be_known_choices():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.fusion_method": "made_up"})
    assert set(_field_errors(result)) == {"fusion_method"}


def test_an_existing_out_of_choice_select_value_is_preserved():
    document = doc.new_document("X")
    document.analysis["fusion_method"] = "legacy_value"
    result = fh.apply_field_form(document, {"analysis.fusion_method": "legacy_value"})
    assert result.errors == ()
    assert result.changed_fields == ()
    assert document.analysis["fusion_method"] == "legacy_value"


def test_blank_required_text_field_is_an_error():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"analysis.markers_dirname": ""})
    assert set(_field_errors(result)) == {"markers_dirname"}


# --- Fields the form must never write ----------------------------------------

def test_locked_fields_are_never_written_from_a_post():
    document = doc.new_document("X")
    before = copy.deepcopy(document.analysis)
    result = fh.apply_field_form(
        document, {"analysis.mta_fit_angle_min_deg": "30", "analysis.pai_g_function": "other"}
    )
    assert result.changed_fields == ()
    assert document.analysis == before


def test_hidden_and_unknown_fields_are_never_written_from_a_post():
    document = doc.new_document("X")
    before = copy.deepcopy(document.analysis)
    result = fh.apply_field_form(
        document,
        {"analysis.cart_id": "X", "analysis.reprocess_scans": "true", "analysis.not_a_field": "1"},
    )
    assert result.changed_fields == ()
    assert document.analysis == before


# --- All-or-nothing ------------------------------------------------------------

def test_any_error_means_no_change_is_applied():
    document = doc.new_document("X")
    before = copy.deepcopy(document.analysis)
    result = fh.apply_field_form(
        document, {"analysis.run_height": "true", "analysis.row_width_u": ""}
    )
    assert result.applied is False
    assert document.analysis == before


def test_every_error_is_reported_together():
    document = doc.new_document("X")
    result = fh.apply_field_form(
        document, {"analysis.row_width_u": "", "analysis.start_u": "abc", "doc.experiment_name": ""}
    )
    assert set(_field_errors(result)) == {"row_width_u", "start_u", "experiment_name"}


# --- Ground filter: one control, both keys --------------------------------------

def test_ground_filter_change_sets_both_keys():
    document = doc.load_document(REAL_TEMPLATE_PATH)
    assert document.analysis["apply_ground_filter"] is True
    assert document.analysis["use_local_ground_filter"] is True
    result = fh.apply_field_form(document, {"analysis.apply_ground_filter": "false"})
    assert result.errors == ()
    assert document.analysis["apply_ground_filter"] is False
    assert document.analysis["use_local_ground_filter"] is False


def test_ground_filter_state_follows_build_config_precedence():
    spec = _specs_by_name()["apply_ground_filter"]
    assert fh.analysis_field_state({"use_local_ground_filter": True}, spec) == fh.FieldState(True, True)
    assert fh.analysis_field_state(
        {"apply_ground_filter": False, "use_local_ground_filter": True}, spec
    ) == fh.FieldState(True, False)
    assert fh.analysis_field_state({}, spec) == fh.FieldState(False, None)


def test_ground_filter_absent_from_both_keys_stays_absent():
    document = doc.new_document("X")
    del document.analysis["apply_ground_filter"]
    del document.analysis["use_local_ground_filter"]
    result = fh.apply_field_form(document, {"analysis.apply_ground_filter": ""})
    assert result.errors == ()
    assert "apply_ground_filter" not in document.analysis
    assert "use_local_ground_filter" not in document.analysis


def test_ground_filter_change_on_a_legacy_only_file_sets_both_keys():
    document = doc.new_document("X")
    del document.analysis["apply_ground_filter"]
    document.analysis["use_local_ground_filter"] = False
    result = fh.apply_field_form(document, {"analysis.apply_ground_filter": "true"})
    assert result.errors == ()
    assert document.analysis["apply_ground_filter"] is True
    assert document.analysis["use_local_ground_filter"] is True


# --- Outer document fields --------------------------------------------------------

def test_blank_experiment_name_is_an_error():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"doc.experiment_name": "  "})
    assert set(_field_errors(result)) == {"experiment_name"}
    assert document.experiment_name == "X"


def test_experiment_name_is_stripped():
    document = doc.new_document("X")
    fh.apply_field_form(document, {"doc.experiment_name": "  MeadowFescue_2026 "})
    assert document.experiment_name == "MeadowFescue_2026"


def test_clearing_config_note_removes_it():
    document = doc.new_document("X")
    assert document.config_note
    fh.apply_field_form(document, {"doc.config_note": ""})
    assert document.config_note is None


def test_config_reviewed_is_a_real_bool():
    document = doc.new_document("X")
    fh.apply_field_form(document, {"doc.config_reviewed": "true"})
    assert document.config_reviewed is True


def test_parallel_scans_is_parsed_into_the_processing_block():
    document = doc.new_document("X")
    document.processing = {"parallel_scans": None, "other_key": "kept"}
    result = fh.apply_field_form(document, {"doc.processing.parallel_scans": "4"})
    assert result.errors == ()
    assert document.processing == {"parallel_scans": 4, "other_key": "kept"}


def test_parallel_scans_absent_processing_block_stays_absent_when_blank():
    document = doc.new_document("X")
    document.processing = None
    fh.apply_field_form(document, {"doc.processing.parallel_scans": ""})
    assert document.processing is None


def test_parallel_scans_must_be_a_whole_number():
    document = doc.new_document("X")
    result = fh.apply_field_form(document, {"doc.processing.parallel_scans": "2.5"})
    assert set(_field_errors(result)) == {"processing"}


# --- Formatting for re-rendering -----------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [(None, ""), (True, "true"), (False, "false"), (5, "5"), (0.05, "0.05"), (1e-05, "1e-05"), ("x", "x")],
)
def test_format_form_value(value, expected):
    assert fh.format_form_value(value) == expected


def test_formatted_values_parse_back_to_the_same_value():
    document = doc.load_document(REAL_TEMPLATE_PATH)
    for spec in fh.analysis_field_specs():
        state = fh.analysis_field_state(document.analysis, spec)
        if spec.read_only or not state.present or state.value is None:
            continue
        parsed, error = fh.parse_value(spec, fh.format_form_value(state.value), current=state.value)
        assert error is None, (spec.name, error)
        assert parsed == state.value, spec.name
