"""Browser forms for the ordered pointcloud_ops pipeline (Web-P1D).

Each pointcloud_ops entry is a dict such as
{"op": "sor_filter", "enabled": true, "mean_k": 12, "std_ratio": 2.0}.
build_config() passes the list through unchecked, and
pointcloud_ops.apply_pointcloud_ops() runs the entries in list order, each
filter changing the cloud the next entry sees -- so order and exact
parameter types both matter, and nothing downstream validates them before
a pipeline run.

Parameter names, labels and defaults come from
config_ui_metadata.POINTCLOUD_OP_METADATA. That metadata does not record
whether a NUMBER is an int or a float, or whether None is accepted, so
PARAM_TYPES below records both, each read from the code that consumes the
parameter (pointcloud_ops.py unless noted). A test keeps PARAM_TYPES and
the metadata in lockstep.

Editing rules, matching form_handling's for flat fields:
* an existing entry keeps every key it already has, including keys this
  editor does not know (aliases such as nb_neighbors or field, or keys
  the pipeline never reads); only submitted, parsed, changed parameters
  are written, and an absent parameter left blank stays absent;
* a newly added entry writes every parameter explicitly (as the template
  does), because several code fallbacks differ from the metadata and
  template values (e.g. bilateral replace_scalar falls back to True);
* new entries go to their POINTCLOUD_OP_ORDER position relative to the
  other recognized entries; existing entries are never reordered.
"""
from __future__ import annotations

from typing import Any, Mapping

from lidar_analysis.webapp.config_service import ValidationError, _op_name
from lidar_analysis.webapp.config_ui_metadata import (
    POINTCLOUD_OP_METADATA,
    POINTCLOUD_OP_ORDER,
)
from lidar_analysis.webapp.experiment_document import ExperimentConfigDocument
from lidar_analysis.webapp.form_handling import (
    FieldState,
    FormFieldSpec,
    ValueKind,
    format_form_value,
    parse_value,
    resolve_submitted,
)

OP_FORM_PREFIX = "op."

_F, _I, _B, _S = ValueKind.FLOAT, ValueKind.INT, ValueKind.BOOL, ValueKind.STR

# (op, parameter) -> (kind, None accepted). "None accepted" only where the
# consumer explicitly treats None as "unset" (e.g. `if op_cfg.get("min") is
# not None`); everywhere else None would reach float()/int() and fail at run
# time, so a value is required.
PARAM_TYPES: dict[tuple[str, str], tuple[ValueKind, bool]] = {
    # _resolve_scalar_name: str(...); _scalar_range_filter: float() only if not None
    ("scalar_range_filter", "scalar"): (_S, False),
    ("scalar_range_filter", "min"): (_F, True),
    ("scalar_range_filter", "max"): (_F, True),
    # _sor_filter: int(mean_k), float(std_ratio)
    ("sor_filter", "mean_k"): (_I, False),
    ("sor_filter", "std_ratio"): (_F, False),
    # _bilateral_scalar_filter
    ("bilateral_scalar_filter", "scalar"): (_S, False),
    ("bilateral_scalar_filter", "sigma_spatial"): (_F, False),
    ("bilateral_scalar_filter", "sigma_range"): (_F, False),
    ("bilateral_scalar_filter", "radius"): (_F, False),
    ("bilateral_scalar_filter", "min_neighbors"): (_I, False),
    ("bilateral_scalar_filter", "max_neighbors"): (_I, False),
    ("bilateral_scalar_filter", "replace_scalar"): (_B, False),
    ("bilateral_scalar_filter", "output_scalar"): (_S, True),  # `or field`: blank/None -> input scalar
    # _height_range_filter: str(axis).upper(); float() only if not None
    ("height_range_filter", "axis"): (_S, False),
    ("height_range_filter", "min_m"): (_F, True),
    ("height_range_filter", "max_m"): (_F, True),
    # _voxel_count / apply_pointcloud_ops: float() if not None, else legacy keys
    ("voxel_count", "voxel_size_m"): (_F, True),
    # _topology_trait; include_per_m2 is read by central_runner.py and pipeline_core.py via bool()
    ("topology_trait", "min_persistence"): (_F, False),
    ("topology_trait", "z_bin_m"): (_F, False),
    ("topology_trait", "include_per_m2"): (_B, False),
    ("topology_trait", "split_sides_for_single_plot"): (_B, False),
    ("topology_trait", "skip_whole_when_split"): (_B, False),
    ("topology_trait", "write_topology_objects"): (_B, False),
    # apply_pointcloud_ops slice_structure_trait branch
    ("slice_structure_trait", "slice_height_m"): (_F, False),
    ("slice_structure_trait", "height_axis"): (_S, False),
    ("slice_structure_trait", "spread_axis"): (_S, False),
    ("slice_structure_trait", "length_axis"): (_S, False),
    ("slice_structure_trait", "percentile_height"): (_F, False),
    ("slice_structure_trait", "min_points_per_slice"): (_I, False),
    ("slice_structure_trait", "clump_grid_m"): (_F, False),
    ("slice_structure_trait", "clump_connectivity"): (_I, False),  # int(); metadata choices are "4"/"8"
    # _compute_canopy_volume_2p5d
    ("canopy_volume_2p5d", "cell_size_m"): (_F, False),
    ("canopy_volume_2p5d", "height_percentile"): (_F, False),
}

# No pre-filled value when adding: the sources disagree and the choice is
# scientific, so the researcher enters it.
_NO_PREFILL: dict[tuple[str, str], str] = {
    ("sor_filter", "mean_k"): (
        "Enter a value. For reference: full_experiment_config_template.yaml uses 12, "
        "the repository's experiment_config.yaml uses 3, and the pipeline falls back "
        "to 5 when mean_k is left out."
    ),
}

# (op, parameter) -> key the consumer reads first when both are present.
_SHADOWED_BY: dict[tuple[str, str], str] = {
    ("sor_filter", "std_ratio"): "stddev_mul_thresh",
}

_POSITION_NOTES: dict[str, str] = {
    "voxel_count": (
        "Runs after all other operations on the final point cloud, whatever its "
        "position in the list. If several voxel entries are enabled, the last one is used."
    ),
}

ENABLED_SPEC = FormFieldSpec(
    name="enabled", form_key=OP_FORM_PREFIX + "enabled", label="Enabled",
    description="When No, the pipeline skips this operation.",
    kind=ValueKind.BOOL, required=True, default=True, has_default=True,
)

_RANK = {name: index for index, name in enumerate(POINTCLOUD_OP_ORDER)}


def op_name(op: Any) -> str:
    """Same key priority as apply_pointcloud_ops's dispatch ("op" before
    "name"), via config_service's existing helper."""
    return _op_name(op) if isinstance(op, dict) else ""


def is_recognized(op: Any) -> bool:
    return isinstance(op, dict) and op_name(op) in POINTCLOUD_OP_METADATA


def _param_spec(name: str, param) -> FormFieldSpec:
    kind, nullable = PARAM_TYPES[(name, param.name)]
    return FormFieldSpec(
        name=param.name,
        form_key=OP_FORM_PREFIX + param.name,
        label=param.label,
        description=param.description,
        kind=kind,
        required=not nullable,
        default=param.default,
        has_default=(name, param.name) not in _NO_PREFILL,
        choices=param.choices,
        note=_NO_PREFILL.get((name, param.name)),
    )


def param_specs(name: str) -> tuple[FormFieldSpec, ...]:
    return tuple(_param_spec(name, p) for p in POINTCLOUD_OP_METADATA[name].parameters)


def shadowing_note(op: Mapping[str, Any], param: str) -> str | None:
    shadow = _SHADOWED_BY.get((op_name(op), param))
    if shadow is None or shadow not in op:
        return None
    return (
        f"Not editable here: this entry also sets {shadow} ({op[shadow]!r}), "
        f"which the pipeline reads instead of {param}."
    )


def editable_specs(op: Any) -> tuple[FormFieldSpec, ...]:
    if not is_recognized(op):
        return ()
    specs = [s for s in param_specs(op_name(op)) if shadowing_note(op, s.name) is None]
    return (ENABLED_SPEC, *specs)


def op_param_state(op: Mapping[str, Any], spec: FormFieldSpec) -> FieldState:
    return FieldState(spec.name in op, op.get(spec.name))


def extra_keys(op: Mapping[str, Any]) -> dict[str, Any]:
    """Keys this editor does not edit; always preserved as they are."""
    known = {"op", "name", "enabled"}
    if is_recognized(op):
        known |= {p.name for p in POINTCLOUD_OP_METADATA[op_name(op)].parameters}
    return {k: v for k, v in op.items() if k not in known}


def position_note(name: str) -> str | None:
    return _POSITION_NOTES.get(name)


def _choice_error(spec: FormFieldSpec, value: Any) -> str | None:
    """parse_value() checks choices for text values; an int parameter with
    string choices (clump_connectivity) is checked here."""
    if spec.choices and spec.kind is ValueKind.INT and value is not None and str(value) not in spec.choices:
        return f"{spec.label} must be one of: {', '.join(spec.choices)} (got {value!r})."
    return None


# --- Adding -----------------------------------------------------------------

def new_op_prefill(name: str) -> list[tuple[FormFieldSpec, str]]:
    """Initial form values for adding `name`: enabled, then every metadata
    parameter at its metadata default (blank where _NO_PREFILL applies)."""
    rows = [(ENABLED_SPEC, "true")]
    for spec in param_specs(name):
        rows.append((spec, format_form_value(spec.default) if spec.has_default else ""))
    return rows


def build_new_op(name: str, form: Mapping[str, str]) -> tuple[dict[str, Any] | None, tuple[ValidationError, ...]]:
    """A complete new entry with every parameter written explicitly, or
    (None, errors). Raises KeyError for an unrecognized operation name."""
    POINTCLOUD_OP_METADATA[name]  # KeyError for unknown names
    op: dict[str, Any] = {"op": name}
    errors: list[ValidationError] = []
    for spec in (ENABLED_SPEC, *param_specs(name)):
        raw = form.get(spec.form_key, "")
        if not raw.strip():
            if spec.required:
                errors.append(ValidationError(spec.name, f"{spec.label} is required."))
            else:
                op[spec.name] = None
            continue
        value, error = parse_value(spec, raw)
        error = error or _choice_error(spec, value)
        if error:
            errors.append(ValidationError(spec.name, error))
        else:
            op[spec.name] = value
    return (None, tuple(errors)) if errors else (op, ())


def insert_position(ops: list[Any], name: str) -> int:
    """Before the first recognized entry that comes later in
    POINTCLOUD_OP_ORDER; at the end if there is none. Unrecognized entries
    keep their places."""
    rank = _RANK[name]
    for index, op in enumerate(ops):
        if is_recognized(op) and _RANK.get(op_name(op), -1) > rank:
            return index
    return len(ops)


def _ops_list(document: ExperimentConfigDocument) -> list[Any]:
    ops = document.analysis.get("pointcloud_ops")
    if ops is None:
        return []
    if not isinstance(ops, list):
        raise ValueError("pointcloud_ops in this file is not a list, so it cannot be edited here.")
    return ops


def add_op(document: ExperimentConfigDocument, op: dict[str, Any]) -> int:
    ops = list(_ops_list(document))
    index = insert_position(ops, op_name(op))
    ops.insert(index, op)
    document.analysis["pointcloud_ops"] = ops
    return index


# --- Editing and removing -------------------------------------------------------

def apply_op_form(op: Mapping[str, Any], form: Mapping[str, str]) -> tuple[dict[str, Any] | None, tuple[ValidationError, ...]]:
    """A copy of `op` with submitted changes applied, or (None, errors).
    Keys not edited here are carried over untouched; `op` is not mutated."""
    updated = dict(op)
    errors: list[ValidationError] = []
    for spec in editable_specs(op):
        if spec.form_key not in form:
            continue
        changed, value, error = resolve_submitted(spec, op_param_state(op, spec), form[spec.form_key])
        error = error or (_choice_error(spec, value) if changed else None)
        if error:
            errors.append(ValidationError(spec.name, error))
        elif changed:
            updated[spec.name] = value
    return (None, tuple(errors)) if errors else (updated, ())


def get_op(document: ExperimentConfigDocument, index: int) -> Any:
    ops = _ops_list(document)
    if not 0 <= index < len(ops):
        raise IndexError(index)
    return ops[index]


def replace_op(document: ExperimentConfigDocument, index: int, op: dict[str, Any]) -> None:
    ops = list(_ops_list(document))
    ops[index] = op
    document.analysis["pointcloud_ops"] = ops


def remove_op(document: ExperimentConfigDocument, index: int) -> Any:
    ops = list(_ops_list(document))
    removed = ops.pop(index)
    document.analysis["pointcloud_ops"] = ops
    return removed
