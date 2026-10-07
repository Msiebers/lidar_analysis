# lidar_analysis/webapp/ — local experiment configuration editor

A browser-based editor for `experiment_config.yaml`, run locally on the machine that holds
the data. It creates, opens, edits, validates, previews and saves experiment configs.
It never runs the pipeline.

## Running it

```bash
.venv/bin/python -m pip install -r requirements.txt   # adds fastapi, uvicorn, jinja2, python-multipart, httpx2
.venv/bin/python -m lidar_analysis.webapp              # http://127.0.0.1:8000  (--port to change)
```

It listens on 127.0.0.1 only; there is no option to listen on another interface. From
another computer, forward the port over SSH and open the address there:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<analysis-machine>
```

State is in memory, per browser session. Restarting the server discards open documents;
anything not saved is lost.

## Layering

**`AnalysisConfig` (`lidar_analysis/config.py`) and `central_runner.build_config()` are
authoritative.** Nothing in this package duplicates the field list, types, defaults, or
validation rules by hand.

| Module | Role |
|---|---|
| `config_schema.py` (P1A) | Live introspection of `AnalysisConfig`: field existence, type, default. |
| `config_ui_metadata.py` (P1A) | Labels, descriptions, sections, BASIC/ADVANCED/EXPERT/LOCKED/HIDDEN_SYSTEM tiers, and the separate `pointcloud_ops` schema. Every description is sourced from the repository. |
| `config_service.py` (P1B) | YAML ⇄ flat field form, legacy-key resolution, LOCKED enforcement, and `validate()` — which calls the real `build_config()`. |
| `experiment_document.py` (P1C) | The whole file: outer metadata plus `analysis:`; load, validate, render, and explicit atomic save that refuses to overwrite by default. |
| `form_handling.py` (P1D) | Browser form strings → typed changes. Types and optionality come from `config_schema`. |
| `pointcloud_ops_form.py` (P1D) | Add / edit / remove `pointcloud_ops` entries; parameter types as read by `pointcloud_ops.py`. |
| `sessions.py` (P1D) | Per-browser in-memory document state, unguessable session ids, one-time overwrite tokens. |
| `editor_view.py` (P1D) | View models for the templates (no logic in the HTML). |
| `app.py`, `templates/`, `__main__.py` (P1D) | FastAPI routes, server-rendered Jinja2 pages, launcher. |

## Behavior worth knowing

- **Absent stays absent.** A setting missing from the file is shown blank ("Not set in this
  file"), and leaving it blank keeps it missing. `build_config()` treats some missing keys
  differently from the same key written with its default value, so only values you actually
  change are written.
- **Blank required values are refused by name**, never handed to `build_config()` as `None`.
  A required value that is `null` in an opened file is reported the same way on the Validate
  page.
- **HIDDEN_SYSTEM** settings are never shown. **LOCKED** settings are shown read-only; a
  conflicting value in an opened file is reported, never silently fixed, and can be reset
  explicitly.
- **`apply_ground_filter`** is one control; changing it also sets the legacy
  `use_local_ground_filter` to the same value, as `build_config()` itself does.
- **`n_plots`** is editable and saved, but `build_config()` does not currently pass it to the
  pipeline; the editor says so beside the field.
- **Point-cloud operations** run in list order. New operations are inserted at their standard
  position (`POINTCLOUD_OP_ORDER`); existing ones are never reordered. New operations write
  every parameter explicitly. `sor_filter.mean_k` has no pre-filled value: the full template
  uses 12, the repository's `experiment_config.yaml` uses 3, and the pipeline falls back to 5
  when it is left out. Keys the editor does not edit are kept as they are.
- **Validate and Preview never write.** Preview shows exactly the text a save would write.
- **Saving** is explicit, to a path you enter, into a folder that already exists. Replacing an
  existing file — including the one you opened — needs a confirmation that works once, for
  that file, while the document is unchanged. Comments in a replaced file are not kept.
- **Localhost only:** requests with any Host other than localhost/127.0.0.1 are refused, as are
  changes sent from another web page (Origin check); the session cookie is HttpOnly and
  SameSite=Strict.

## Tests

`tests/webapp/` — including `test_ui_metadata_coverage.py`, which fails if a field is added to
`AnalysisConfig` without metadata, and `test_pointcloud_ops_form.py`, which fails if an operation
parameter is added to the metadata without a type.
