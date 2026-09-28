"""The complete experiment_config.yaml document -- outer metadata plus the
analysis section P1B (config_service.py) already handles.

P1B understands `analysis:` in isolation. This module understands the
whole real file:

    experiment_name: MeadowFescue_2026
    config_note: ...
    config_reviewed: false
    processing: {parallel_scans: null}
    processing_mode: off
    raw_data_path: ...
    output_path: ...
    sharing: {enabled: false}
    notifications: {enabled: false}
    analysis:
        ...

Deliberately does not duplicate any P1B translation/validation logic --
every analysis-section concern (aliasing, nested marks/ray_box, LOCKED
enforcement, HIDDEN_SYSTEM stripping) is delegated to config_service.py
functions directly. This module's own job is exactly the outer envelope:
preserving it, validating the small piece of it the pipeline actually
reads, and the load/preview/save lifecycle around the combined document.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lidar_analysis.central_runner import resolve_parallel_scans
from lidar_analysis.webapp import config_service as analysis_service
from lidar_analysis.webapp.config_service import ValidationError, ValidationResult

# ---------------------------------------------------------------------------
# Outer schema, established by inspecting real consumption -- not inferred
# from the one example experiment_config.yaml alone. Confirmed by grep
# across the whole repository, not assumed:
#
#   experiment_name  -- read nowhere. The real experiment identity always
#       comes from the required --experiment CLI argument
#       (central_runner.py's own argparse setup); this key is documentary.
#   config_note       -- read nowhere. Free-text human documentation.
#   config_reviewed   -- read nowhere. A human sign-off marker.
#   processing        -- read by central_runner.resolve_parallel_scans,
#       which IS called from the live scan-processing loop
#       (run_experiment_date). Genuinely functional.
#   processing_mode   -- read only by orchestrator.py, which the Stage 0
#       reconciliation audit already established is a single-commit,
#       zero-test, never-revisited prototype -- not the live automation
#       path (central_watcher.py is). Nominally read, effectively inert.
#   raw_data_path, output_path, sharing, notifications -- found only in
#       scaffold_experiments.py's own default_experiment_config()
#       generator; confirmed by grep to be consumed NOWHERE else in the
#       repository, including by that same module. Scaffolded, never
#       wired up.
#   analysis          -- everything config_service.py (P1B) handles.
#
# None of this is enforced as required by any pipeline code -- these are
# all optional at the code level. experiment_name is required by THIS
# module's new_document() specifically, as a UX choice (a nameless
# experiment config is not a sensible thing to hand a researcher), not a
# claim that the pipeline itself requires it.
# ---------------------------------------------------------------------------
KNOWN_OUTER_FIELDS: tuple[str, ...] = (
    "experiment_name",
    "config_note",
    "config_reviewed",
    "processing",
    "processing_mode",
    "raw_data_path",
    "output_path",
    "sharing",
    "notifications",
)
# Fixed, readable order for rendered YAML -- documentary fields first,
# functional/scaffolded fields after, analysis always last.
_RENDER_ORDER: tuple[str, ...] = KNOWN_OUTER_FIELDS + ("analysis",)


@dataclass
class ExperimentConfigDocument:
    """A complete experiment_config.yaml, in memory. Mutable: a future UI
    is expected to hold one of these and update fields incrementally as a
    researcher interacts with a form, rather than reconstructing it whole
    on every edit.

    `analysis` is the flat, UI-representation dict from
    config_service.to_ui_representation() -- one value per AnalysisConfig
    field, exactly matching config_ui_metadata.UI_METADATA's structure, so
    a form can bind to it directly without a further translation step.

    `unknown_outer_fields` holds any top-level key found on load that
    isn't in KNOWN_OUTER_FIELDS -- preserved verbatim and always re-emitted
    on render/save, never silently dropped, per the explicit "preserve and
    audit" policy (see below for why).
    """

    analysis: dict[str, Any] = field(default_factory=dict)
    experiment_name: str | None = None
    config_note: str | None = None
    config_reviewed: bool | None = None
    processing: dict[str, Any] | None = None
    processing_mode: str | None = None
    raw_data_path: str | None = None
    output_path: str | None = None
    sharing: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    unknown_outer_fields: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None  # None for a new, never-saved document


@dataclass(frozen=True)
class DocumentValidationResult:
    """Combines document-level (outer-key) errors with P1B's own analysis
    ValidationResult, keeping the two attributable separately: a
    document-level error's `field` is a top-level key name
    (e.g. "processing"); an analysis error's field is an AnalysisConfig
    field name (e.g. "mta_fit_angle_min_deg"), exactly as P1B already
    produces it."""

    valid: bool
    document_errors: tuple[ValidationError, ...]
    analysis_result: ValidationResult


def _validate_processing_block(processing: dict[str, Any] | None) -> tuple[ValidationError, ...]:
    """Reuses central_runner.resolve_parallel_scans itself -- the pipeline's
    own real check for this block -- rather than reimplementing its
    "must be a mapping" / "parallel_scans must be null or a positive
    integer" rules a second time."""
    if processing is None:
        return ()
    try:
        resolve_parallel_scans({"processing": processing})
        return ()
    except Exception as exc:  # noqa: BLE001 -- resolve_parallel_scans raises ValueError today
        return (ValidationError(field="processing", message=str(exc)),)


def load_document(path: Path) -> ExperimentConfigDocument:
    """Load a full experiment_config.yaml. Opening a file never modifies
    it -- this only reads."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    known = {k: raw.get(k) for k in KNOWN_OUTER_FIELDS if k in raw}
    unknown = {k: v for k, v in raw.items() if k not in KNOWN_OUTER_FIELDS and k != "analysis"}

    return ExperimentConfigDocument(
        analysis=analysis_service.to_ui_representation(raw),
        unknown_outer_fields=unknown,
        source_path=path,
        **known,
    )


def new_document(experiment_name: str, **outer_overrides: Any) -> ExperimentConfigDocument:
    """A new document, starting from config_service's own canonical
    analysis defaults (default_analysis_yaml_dict(), via
    config_service.default_config_dict() -- not a second, invented default
    schema) plus document-level defaults taken directly from
    scaffold_experiments.py's own default_experiment_config() generator,
    the one real precedent for what a fresh document's outer fields should
    contain.

    experiment_name is required here as a keyword/positional argument, not
    because build_config or any pipeline validator requires it (confirmed
    in the schema audit: it's read nowhere), but because this module
    should not guess a name for a researcher's new experiment.
    """
    if not experiment_name or not str(experiment_name).strip():
        raise ValueError("new_document() requires a non-empty experiment_name")

    defaults: dict[str, Any] = {
        "config_note": "Template only. Edit this config before enabling processing.",
        "config_reviewed": False,
        "processing": {"parallel_scans": None},
        "processing_mode": "off",
        "sharing": {"enabled": False},
        "notifications": {"enabled": False},
        # raw_data_path/output_path deliberately omitted: scaffold_experiments.py
        # fills these from the experiment name and a fixed cart-city root path
        # that has no meaning outside that specific scaffolding tool; no
        # equivalent default exists for a document created through this
        # service. Left unset (None) rather than fabricated.
    }
    defaults.update(outer_overrides)

    return ExperimentConfigDocument(
        analysis=analysis_service.to_ui_representation(analysis_service.default_config_dict()),
        experiment_name=str(experiment_name),
        unknown_outer_fields={},
        source_path=None,
        **defaults,
    )


def validate_document(document: ExperimentConfigDocument) -> DocumentValidationResult:
    """document-level structural validation + config_service (P1B)
    validation of the analysis section, which itself calls the real
    build_config(). Document-level errors are checked independently of
    whether the analysis section is valid -- both sets of errors are
    always reported together, not short-circuited."""
    document_errors = _validate_processing_block(document.processing)
    analysis_result = analysis_service.validate(document.analysis)
    return DocumentValidationResult(
        valid=(not document_errors) and analysis_result.valid,
        document_errors=document_errors,
        analysis_result=analysis_result,
    )


def render_document_yaml(document: ExperimentConfigDocument) -> str:
    """Pure -- no filesystem effects. Produces canonical YAML text for the
    complete document: known outer fields (only those actually set, in a
    fixed readable order), any preserved unknown outer fields, and the
    analysis section nested under `analysis:` exactly as the real pipeline
    expects (config_service.from_ui_representation() is called here, which
    already enforces LOCKED fields and strips HIDDEN_SYSTEM fields -- this
    function does not duplicate either guarantee, it inherits them).

    Raises config_service.LockedFieldViolation if the document's analysis
    section conflicts with a LOCKED field -- same as calling
    config_service.export_yaml_text() directly would.
    """
    combined: dict[str, Any] = {}
    for key in KNOWN_OUTER_FIELDS:
        value = getattr(document, key)
        if value is not None:
            combined[key] = value
    combined.update(document.unknown_outer_fields)
    combined["analysis"] = analysis_service.from_ui_representation(document.analysis)

    # Preserve the fixed, readable ordering where possible; unknown fields
    # (not in _RENDER_ORDER) are appended after, in their existing order.
    ordered = {k: combined[k] for k in _RENDER_ORDER if k in combined}
    ordered.update({k: v for k, v in combined.items() if k not in ordered})
    return yaml.safe_dump(ordered, sort_keys=False)


def save_document(document: ExperimentConfigDocument, path: Path, *, overwrite: bool = False) -> Path:
    """Explicit save only -- render_document_yaml() has no filesystem
    effects on its own, and loading a document never writes anything back
    to the path it came from merely by having been opened.

    Refuses to overwrite an existing file unless overwrite=True is passed
    explicitly -- the default is safe. Writes via a temp file in the same
    directory followed by an atomic os.replace(), so a serialization or
    disk-write failure never leaves a partially-written experiment config
    at the destination path. No existing single-file atomic-write
    precedent was found elsewhere in this repository (research_delivery.py
    has a directory-staging pattern for a whole build, not a single-file
    one) -- this is the standard temp-file-then-atomic-replace pattern,
    not a repository convention being reused.

    Sets document.source_path to `path` on success.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists; pass overwrite=True to replace it explicitly."
        )

    text = render_document_yaml(document)  # may raise LockedFieldViolation; nothing written yet if so

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    document.source_path = path
    return path
