"""Pure introspection of AnalysisConfig -- the web app's schema layer.

AnalysisConfig (lidar_analysis/config.py) remains the single, authoritative
source of truth for field existence, type, and default. This module never
duplicates that information by hand -- it reads it directly from
dataclasses.fields(AnalysisConfig) at call time, so a field added, removed,
or retyped in config.py is reflected here automatically, with no separate
list to keep in sync.

config.py does not use `from __future__ import annotations`, so
dataclasses.fields()[i].type is a real type object here, not a deferred
string -- confirmed by inspection before writing this module. That means
typing.get_origin()/get_args() can be used directly below without needing
typing.get_type_hints() resolution or any string-eval workaround.

This module knows nothing about researcher-facing labels, grouping, or
BASIC/ADVANCED/EXPERT/LOCKED/HIDDEN_SYSTEM tiers -- that presentation layer
is config_ui_metadata.py, kept deliberately separate so AnalysisConfig can
change shape without this module's authority over "what fields actually
exist" ever being in question, and so the presentation layer can be reviewed
and edited by a human without touching introspection logic.

Nothing here writes YAML, calls build_config, or executes any pipeline code.
That translation/validation layer is Web-P1B's config_service.py, not this
module -- see the module docstring in lidar_analysis/webapp/__init__.py for
the phase boundary.
"""
from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lidar_analysis.config import AnalysisConfig

_MISSING = dataclasses.MISSING
_UNION_ORIGINS = (typing.Union, types.UnionType)


@dataclass(frozen=True)
class FieldTypeInfo:
    """A structured, UI-agnostic description of one field's Python type.

    raw: the exact type object from the dataclass annotation, unmodified --
        e.g. `str | None`, `list[dict] | None`, `List[Path]`.
    is_optional: True if the field's type is `X | None` (or an equivalent
        `typing.Optional[X]` / `typing.Union[X, None]` form). No other kind
        of multi-type union currently exists in AnalysisConfig; if one is
        ever added, is_optional stays False and `inner` falls back to `raw`
        unchanged, rather than guessing which member matters.
    inner: for an optional field, the non-None member of the union (e.g.
        `str` for `str | None`, `list[dict]` for `list[dict] | None`).
        Equal to `raw` when the field is not optional.
    origin: typing.get_origin(inner) -- e.g. `list` for `list[dict]`, `dict`
        for `dict`, or None for a plain scalar type like `str` or `Path`.
    args: typing.get_args(inner) -- e.g. `(dict,)` for `list[dict]`.
    is_list: True if `origin` is `list`.
    is_dict: True if `origin` is `dict`.
    is_path: True if `inner` is pathlib.Path, or a list of pathlib.Path.
    is_bool: True if `inner` is bool -- checked explicitly since bool is a
        subclass of int in Python and callers must not confuse the two.
    """

    raw: Any
    is_optional: bool
    inner: Any
    origin: Any
    args: tuple
    is_list: bool
    is_dict: bool
    is_path: bool
    is_bool: bool


@dataclass(frozen=True)
class ConfigFieldSchema:
    """One AnalysisConfig field, exactly as the dataclass declares it.

    has_default / has_default_factory distinguish "no default at all"
    (data_dirs, calibration_dir, cart_id -- must come from outside the YAML
    entirely) from "defaults to this value" and from "defaults via a factory
    callable" (none currently exist in AnalysisConfig, but represented so
    one could be added without this schema silently mishandling it).
    """

    name: str
    type_info: FieldTypeInfo
    has_default: bool
    default: Any
    has_default_factory: bool
    default_factory: Any


def _classify_type(annotation: Any) -> FieldTypeInfo:
    origin = typing.get_origin(annotation)
    is_optional = False
    inner = annotation

    if origin in _UNION_ORIGINS:
        args = typing.get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and len(non_none) == 1:
            is_optional = True
            inner = non_none[0]
        # else: a union that isn't simply "X or None". None exist today;
        # `inner` stays as the full annotation rather than guessing.

    inner_origin = typing.get_origin(inner)
    inner_args = typing.get_args(inner)
    # A bare, unparameterized `dict` or `list` annotation (e.g. `dict | None`,
    # as opposed to `dict[str, int]` or `list[dict]`) is not a generic alias
    # at all -- typing.get_origin() returns None for it, not `dict`/`list`.
    # Both forms must count: check the origin (parameterized case) and the
    # type itself (bare case).
    is_list = inner_origin is list or inner is list
    is_dict = inner_origin is dict or inner is dict
    is_path = inner is Path or (is_list and inner_args[:1] == (Path,))
    is_bool = inner is bool

    return FieldTypeInfo(
        raw=annotation,
        is_optional=is_optional,
        inner=inner,
        origin=inner_origin,
        args=inner_args,
        is_list=is_list,
        is_dict=is_dict,
        is_path=is_path,
        is_bool=is_bool,
    )


def introspect_analysis_config_fields() -> tuple[ConfigFieldSchema, ...]:
    """The live, authoritative field list for AnalysisConfig, freshly read.

    Returns fields in the same order dataclasses.fields() reports them
    (declaration order in config.py) -- callers that want a stable sort for
    display should sort explicitly; this function makes no ordering promise
    beyond "whatever the dataclass currently declares."
    """
    schemas = []
    for field in dataclasses.fields(AnalysisConfig):
        has_default = field.default is not _MISSING
        has_default_factory = field.default_factory is not _MISSING
        schemas.append(
            ConfigFieldSchema(
                name=field.name,
                type_info=_classify_type(field.type),
                has_default=has_default,
                default=field.default if has_default else None,
                has_default_factory=has_default_factory,
                default_factory=field.default_factory if has_default_factory else None,
            )
        )
    return tuple(schemas)


def analysis_config_field_names() -> frozenset[str]:
    """Just the names, for coverage checks that don't need full type info."""
    return frozenset(f.name for f in dataclasses.fields(AnalysisConfig))
