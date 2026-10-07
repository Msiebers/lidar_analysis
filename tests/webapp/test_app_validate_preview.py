"""Validation and YAML preview pages (Web-P1D). Both are read-only: the
no-write tests below fail if anything is written anywhere."""
from __future__ import annotations

import builtins
import html
import os
import pathlib
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp import form_handling as fh

from .html_forms import form_posting_to

REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_SAVE_DOCUMENT = doc.save_document
REAL_TEMPLATE_PATH = REPO_ROOT / "experiment_config.yaml"
REAL_CONFIG_PATHS = (
    REAL_TEMPLATE_PATH,
    REPO_ROOT / "lidar_analysis" / "example_configs" / "full_experiment_config_template.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "premerge_pai_biomass.yaml",
)


@pytest.fixture
def client():
    with TestClient(webapp.create_app(), base_url="http://127.0.0.1:8000") as c:
        yield c


def _document(client: TestClient):
    return client.app.state.sessions.get(client.cookies["lidar_config_editor_session"]).document


def _open(client: TestClient, path: Path) -> str:
    response = client.post("/documents/open", data={"path": str(path)})
    assert response.status_code == 200
    return response.text


def _copy_with(tmp_path: Path, old: str, new: str) -> Path:
    text = REAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path = tmp_path / "edited.yaml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def _set_fields(client: TestClient, **values: str) -> None:
    form = form_posting_to(client.get("/editor").text, "/editor/fields")
    form.update(values)
    assert client.post("/editor/fields", data=form, follow_redirects=False).status_code == 303


def _preview_yaml(page: str) -> str:
    start = page.index('<pre id="yaml">') + len('<pre id="yaml">')
    return html.unescape(page[start:page.index("</pre>", start)])


# --- Validation ------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_real_configs_validate(client, path):
    _open(client, path)
    page = client.get("/validate")
    assert page.status_code == 200
    assert "build_config() accepted this configuration" in page.text


def test_a_build_config_rule_is_reported_with_a_link_to_its_field(client):
    _open(client, REAL_TEMPLATE_PATH)
    _set_fields(client, **{"analysis.analyze_one_side": "true", "analysis.analyze_side": ""})
    page = client.get("/validate").text
    assert "analyze_one_side=true requires analyze_side" in page
    assert 'href="/editor#f-analysis-analyze_side"' in page or 'href="/editor#f-analysis-analyze_one_side"' in page


def test_a_document_level_error_links_to_parallel_scans(client):
    _open(client, REAL_TEMPLATE_PATH)
    _set_fields(client, **{"doc.processing.parallel_scans": "-2"})
    page = client.get("/validate").text
    assert 'href="/editor#f-doc-processing-parallel_scans"' in page
    assert "accepted this configuration" not in page


def test_a_locked_conflict_is_reported(client, tmp_path):
    _open(client, _copy_with(tmp_path, "  pai_g_function: spherical\n", "  pai_g_function: other\n"))
    page = client.get("/validate").text
    assert "locked" in page
    assert 'href="/editor#f-analysis-pai_g_function"' in page


def test_a_required_null_in_the_file_is_reported_by_name_not_as_a_type_error(client, tmp_path):
    _open(client, _copy_with(tmp_path, "  start_u: 0.0\n", "  start_u: null\n"))
    page = client.get("/validate").text
    assert "Start offset is empty (null) in this file" in page
    assert 'href="/editor#f-analysis-start_u"' in page
    for raw in ("NoneType", "float()", "Traceback"):
        assert raw not in page


def test_required_value_problems_lists_each_null_required_field():
    document = doc.new_document("X")
    document.analysis["row_width_u"] = None
    document.analysis["n_plots"] = None  # optional: fine
    problems = fh.required_value_problems(document)
    assert [p.field for p in problems] == ["row_width_u"]


# --- Preview ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_preview_shows_exactly_what_would_be_saved(client, path):
    _open(client, path)
    page = client.get("/preview")
    assert page.status_code == 200
    assert _preview_yaml(page.text) == doc.render_document_yaml(_document(client))


def test_preview_reflects_edits(client):
    _open(client, REAL_TEMPLATE_PATH)
    _set_fields(client, **{"analysis.row_width_u": "1.75"})
    assert "row_width_u: 1.75" in _preview_yaml(client.get("/preview").text)


def test_preview_escapes_html(client):
    client.post("/documents/new", data={"experiment_name": "<b>bold</b>"})
    page = client.get("/preview").text
    assert "<b>bold</b>" not in page
    assert "experiment_name: <b>bold</b>" in _preview_yaml(page)


def test_preview_of_a_locked_conflict_explains_instead_of_failing(client, tmp_path):
    _open(client, _copy_with(tmp_path, "  pai_g_function: spherical\n", "  pai_g_function: other\n"))
    page = client.get("/preview")
    assert page.status_code == 409
    assert "cannot be previewed" in page.text
    assert "/editor#f-analysis-pai_g_function" in page.text
    assert "Traceback" not in page.text


@pytest.mark.parametrize("url", ["/validate", "/preview"])
def test_without_a_document_go_home(client, url):
    response = client.get(url, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_editor_links_to_validate_and_preview(client):
    _open(client, REAL_TEMPLATE_PATH)
    page = client.get("/editor").text
    assert 'href="/validate"' in page and 'href="/preview"' in page


# --- Nothing is ever written ----------------------------------------------------------

@pytest.fixture
def forbid_writes(monkeypatch):
    """Any attempt to write, create, rename or delete a file fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"filesystem write attempted: {args!r}")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"open({file!r}, {mode!r}) attempted")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    for target, name in (
        (os, "replace"), (os, "rename"), (os, "remove"), (os, "unlink"), (os, "mkdir"), (os, "makedirs"),
        (os, "fdopen"), (tempfile, "mkstemp"), (tempfile, "NamedTemporaryFile"),
        (pathlib.Path, "write_text"), (pathlib.Path, "write_bytes"), (pathlib.Path, "mkdir"),
        (pathlib.Path, "touch"), (pathlib.Path, "unlink"), (pathlib.Path, "rename"), (pathlib.Path, "replace"),
        (doc, "save_document"),
    ):
        monkeypatch.setattr(target, name, refuse)


def _snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(directory.rglob("*")) if p.is_file()
    }


@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_editor_validate_and_preview_write_nothing(client, tmp_path, request, path):
    source = tmp_path / path.name
    source.write_bytes(path.read_bytes())
    _open(client, source)
    before = _snapshot(tmp_path)

    request.getfixturevalue("forbid_writes")
    for url in ("/editor", "/validate", "/preview", "/editor?changed=1"):
        assert client.get(url).status_code == 200, url
    _set_fields(client, **{"analysis.row_width_u": "2.5"})
    assert client.get("/preview").status_code == 200

    assert _snapshot(tmp_path) == before


def test_the_no_write_guard_itself_catches_a_real_save(tmp_path, forbid_writes):
    """Proves the guard is not vacuous: the real save path trips it."""
    with pytest.raises(AssertionError):
        _REAL_SAVE_DOCUMENT(doc.new_document("X"), tmp_path / "out.yaml")
    assert not (tmp_path / "out.yaml").exists()
