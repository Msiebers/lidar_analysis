# lidar_analysis/webapp/ — architecture boundary (Web-P1A)

**`AnalysisConfig` (`lidar_analysis/config.py`) is authoritative.** Nothing in this package
duplicates its field list, types, or defaults by hand.

- **`config_schema.py`** — pure introspection. Reads `dataclasses.fields(AnalysisConfig)` fresh
  on every call. Owns field *existence*, *type*, and *default* only. No presentation, no YAML,
  no validation.
- **`config_ui_metadata.py`** — researcher-facing presentation metadata (label, description,
  section, BASIC/ADVANCED/EXPERT/LOCKED/HIDDEN_SYSTEM tier, control type) for every field
  `config_schema.py` reports, plus a separate, explicit schema for `pointcloud_ops` — an
  ordered nested pipeline, not a flat field, so it isn't forced into the same per-field
  registry. Every description here is sourced from something that already exists in the
  repository (the real experiment config template's own comments, docstrings, validator error
  messages) — never invented, and never a claim about whether a setting is scientifically
  better in one position over another.

**YAML translation and pipeline validation are not part of this milestone.** A researcher's
form selections becoming a real, `build_config()`-accepted `experiment_config.yaml` — including
the real YAML-key-vs-field-name remapping and legacy-alias handling documented in the Phase 1
audit — is Web-P1B's `config_service.py`, not this package as it stands today. Nothing here
writes a file, calls `build_config`, or executes any pipeline code.

**Why this split exists:** `config_schema.py` can never go stale — it reads the live dataclass.
`config_ui_metadata.py` is the part a human reviews and edits, and
`tests/webapp/test_ui_metadata_coverage.py` guarantees the two stay in lockstep: add a field to
`AnalysisConfig` without updating `config_ui_metadata.py` and the test suite fails immediately,
rather than the web app silently showing an incomplete form.
