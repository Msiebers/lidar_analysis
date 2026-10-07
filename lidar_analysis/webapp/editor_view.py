"""View models for the editor page (Web-P1D).

Turns the open document plus form_handling's field specs into plain
objects the editor template renders without logic of its own: which
control each field gets, the options it offers, the value it shows, and
any error or note beside it.

Grouping comes from config_ui_metadata only: one section per
FieldMetadata.section (in registration order), and within a section the
BASIC / ADVANCED / EXPERT / LOCKED tiers.

A field absent from the document is rendered blank with a "Not set in
this file" hint -- never pre-filled with the dataclass default -- so that
an unchanged submission leaves it absent (see form_handling).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import yaml

from lidar_analysis.webapp import form_handling as fh
from lidar_analysis.webapp.config_ui_metadata import Tier
from lidar_analysis.webapp.experiment_document import KNOWN_OUTER_FIELDS, ExperimentConfigDocument

_OUTER_EDITED = {"experiment_name", "config_note", "config_reviewed"}


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    selected: bool


@dataclass(frozen=True)
class FieldView:
    spec: fh.FormFieldSpec
    dom_id: str
    control: str  # "select" | "text" | "locked"
    value: str = ""
    options: tuple[Option, ...] = ()
    placeholder: str = ""
    error: str | None = None
    note: str | None = None
    locked_display: str = ""
    locked_conflict: bool = False


@dataclass
class SectionView:
    title: str
    basic: list[FieldView] = field(default_factory=list)
    advanced: list[FieldView] = field(default_factory=list)
    expert: list[FieldView] = field(default_factory=list)
    locked: list[FieldView] = field(default_factory=list)

    @property
    def advanced_has_error(self) -> bool:
        return any(f.error for f in self.advanced)

    @property
    def expert_has_error(self) -> bool:
        return any(f.error for f in self.expert)


@dataclass(frozen=True)
class ReadOnlyItem:
    label: str
    value: str
    note: str


def _dom_id(form_key: str) -> str:
    return "f-" + form_key.replace(".", "-")


def error_anchor(field_name: str | None) -> str | None:
    """The DOM id of the input an error belongs to, for in-page links."""
    if field_name is None:
        return None
    for spec in fh.outer_field_specs():
        if spec.name == field_name:
            return _dom_id(spec.form_key)
    return _dom_id(fh.ANALYSIS_PREFIX + field_name)


def _default_text(spec: fh.FormFieldSpec) -> str:
    if not spec.has_default:
        return ""
    return fh.format_form_value(spec.default) or "null"


def _blank_label(spec: fh.FormFieldSpec, state: fh.FieldState, *, outer: bool) -> str | None:
    """Label for the empty option of a select, or None if it has none."""
    if not state.present:
        if outer:
            return "Not set in this file"
        default = _default_text(spec)
        return f"Not set in this file (pipeline default: {default})" if default else "Not set in this file"
    if state.value is None or not spec.required:
        return "Not set in this file" if outer else "No value (null)"
    return None


def _field_view(
    spec: fh.FormFieldSpec,
    state: fh.FieldState,
    submitted: Mapping[str, str],
    error: str | None,
    *,
    outer: bool = False,
) -> FieldView:
    shown = submitted[spec.form_key] if spec.form_key in submitted else (
        fh.format_form_value(state.value) if state.present else ""
    )
    common = dict(spec=spec, dom_id=_dom_id(spec.form_key), error=error, note=spec.note)

    if spec.kind is fh.ValueKind.BOOL or spec.choices:
        if spec.kind is fh.ValueKind.BOOL:
            pairs = [("true", "Yes"), ("false", "No")]
        else:
            pairs = [(c, c) for c in spec.choices]
            if state.present and isinstance(state.value, str) and state.value not in spec.choices:
                pairs.append((state.value, f"{state.value} (value from file, not a known choice)"))
        blank = _blank_label(spec, state, outer=outer)
        if blank is not None:
            pairs.insert(0, ("", blank))
        if shown not in {value for value, _ in pairs}:
            pairs.append((shown, f"{shown} (submitted value)"))
        options = tuple(Option(value, label, value == shown) for value, label in pairs)
        return FieldView(control="select", options=options, **common)

    if not state.present:
        default = _default_text(spec)
        placeholder = f"Not set in this file (pipeline default: {default})" if default else "Not set in this file"
    elif state.value is None:
        placeholder = "No value (null)"
    else:
        placeholder = ""
    return FieldView(control="text", value=shown, placeholder=placeholder, **common)


def _locked_view(spec: fh.FormFieldSpec, analysis: Mapping[str, Any]) -> FieldView:
    locked_value = spec.metadata.locked_value
    if spec.name in analysis:
        value = analysis[spec.name]
        conflict = value != locked_value
        display = fh.format_form_value(value)
    else:
        conflict = False
        display = f"{fh.format_form_value(locked_value)} (not in this file; written on save)"
    return FieldView(
        spec=spec, dom_id=_dom_id(spec.form_key), control="locked",
        locked_display=display, locked_conflict=conflict,
        error=(
            f"This file sets {spec.label} to {fh.format_form_value(analysis.get(spec.name))!r}, "
            f"but it is locked to {fh.format_form_value(locked_value)!r}. The file cannot be "
            "previewed or saved until it is reset."
        ) if conflict else None,
    )


def build_sections(
    document: ExperimentConfigDocument,
    submitted: Mapping[str, str],
    errors: Mapping[str, str],
) -> list[SectionView]:
    sections: dict[str, SectionView] = {}
    for spec in fh.analysis_field_specs():
        meta = spec.metadata
        section = sections.setdefault(meta.section, SectionView(title=meta.section))
        if spec.read_only:
            section.locked.append(_locked_view(spec, document.analysis))
            continue
        view = _field_view(spec, fh.analysis_field_state(document.analysis, spec), submitted, errors.get(spec.name))
        {Tier.BASIC: section.basic, Tier.ADVANCED: section.advanced, Tier.EXPERT: section.expert}[meta.tier].append(view)
    return list(sections.values())


def build_outer_fields(
    document: ExperimentConfigDocument,
    submitted: Mapping[str, str],
    errors: Mapping[str, str],
) -> list[FieldView]:
    return [
        _field_view(spec, fh.outer_field_state(document, spec), submitted, errors.get(spec.name), outer=True)
        for spec in fh.outer_field_specs()
    ]


def _yaml_text(value: Any) -> str:
    return yaml.safe_dump(value, default_flow_style=True, sort_keys=False).strip().removesuffix("...").strip()


def build_read_only_items(document: ExperimentConfigDocument) -> list[ReadOnlyItem]:
    """Settings present in the document that this editor shows but does not
    edit. All are preserved unchanged on save."""
    items: list[ReadOnlyItem] = []
    for key in KNOWN_OUTER_FIELDS:
        if key in _OUTER_EDITED or key == "processing":
            continue
        value = getattr(document, key)
        if value is not None:
            items.append(ReadOnlyItem(key, _yaml_text(value), "Not read by the live pipeline; kept as is."))
    if isinstance(document.processing, dict):
        extra = {k: v for k, v in document.processing.items() if k != "parallel_scans"}
        if extra:
            items.append(ReadOnlyItem("processing (other keys)", _yaml_text(extra), "Kept as is."))
    for key, value in document.unknown_outer_fields.items():
        items.append(ReadOnlyItem(key, _yaml_text(value), "Not a recognized top-level key; kept as is."))
    if document.analysis.get("pcl_backend") is not None:
        items.append(ReadOnlyItem("pcl_backend", _yaml_text(document.analysis["pcl_backend"]), "Kept as is."))
    return items
