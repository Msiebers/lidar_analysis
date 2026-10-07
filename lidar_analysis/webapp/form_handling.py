"""Browser form input -> typed changes on an ExperimentConfigDocument (Web-P1D).

HTML forms deliver every value as a string. Nothing below this layer parses
form strings: config_service.validate() hands values straight to
central_runner.build_config(), whose pick() casts with float()/int()/bool()
or, for some fields (start_u, max_y_u, rssi_min, ...), not at all. Two
concrete consequences, both confirmed by reading build_config before
writing this module:

* A cleared required number reaches build_config as None and fails inside
  pick() as "float() argument must be a string or a real number, not
  'NoneType'" -- a message naming no field, so validate() cannot attribute
  it. Blank required fields are therefore reported here, by field, and
  never handed down.
* An unparsed "abc" for an uncast field would *pass* validation and be
  written to YAML as a string; bool("false") is True. So every value is
  parsed to its real type here first.

Scope is input parsing only. Field existence, type and optionality come
from config_schema (the live AnalysisConfig dataclass); labels, tiers and
choices from config_ui_metadata. Whether a parsed configuration is
scientifically valid is still decided only by validate_document() ->
build_config(), never here.

Absence is preserved deliberately. build_config() treats some absent keys
differently from the same key written with its default value
(write_reference_points follows write_marker_pointcloud;
missing_mark_file falls back to markers_required; ray_box.* fall back to
the flat field names). So a field absent from the document is rendered
blank, a blank submission for it is "no change", and only fields whose
parsed value actually differs from the document are written.
"""
from __future__ import annotations

import enum
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from lidar_analysis.webapp.config_schema import ConfigFieldSchema, introspect_analysis_config_fields
from lidar_analysis.webapp.config_service import ValidationError
from lidar_analysis.webapp.config_ui_metadata import (
    ControlType,
    FieldMetadata,
    Tier,
    UI_METADATA,
)
from lidar_analysis.webapp.experiment_document import ExperimentConfigDocument

ANALYSIS_PREFIX = "analysis."
OUTER_PREFIX = "doc."

# Rendered somewhere other than the flat field form:
#   pointcloud_ops          -- ordered pipeline, its own editor
#   pcl_backend             -- ControlType.RAW, shown read-only
#   use_local_ground_filter -- second name for apply_ground_filter (see below)
_NOT_FLAT_FORM_FIELDS = frozenset({"pointcloud_ops", "pcl_backend", "use_local_ground_filter"})

# build_config() reads apply_ground_filter first, then use_local_ground_filter,
# and sets both AnalysisConfig fields to the same value;
# config_service.to_ui_representation() likewise sets both whenever either is
# present. One control is rendered, and a change writes both keys -- the same
# state to_ui_representation() itself produces.
_GROUND_FIELD = "apply_ground_filter"
_GROUND_LEGACY_FIELD = "use_local_ground_filter"

# Notes shown beside a field, each established from repository code.
_FIELD_NOTES: dict[str, str] = {
    "n_plots": (
        "Not currently applied: build_config() does not pass n_plots to the "
        "pipeline, so this value does not cap the distance-split plot count. "
        "It is still saved in the file."
    ),
    _GROUND_FIELD: (
        "Also sets use_local_ground_filter, the legacy name for the same "
        "setting, to the same value."
    ),
}

_INT_PATTERN = re.compile(r"[+-]?\d+")
_FLOAT_PATTERN = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_BOOL_STRINGS = {"true": True, "false": False}


class ValueKind(enum.Enum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STR = "str"


_KIND_BY_TYPE = {bool: ValueKind.BOOL, int: ValueKind.INT, float: ValueKind.FLOAT, str: ValueKind.STR}


@dataclass(frozen=True)
class FormFieldSpec:
    """One rendered form field. `required` means the dataclass annotation
    is not Optional -- None is not a value the pipeline accepts for it."""

    name: str
    form_key: str
    label: str
    description: str
    kind: ValueKind
    required: bool
    default: Any
    has_default: bool
    choices: tuple[str, ...] = ()
    read_only: bool = False
    note: str | None = None
    metadata: FieldMetadata | None = None


@dataclass(frozen=True)
class FieldState:
    """present=False means the key is absent from the document."""

    present: bool
    value: Any


@dataclass(frozen=True)
class FormApplyResult:
    applied: bool
    errors: tuple[ValidationError, ...]
    changed_fields: tuple[str, ...]


def _analysis_spec(schema: ConfigFieldSchema, meta: FieldMetadata) -> FormFieldSpec:
    kind = _KIND_BY_TYPE.get(schema.type_info.inner)
    if kind is None:
        raise TypeError(
            f"{schema.name}: no form parser for type {schema.type_info.raw!r}; "
            "add one here or exclude the field from the flat form"
        )
    return FormFieldSpec(
        name=schema.name,
        form_key=ANALYSIS_PREFIX + schema.name,
        label=meta.label,
        description=meta.description,
        kind=kind,
        required=not schema.type_info.is_optional,
        default=schema.default,
        has_default=schema.has_default,
        choices=meta.choices,
        read_only=meta.tier is Tier.LOCKED,
        note=_FIELD_NOTES.get(schema.name),
        metadata=meta,
    )


def analysis_field_specs() -> tuple[FormFieldSpec, ...]:
    """Every rendered analysis field, in UI_METADATA registration order
    (which follows its section order). HIDDEN_SYSTEM fields are never
    included."""
    schemas = {s.name: s for s in introspect_analysis_config_fields()}
    return tuple(
        _analysis_spec(schemas[name], meta)
        for name, meta in UI_METADATA.items()
        if meta.tier is not Tier.HIDDEN_SYSTEM and name not in _NOT_FLAT_FORM_FIELDS
    )


# Outer envelope fields edited in P1D. The remaining known outer fields
# (processing_mode, raw_data_path, output_path, sharing, notifications) are
# read by no live pipeline path (see experiment_document.py) and are shown
# read-only, preserved as loaded.
_OUTER_SPECS: tuple[FormFieldSpec, ...] = (
    FormFieldSpec(
        name="experiment_name", form_key=OUTER_PREFIX + "experiment_name",
        label="Experiment name",
        description="Documentary: the pipeline takes the experiment identity from the --experiment command-line argument.",
        kind=ValueKind.STR, required=True, default=None, has_default=False,
    ),
    FormFieldSpec(
        name="config_note", form_key=OUTER_PREFIX + "config_note",
        label="Config note", description="Free-text note for people reading this file. Not read by the pipeline.",
        kind=ValueKind.STR, required=False, default=None, has_default=False,
    ),
    FormFieldSpec(
        name="config_reviewed", form_key=OUTER_PREFIX + "config_reviewed",
        label="Config reviewed", description="Human sign-off marker. Not read by the pipeline.",
        kind=ValueKind.BOOL, required=False, default=None, has_default=False,
    ),
    FormFieldSpec(
        name="processing", form_key=OUTER_PREFIX + "processing.parallel_scans",
        label="Parallel scans",
        description="processing.parallel_scans: number of scans processed in parallel. Leave blank for the pipeline default.",
        kind=ValueKind.INT, required=False, default=None, has_default=False,
    ),
)


def outer_field_specs() -> tuple[FormFieldSpec, ...]:
    return _OUTER_SPECS


def analysis_field_state(analysis: Mapping[str, Any], spec: FormFieldSpec) -> FieldState:
    if spec.name == _GROUND_FIELD:
        for key in (_GROUND_FIELD, _GROUND_LEGACY_FIELD):
            if key in analysis:
                return FieldState(True, analysis[key])
        return FieldState(False, None)
    if spec.name in analysis:
        return FieldState(True, analysis[spec.name])
    return FieldState(False, None)


def outer_field_state(document: ExperimentConfigDocument, spec: FormFieldSpec) -> FieldState:
    if spec.name == "processing":
        processing = document.processing
        if isinstance(processing, dict) and "parallel_scans" in processing:
            return FieldState(True, processing["parallel_scans"])
        return FieldState(False, None)
    value = getattr(document, spec.name)
    return FieldState(value is not None, value)


def format_form_value(value: Any) -> str:
    """The string a form input shows for a stored value; parse_value()
    reads it back to the same value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def parse_value(spec: FormFieldSpec, raw: str, *, current: Any = None) -> tuple[Any, str | None]:
    """Parse one non-blank form string to spec's type. Returns
    (value, None) or (None, researcher-facing error message)."""
    text = raw.strip()
    if spec.kind is ValueKind.BOOL:
        if text in _BOOL_STRINGS:
            return _BOOL_STRINGS[text], None
        return None, f"{spec.label} must be true or false (got {raw!r})."
    if spec.kind is ValueKind.INT:
        if _INT_PATTERN.fullmatch(text):
            return int(text), None
        return None, f"{spec.label} must be a whole number (got {raw!r})."
    if spec.kind is ValueKind.FLOAT:
        if not _FLOAT_PATTERN.fullmatch(text):
            if text.lower().lstrip("+-") in {"nan", "inf", "infinity"}:
                return None, f"{spec.label} must be a finite number (got {raw!r})."
            return None, f"{spec.label} must be a number (got {raw!r})."
        value = float(text)
        if not math.isfinite(value):
            return None, f"{spec.label} must be a finite number (got {raw!r})."
        return value, None
    # STR: free text, or a select whose submitted value must be one of the
    # metadata choices -- or the value already in the document, so a file
    # holding a value outside the known choices can still be opened and
    # re-saved without being forced to change it.
    if spec.choices and text not in spec.choices and text != current:
        return None, f"{spec.label} must be one of: {', '.join(spec.choices)} (got {raw!r})."
    return text, None


def _same_value(a: Any, b: Any) -> bool:
    """Equality that does not treat True as 1 or 5 as different from 5.0."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return type(a) is type(b) and a == b
    return a == b


def _required_message(spec: FormFieldSpec) -> str:
    message = f"{spec.label} is required and cannot be left blank."
    if spec.has_default:
        message += f" The pipeline default is {format_form_value(spec.default) or 'null'}."
    return message


def resolve_submitted(spec: FormFieldSpec, state: FieldState, raw: str) -> tuple[bool, Any, str | None]:
    """(changed, new_value, error) for one submitted field: blank on an
    absent or null value is no change; blank on a set required value is an
    error; otherwise the parsed value, if it differs from the current one."""
    if not raw.strip():
        if not state.present or state.value is None:
            return False, None, None
        if spec.required:
            return False, None, _required_message(spec)
        return True, None, None
    value, error = parse_value(spec, raw, current=state.value)
    if error is not None:
        return False, None, error
    if state.present and _same_value(state.value, value):
        return False, None, None
    return True, value, None


def apply_field_form(document: ExperimentConfigDocument, form: Mapping[str, str]) -> FormApplyResult:
    """Apply a submitted field form to `document`, all-or-nothing: if any
    field fails to parse, nothing is changed and every error is returned
    together. Fields not present in `form`, read-only (LOCKED) fields,
    HIDDEN_SYSTEM fields and unknown keys are never written."""
    errors: list[ValidationError] = []
    analysis_changes: dict[str, Any] = {}
    outer_changes: dict[str, Any] = {}

    for spec in analysis_field_specs():
        if spec.read_only or spec.form_key not in form:
            continue
        changed, value, error = resolve_submitted(spec, analysis_field_state(document.analysis, spec), form[spec.form_key])
        if error is not None:
            errors.append(ValidationError(field=spec.name, message=error))
        elif changed:
            analysis_changes[spec.name] = value

    for spec in outer_field_specs():
        if spec.form_key not in form:
            continue
        changed, value, error = resolve_submitted(spec, outer_field_state(document, spec), form[spec.form_key])
        if error is not None:
            errors.append(ValidationError(field=spec.name, message=error))
        elif changed:
            outer_changes[spec.name] = value

    if errors:
        return FormApplyResult(applied=False, errors=tuple(errors), changed_fields=())

    for name, value in analysis_changes.items():
        document.analysis[name] = value
        if name == _GROUND_FIELD:
            document.analysis[_GROUND_LEGACY_FIELD] = value
    for name, value in outer_changes.items():
        if name == "processing":
            processing = dict(document.processing) if isinstance(document.processing, dict) else {}
            processing["parallel_scans"] = value
            document.processing = processing
        else:
            setattr(document, name, value)

    return FormApplyResult(
        applied=True,
        errors=(),
        changed_fields=tuple(analysis_changes) + tuple(outer_changes),
    )


def reset_locked_field(document: ExperimentConfigDocument, name: str) -> None:
    """Explicit researcher action: set a LOCKED field to its enforced value.
    A conflicting value loaded from a file is never corrected implicitly
    (config_service surfaces it as an error instead); this is the one way
    the editor changes it. Raises KeyError for a field that is not LOCKED."""
    meta = UI_METADATA.get(name)
    if meta is None or meta.tier is not Tier.LOCKED:
        raise KeyError(name)
    document.analysis[name] = meta.locked_value


def required_value_problems(document: ExperimentConfigDocument) -> tuple[ValidationError, ...]:
    """Required fields set to null in the document itself (e.g. a file
    with `start_u: null`). The form never produces these, but an opened
    file can contain them, and build_config() would then either fail with
    an unattributable "float() ... 'NoneType'" or, for fields it does not
    cast, pass None through. Reported by name with the same rule the form
    applies to a cleared field."""
    problems = []
    for spec in analysis_field_specs():
        if spec.read_only or not spec.required:
            continue
        state = analysis_field_state(document.analysis, spec)
        if state.present and state.value is None:
            problems.append(ValidationError(
                field=spec.name,
                message=f"{spec.label} is empty (null) in this file, but it requires a value. Enter one in the editor.",
            ))
    return tuple(problems)
