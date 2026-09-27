"""Configuration service: the translation/validation truth layer.

This module is the *only* place a future web UI (P1C onward) talks to for
turning researcher form input into a real, pipeline-accepted
experiment_config.yaml, and for turning an existing YAML file into
something a form can display. It does not implement pipeline execution,
HTML, or a server -- see lidar_analysis/webapp/README.md for the phase
boundary.

The one rule everything here follows: **validation is never reimplemented.**
Every validity claim this module makes is produced by literally calling
central_runner.build_config() -- the same function the real pipeline uses --
never a parallel/independent check. Where this module resolves aliases or
nested YAML sections itself (to_ui_representation, below), it does so by
calling the pipeline's own real alias-resolution functions
(map_deprecated_analysis_keys, resolve_splitting_style, resolve_buffer_u),
not by re-deriving that logic a second time. This is deliberate: two
implementations of the same resolution logic is exactly the kind of thing
that drifts silently, which this project has already been bitten by twice.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lidar_analysis.central_runner import (
    build_config,
    extract_analysis_cfg,
    resolve_buffer_u,
    resolve_splitting_style,
)
from lidar_analysis.config import (
    AnalysisConfig,
    default_analysis_yaml_dict,
    map_deprecated_analysis_keys,
)
from lidar_analysis.webapp.config_ui_metadata import Tier, UI_METADATA

# ---------------------------------------------------------------------------
# Placeholders used only to satisfy build_config()'s signature during
# validation. Confirmed during the Phase 1 audit, re-confirmed before
# writing this module: neither build_config() nor validate_mta_config()
# touch the filesystem for cart_id/data_dir -- they're only stored on the
# resulting AnalysisConfig, never opened, checked for existence, or read.
# A researcher's real cart_id/data directory are supplied elsewhere in the
# real pipeline (cart_config.yaml, the CLI), never through
# experiment_config.yaml -- see config_ui_metadata's HIDDEN_SYSTEM entries
# for data_dirs/calibration_dir/cart_id.
_VALIDATION_CART_ID = "webapp-validation-placeholder"
_VALIDATION_DATA_DIR = Path("/nonexistent/webapp-validation-placeholder")

# HIDDEN_SYSTEM fields are never written into exported YAML -- derived
# directly from the P1A registry rather than a second, separately
# maintained list, so the two can't drift apart.
HIDDEN_SYSTEM_FIELDS: frozenset[str] = frozenset(
    name for name, meta in UI_METADATA.items() if meta.tier is Tier.HIDDEN_SYSTEM
)

# Canonical nested-vs-flat mappings, taken directly from build_config's own
# pick_ray_box()/marks_cfg handling (central_runner.py) -- not re-derived,
# transcribed from what that function actually reads.
MARKS_NESTED_FIELDS: dict[str, str] = {
    "target_type": "mark_target_type",
    "dirname": "markers_dirname",
    "missing_file": "missing_mark_file",
    "write_pointcloud": "write_marker_pointcloud",
    "write_reference_points": "write_reference_points",
    "write_window_pointcloud": "write_window_pointcloud",
    "free_marks_as": "free_marks_as",
    "empty_file": "empty_mark_file",
    "buffer_u": "mark_z_buffer_u",
}
RAY_BOX_NESTED_FIELDS: dict[str, str] = {
    "ground_mode": "ray_box_ground_mode",
    "bottom_agl_m": "ray_box_bottom_agl_m",
    "x_near_m": "ray_box_x_near_m",
    "height_percentile": "ray_box_height_percentile",
    "height_buffer_m": "ray_box_height_buffer_m",
    "grubbs_alpha": "ray_box_grubbs_alpha",
    "layer_thickness_m": "ray_box_layer_thickness_m",
    "diagnostic": "ray_box_diagnostic",
}
# YAML key -> AnalysisConfig field name, where a flat (non-nested) key
# genuinely differs from the field name it fills.
FLAT_KEY_REMAPS: dict[str, str] = {
    "generate_pointclouds": "make_point_cloud",
    "overwrite_pointclouds": "overwrite_outputs",
}
# Pointcloud-op aliases -> the canonical name this service always exports.
# apply_pointcloud_ops's own dispatch (pointcloud_ops.py) checks op_cfg["op"]
# before op_cfg["name"] -- this service writes "op" on export, accepting
# either on import, matching that same priority.
_POINTCLOUD_OP_ALIASES: dict[str, str] = {"voxel_volume": "voxel_count", "voxel_grid": "voxel_count"}


# ---------------------------------------------------------------------------
# Structured validation results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationError:
    """One validation problem, structured enough for a future UI to render
    without parsing traceback text -- deliberately not more than this yet
    (no severity levels beyond "error", no error codes) per the instruction
    not to overengineer a full frontend error system before there's a
    frontend."""

    field: str | None  # best-effort; None if the message isn't attributable to one field
    message: str


class LockedFieldViolation(ValueError):
    """Raised by from_ui_representation()/export_yaml_text()/export_yaml_file()
    when a caller attempts to set a LOCKED field to a value other than its
    enforced locked_value.

    Pre-merge audit finding: LOCKED metadata (P1A) was advisory only at
    this service boundary -- validate() correctly rejected an
    out-of-range mta_fit_angle_min_deg via build_config's own
    validate_mta_config, but export still happily wrote the bad value to
    YAML regardless, and pai_g_function/fad_g_function were not checked
    anywhere in this service at all (their enforcement lives in pai.py's/
    fad.py's own runtime code, never reached by build_config). Confirmed
    concretely before fixing: from_ui_representation({"pai_g_function":
    "something_else"}) exported that value unchanged, and validate() on
    the same input returned valid=True.

    Fixed by making LOCKED enforcement authoritative at this boundary,
    derived from UI_METADATA (no second hardcoded locked-field table):
    validate() reports a conflict as a structured, field-attributed
    ValidationError without needing build_config to be the one that
    happens to catch it; from_ui_representation() (and therefore both
    export functions, which call it) raises this exception outright on a
    conflicting value, rather than silently substituting the canonical
    value -- an explicit conflicting value most likely reflects a real
    misunderstanding worth surfacing, not something to paper over.
    Import (to_ui_representation) deliberately does NOT raise: it must
    still be possible to load and inspect an existing file that happens
    to have a bad locked value, so a researcher can see and fix it via
    validate()'s reported error, rather than the tool refusing to open
    the file at all.
    """


def _locked_field_conflicts(flat_config: dict[str, Any]) -> tuple[ValidationError, ...]:
    """Non-raising: LOCKED fields present in flat_config with a value other
    than their UI_METADATA.locked_value, as structured errors. A LOCKED
    field absent from flat_config is not a conflict -- AnalysisConfig's own
    default (already correct for all four current LOCKED fields) applies."""
    errors = []
    for name, meta in UI_METADATA.items():
        if meta.tier is not Tier.LOCKED:
            continue
        if name in flat_config and flat_config[name] != meta.locked_value:
            errors.append(
                ValidationError(
                    field=name,
                    message=(
                        f"{name} is locked to {meta.locked_value!r} and cannot be "
                        f"overridden (got {flat_config[name]!r}). {meta.description}"
                    ),
                )
            )
    return tuple(errors)


def _with_locked_fields_enforced(flat_config: dict[str, Any]) -> dict[str, Any]:
    """Raises LockedFieldViolation on any conflict (see class docstring);
    otherwise returns a copy with every LOCKED field explicitly present at
    its canonical value -- inserted if it was absent, so exported YAML is
    self-documenting about the constraint rather than silently relying on
    AnalysisConfig's own default to happen to be correct elsewhere."""
    conflicts = _locked_field_conflicts(flat_config)
    if conflicts:
        raise LockedFieldViolation("; ".join(e.message for e in conflicts))
    out = dict(flat_config)
    for name, meta in UI_METADATA.items():
        if meta.tier is Tier.LOCKED:
            out[name] = meta.locked_value
    return out


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[ValidationError, ...]
    config: AnalysisConfig | None  # the real, validated object, only when valid
    exception: Exception | None  # preserved for debugging; never shown raw to a future UI


def _attribute_error_to_field(message: str) -> str | None:
    """Best-effort only: if a known AnalysisConfig field name appears as a
    whole word in the error message, attribute the error to it. Several
    real build_config()/validate_mta_config() messages already name the
    field directly (e.g. "mta_fit_angle_min_deg"), so this works more often
    than a generic heuristic might suggest -- but it is explicitly not
    guaranteed, and callers must handle field=None."""
    field_names = {f.name for f in dataclasses.fields(AnalysisConfig)}
    words = message.replace(",", " ").replace("=", " ").split()
    for word in words:
        cleaned = word.strip("'\":.")
        if cleaned in field_names:
            return cleaned
    return None


def _canonicalize_for_build_config(analysis_cfg: dict[str, Any]) -> dict[str, Any]:
    """Reverses FLAT_KEY_REMAPS only (make_point_cloud -> generate_pointclouds,
    overwrite_outputs -> overwrite_pointclouds) so build_config's own
    pick() calls can find a value however it was supplied.

    Real, subtle asymmetry found while testing this module against the
    real template: build_config's pick("generate_pointclouds",
    "make_point_cloud", bool) does experiment_config.get("generate_pointclouds",
    ...) -- it looks ONLY for the literal YAML key, with no fallback to the
    AnalysisConfig field name. This is unlike use_imu/apply_imu and
    apply_ground_filter/use_local_ground_filter, both of which build_config
    already checks under either name natively via chained .get() calls. A
    UI-representation dict (which uses "make_point_cloud", the field name)
    would silently be ignored by build_config without this reversal --
    caught by test_roundtrip_semantic_equivalence_for_real_template before
    it shipped as a real bug.

    Deliberately does NOT touch legacy/deprecated keys (mta_lo_deg,
    apply_imu, use_local_ground_filter, splitting_style, etc.) or nested
    marks/ray_box sections: build_config already resolves all of those
    itself (map_deprecated_analysis_keys runs as build_config's own first
    step; pick_ray_box/marks_cfg already accept flat or nested with a
    native fallback). Reversing those here first, before build_config gets
    the chance to translate them itself, would risk silently dropping a
    legacy value instead -- a real risk checked and deliberately avoided,
    not just an unconsidered edge case.
    """
    cfg = dict(analysis_cfg)
    for yaml_key, field_name in FLAT_KEY_REMAPS.items():
        if field_name in cfg and yaml_key not in cfg:
            cfg[yaml_key] = cfg.pop(field_name)
    return cfg


def validate(experiment_config: dict[str, Any]) -> ValidationResult:
    """The one and only validation authority: calls the real
    central_runner.build_config() and reports success/failure from its
    actual behavior. Never reimplements any of build_config's or
    validate_mta_config's checks.

    Accepts either a full experiment_config.yaml structure (with the
    settings nested under an `analysis:` key, alongside sibling metadata
    like experiment_name/processing_mode) or a bare analysis-only dict --
    extract_analysis_cfg() (central_runner.py's own real unwrapping
    function, the same one run_experiment_date() itself calls) is applied
    defensively first, so a caller can never accidentally validate against
    the wrong (outer, wrapper) dict and get a misleading "valid" result
    built entirely from defaults. This exact failure mode was caught while
    testing this module against the real template config, before it became
    a real bug: build_config() silently accepted the full wrapped file and
    validated as True purely on defaults, having found none of the actual
    configured values.

    Also applies _canonicalize_for_build_config() (see above) so a
    UI-representation dict validates identically to the raw YAML it came
    from -- also caught by testing before shipping, not assumed correct.
    """
    analysis_cfg = extract_analysis_cfg(dict(experiment_config))
    analysis_cfg = _canonicalize_for_build_config(analysis_cfg)

    locked_conflicts = _locked_field_conflicts(analysis_cfg)
    if locked_conflicts:
        # Checked before build_config is even called: a LOCKED-field
        # conflict is rejected by this service's own contract, not left
        # dependent on whether the downstream pipeline module happens to
        # catch it (pai_g_function/fad_g_function currently are not
        # checked by build_config at all -- only by pai.py/fad.py at
        # runtime, far past where this service could report it cleanly).
        return ValidationResult(valid=False, errors=locked_conflicts, config=None, exception=None)

    try:
        config = build_config(
            dict(analysis_cfg),
            force=False,
            cart_id=_VALIDATION_CART_ID,
            data_dir=_VALIDATION_DATA_DIR,
        )
        return ValidationResult(valid=True, errors=(), config=config, exception=None)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: build_config
        # can raise ValueError, TypeError, or others depending on which
        # check fails; all must be caught and reported, not just ValueError.
        message = str(exc)
        error = ValidationError(field=_attribute_error_to_field(message), message=message)
        return ValidationResult(valid=False, errors=(error,), config=None, exception=exc)


# ---------------------------------------------------------------------------
# Load / default / export
# ---------------------------------------------------------------------------

def load_yaml_file(path: Path) -> dict[str, Any]:
    """Read a YAML file into a raw dict. Uses plain PyYAML (`import yaml`),
    matching central_runner.py's and research_delivery.py's own convention
    -- not lidar_analysis.yaml_loader, which is a fallback for environments
    without PyYAML installed, used by a different subset of modules."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def extract_analysis_section(full_or_bare_config: dict[str, Any]) -> dict[str, Any]:
    """Thin, documented re-export of central_runner.extract_analysis_cfg --
    the real pipeline's own function for unwrapping a full
    experiment_config.yaml's `analysis:` section (falling through to the
    dict unchanged if it's already a bare analysis dict, or has no
    non-empty `analysis:` key). Exposed here so future UI code never needs
    to reach into central_runner directly for this."""
    return extract_analysis_cfg(dict(full_or_bare_config))


def default_config_dict() -> dict[str, Any]:
    """The canonical starting point for a new configuration. Reuses
    config.py's own default_analysis_yaml_dict() rather than inventing a
    second default schema -- that function already knows which fields
    should not appear in a fresh researcher-facing config (the deprecated
    shims, the legacy MTA aliases, cart_id/data_dirs/calibration_dir) and
    already performs the generate_pointclouds/overwrite_pointclouds and
    apply_imu/use_imu renames build_config itself expects on the way back
    in."""
    return default_analysis_yaml_dict()


def to_ui_representation(experiment_config: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw (possibly nested, possibly legacy-keyed) experiment
    config dict into one value per AnalysisConfig field name -- matching
    config_ui_metadata.UI_METADATA's structure directly, one entry per
    field, so a future form can bind to it without its own translation
    layer.

    Accepts either a full experiment_config.yaml (analysis settings nested
    under `analysis:`) or a bare analysis-only dict -- extract_analysis_cfg()
    is applied first, defensively, same as in validate() above.

    Resolves legacy/deprecated keys and nested marks:/ray_box: sections by
    calling the pipeline's own real resolution functions
    (map_deprecated_analysis_keys, resolve_splitting_style,
    resolve_buffer_u) -- the exact same functions build_config() itself
    calls -- so this can never silently diverge from what build_config
    would actually do with the same input.
    """
    cfg = map_deprecated_analysis_keys(extract_analysis_cfg(dict(experiment_config)))

    split_source, mark_target_type = resolve_splitting_style(cfg)
    buffer_u = resolve_buffer_u(cfg)

    marks_cfg = cfg.get("marks", {}) or {}
    ray_box_cfg = cfg.get("ray_box", {}) or {}

    flat: dict[str, Any] = {k: v for k, v in cfg.items() if k not in ("marks", "ray_box", "splitting_style")}

    flat["split_source"] = split_source
    flat["mark_target_type"] = mark_target_type
    flat["mark_z_buffer_u"] = buffer_u

    for nested_key, field_name in MARKS_NESTED_FIELDS.items():
        if nested_key in marks_cfg:
            flat[field_name] = marks_cfg[nested_key]
    for nested_key, field_name in RAY_BOX_NESTED_FIELDS.items():
        if nested_key in ray_box_cfg:
            flat[field_name] = ray_box_cfg[nested_key]

    for yaml_key, field_name in FLAT_KEY_REMAPS.items():
        if yaml_key in flat:
            flat[field_name] = flat.pop(yaml_key)

    # use_imu/apply_imu and apply_ground_filter/use_local_ground_filter are
    # each two names for one underlying setting -- build_config treats
    # either as authoritative; the UI representation exposes one value
    # under the current preferred name.
    if "apply_imu" in flat:
        flat.setdefault("use_imu", flat.pop("apply_imu"))
    ground_value = flat.get("apply_ground_filter", flat.get("use_local_ground_filter"))
    if ground_value is not None:
        flat["apply_ground_filter"] = bool(ground_value)
        flat["use_local_ground_filter"] = bool(ground_value)

    if flat.get("pointcloud_ops"):
        flat["pointcloud_ops"] = [_normalize_op_name(op) for op in flat["pointcloud_ops"]]

    return flat


def from_ui_representation(flat_config: dict[str, Any]) -> dict[str, Any]:
    """The reverse of to_ui_representation: produce canonical, nested YAML
    from a flat field-name-keyed dict -- always writing the CURRENT
    preferred key names and structure. Deprecated aliases are never
    (re-)written; HIDDEN_SYSTEM fields are never written at all, since
    they either aren't real YAML settings (data_dirs, cart_id,
    reprocess_scans) or must never appear in new configs
    (the deprecated shims, per config.py's own comment).

    Exact byte preservation of an imported file is not attempted -- the
    Phase 1 audit confirmed the pipeline's own YAML handling never
    preserves comments or formatting either, so canonicalizing here loses
    nothing the pipeline itself cares about.

    Raises LockedFieldViolation if flat_config sets a LOCKED field
    (mta_fit_angle_min/max_deg, pai_g_function, fad_g_function) to a value
    other than its enforced constant -- see that exception's docstring for
    why this is checked here, not left to validate()/build_config alone.
    """
    flat_config = _with_locked_fields_enforced(flat_config)
    out = {k: v for k, v in flat_config.items() if k not in HIDDEN_SYSTEM_FIELDS}

    marks_cfg: dict[str, Any] = {}
    for nested_key, field_name in MARKS_NESTED_FIELDS.items():
        if field_name in out:
            marks_cfg[nested_key] = out.pop(field_name)
    if marks_cfg:
        out["marks"] = marks_cfg

    ray_box_cfg: dict[str, Any] = {}
    for nested_key, field_name in RAY_BOX_NESTED_FIELDS.items():
        if field_name in out:
            ray_box_cfg[nested_key] = out.pop(field_name)
    if ray_box_cfg:
        out["ray_box"] = ray_box_cfg

    for yaml_key, field_name in FLAT_KEY_REMAPS.items():
        if field_name in out:
            out[yaml_key] = out.pop(field_name)

    if out.get("pointcloud_ops"):
        out["pointcloud_ops"] = [_canonicalize_op(op) for op in out["pointcloud_ops"]]

    return out


def _op_name(op_cfg: dict[str, Any]) -> str:
    """Same key priority as apply_pointcloud_ops's real dispatch
    (pointcloud_ops.py): op_cfg.get("op", op_cfg.get("name", "")). Note:
    a different helper in that same file (_pointcloud_op_enabled) checks
    "name" before "op" -- a real, minor inconsistency in the pipeline
    itself, found while writing this module. This service matches the
    actual execution dispatch's priority, not the other helper's, since
    dispatch is what determines real behavior."""
    return str(op_cfg.get("op", op_cfg.get("name", ""))).strip().lower()


def _normalize_op_name(op_cfg: dict[str, Any]) -> dict[str, Any]:
    """Used on import (to_ui_representation): resolve an op's name to its
    canonical form without changing which key ("op" vs "name") the entry
    used, so importing doesn't rewrite structure a researcher didn't ask
    to change."""
    op_cfg = dict(op_cfg)
    name = _op_name(op_cfg)
    canonical = _POINTCLOUD_OP_ALIASES.get(name, name)
    if "op" in op_cfg:
        op_cfg["op"] = canonical
    elif "name" in op_cfg:
        op_cfg["name"] = canonical
    return op_cfg


def _canonicalize_op(op_cfg: dict[str, Any]) -> dict[str, Any]:
    """Used on export (from_ui_representation): always write the canonical
    name under the canonical key ("op"), regardless of which key/alias the
    UI representation happened to carry -- the audit's explicit
    instruction that aliases must never be the preferred exported form."""
    op_cfg = dict(op_cfg)
    name = _op_name(op_cfg)
    canonical = _POINTCLOUD_OP_ALIASES.get(name, name)
    op_cfg.pop("name", None)
    op_cfg["op"] = canonical
    return op_cfg


def export_yaml_text(experiment_config: dict[str, Any]) -> str:
    """Canonical dict -> YAML text. Semantic preservation only -- comments
    and key order from an imported file are not preserved, matching the
    pipeline's own yaml.safe_load-based handling everywhere else.

    Scope note: this exports the analysis-settings surface only (the
    `analysis:` section's content, unwrapped) -- matching exactly what
    build_config() itself consumes. A real experiment_config.yaml file can
    carry sibling top-level keys outside `analysis:` (experiment_name,
    config_note, config_reviewed, processing, processing_mode were found
    in the real template during this milestone) that this service does not
    yet read, preserve, or re-emit. Round-tripping those is a P1C concern,
    not addressed here -- see the P1B handoff.
    """
    return yaml.safe_dump(from_ui_representation(experiment_config), sort_keys=False)


def export_yaml_file(experiment_config: dict[str, Any], path: Path) -> None:
    """Writes to `path` unconditionally -- callers decide whether that path
    is safe to write to (e.g. a fresh export destination vs. the file that
    was originally imported). This function does not check whether `path`
    already exists or came from an import; per the P1B filesystem-safety
    requirement, that decision belongs to the caller (a future explicit
    "save" action in the UI), not this service silently overwriting an
    imported file just because export was called."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export_yaml_text(experiment_config), encoding="utf-8")
