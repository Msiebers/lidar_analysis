"""Explicit save and one-time overwrite confirmation (Web-P1D)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp import config_service as svc
from lidar_analysis.webapp import experiment_document as doc

from .html_forms import form_posting_to

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_PATHS = (
    REPO_ROOT / "experiment_config.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "full_experiment_config_template.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "premerge_pai_biomass.yaml",
)
BASE_URL = "http://127.0.0.1:8000"


def _client(app=None) -> TestClient:
    return TestClient(app or webapp.create_app(), base_url=BASE_URL)


@pytest.fixture
def client():
    with _client() as c:
        yield c


def _document(client: TestClient):
    return client.app.state.sessions.get(client.cookies["lidar_config_editor_session"]).document


def _new(client: TestClient, name: str = "SaveTest") -> None:
    client.post("/documents/new", data={"experiment_name": name})


def _save_form(client: TestClient) -> dict[str, str]:
    return form_posting_to(client.get("/editor").text, "/save")


def _save(client: TestClient, path: Path | str, **extra):
    form = dict(_save_form(client), path=str(path), **extra)
    return client.post("/save", data=form, follow_redirects=False)


def _confirm_form(page: str) -> dict[str, str]:
    return form_posting_to(page, "/save/confirm-overwrite")


def _state(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


# --- Saving to a new file ----------------------------------------------------------

def test_save_writes_the_previewed_text_to_a_new_file(client, tmp_path):
    _new(client)
    target = tmp_path / "experiment_config.yaml"
    expected = doc.render_document_yaml(_document(client))

    response = _save(client, target)

    assert response.status_code == 303
    assert target.read_text(encoding="utf-8") == expected
    assert _document(client).source_path == target.resolve()
    assert f"Saved to {target.resolve()}" in client.get(response.headers["location"]).text


def test_save_form_is_prefilled_with_the_opened_path(client, tmp_path):
    source = tmp_path / "cfg.yaml"
    source.write_bytes(REAL_CONFIG_PATHS[0].read_bytes())
    client.post("/documents/open", data={"path": str(source)})
    assert _save_form(client)["path"] == str(source.resolve())


def test_new_document_save_form_starts_blank(client):
    _new(client)
    assert _save_form(client)["path"] == ""


@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_saved_file_configures_the_pipeline_identically(client, tmp_path, path):
    client.post("/documents/open", data={"path": str(path)})
    target = tmp_path / "saved.yaml"
    assert _save(client, target).status_code == 303
    original = svc.validate(svc.load_yaml_file(path))
    saved = svc.validate(svc.load_yaml_file(target))
    assert original.valid and saved.valid
    assert saved.config == original.config


def test_saving_an_invalid_document_is_allowed_but_reported(client, tmp_path):
    _new(client)
    form = form_posting_to(client.get("/editor").text, "/editor/fields")
    form["doc.processing.parallel_scans"] = "-2"
    client.post("/editor/fields", data=form)
    response = _save(client, tmp_path / "wip.yaml")
    assert response.status_code == 303
    page = client.get(response.headers["location"]).text
    assert "1 validation problem" in page


# --- Refusals that write nothing ------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_path_is_refused(client, raw):
    _new(client)
    response = _save(client, raw)
    assert response.status_code == 422
    assert "Enter the path" in response.text


def test_missing_folder_is_refused_and_not_created(client, tmp_path):
    _new(client)
    target = tmp_path / "no" / "such" / "folder" / "cfg.yaml"
    response = _save(client, target)
    assert response.status_code == 422
    assert "does not exist" in response.text
    assert not (tmp_path / "no").exists()


def test_a_folder_path_is_refused(client, tmp_path):
    _new(client)
    response = _save(client, tmp_path)
    assert response.status_code == 422
    assert "is a folder" in response.text


def test_a_locked_conflict_cannot_be_saved(client, tmp_path):
    _new(client)
    _document(client).analysis["pai_g_function"] = "other"
    target = tmp_path / "cfg.yaml"
    response = _save(client, target)
    assert response.status_code == 409
    assert "locked" in response.text.lower()
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_stale_save_form_is_refused(client, tmp_path):
    _new(client)
    form = _save_form(client)
    fields = form_posting_to(client.get("/editor").text, "/editor/fields")
    fields["analysis.row_width_u"] = "9.0"
    client.post("/editor/fields", data=fields)
    target = tmp_path / "cfg.yaml"
    response = client.post("/save", data=dict(form, path=str(target)))
    assert response.status_code == 409
    assert not target.exists()


def test_write_failures_are_reported_readably(client, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("permissions are not enforced for root")
    _new(client)
    locked_dir = tmp_path / "readonly"
    locked_dir.mkdir()
    locked_dir.chmod(0o500)
    try:
        response = _save(client, locked_dir / "cfg.yaml")
    finally:
        locked_dir.chmod(0o700)
    assert response.status_code == 422
    assert "Permission denied" in response.text
    assert "Traceback" not in response.text
    assert list(locked_dir.iterdir()) == []


def test_save_without_a_document_goes_home(client, tmp_path):
    response = client.post("/save", data={"path": str(tmp_path / "x.yaml"), "revision": "0"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_cross_origin_save_is_rejected(client, tmp_path):
    _new(client)
    target = tmp_path / "cfg.yaml"
    form = dict(_save_form(client), path=str(target))
    response = client.post("/save", data=form, headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert not target.exists()


# --- Overwriting needs a one-time confirmation ---------------------------------------------

@pytest.fixture
def existing(tmp_path) -> Path:
    path = tmp_path / "experiment_config.yaml"
    path.write_text("experiment_name: Old\nanalysis: {run_height: true}\n", encoding="utf-8")
    return path


def test_saving_over_an_existing_file_asks_first_and_writes_nothing(client, existing):
    _new(client)
    before = _state(existing)
    response = _save(client, existing)
    assert response.status_code == 200
    assert "already exists" in response.text
    assert str(existing.resolve()) in response.text
    assert _confirm_form(response.text)["token"]
    assert _state(existing) == before


def test_confirming_overwrites_with_the_previewed_text(client, existing):
    _new(client)
    expected = doc.render_document_yaml(_document(client))
    confirm = _confirm_form(_save(client, existing).text)
    response = client.post("/save/confirm-overwrite", data=confirm, follow_redirects=False)
    assert response.status_code == 303
    assert existing.read_text(encoding="utf-8") == expected
    assert _document(client).source_path == existing.resolve()


def test_saving_back_to_the_opened_file_also_asks_first(client, tmp_path):
    source = tmp_path / "cfg.yaml"
    source.write_bytes(REAL_CONFIG_PATHS[0].read_bytes())
    client.post("/documents/open", data={"path": str(source)})
    before = _state(source)
    response = client.post("/save", data=_save_form(client), follow_redirects=False)
    assert response.status_code == 200
    assert "already exists" in response.text
    assert _state(source) == before


def test_a_confirmation_works_only_once(client, existing):
    _new(client)
    confirm = _confirm_form(_save(client, existing).text)
    assert client.post("/save/confirm-overwrite", data=confirm, follow_redirects=False).status_code == 303
    existing.write_text("changed by someone else\n", encoding="utf-8")
    before = _state(existing)
    response = client.post("/save/confirm-overwrite", data=confirm)
    assert response.status_code == 409
    assert _state(existing) == before


def test_a_wrong_token_is_refused(client, existing):
    _new(client)
    confirm = dict(_confirm_form(_save(client, existing).text), token="not-the-token")
    before = _state(existing)
    assert client.post("/save/confirm-overwrite", data=confirm).status_code == 409
    assert _state(existing) == before


def test_a_confirmation_for_another_path_is_refused(client, existing, tmp_path):
    _new(client)
    other = tmp_path / "other.yaml"
    other.write_text("experiment_name: Other\n", encoding="utf-8")
    confirm = dict(_confirm_form(_save(client, existing).text), path=str(other))
    before = (_state(existing), _state(other))
    assert client.post("/save/confirm-overwrite", data=confirm).status_code == 409
    assert (_state(existing), _state(other)) == before


def test_a_confirmation_expires_when_the_document_changes(client, existing):
    _new(client)
    confirm = _confirm_form(_save(client, existing).text)
    fields = form_posting_to(client.get("/editor").text, "/editor/fields")
    fields["analysis.row_width_u"] = "9.0"
    client.post("/editor/fields", data=fields)
    before = _state(existing)
    assert client.post("/save/confirm-overwrite", data=confirm).status_code == 409
    assert _state(existing) == before


def test_a_confirmation_cannot_be_used_by_another_browser(existing):
    app = webapp.create_app()
    with _client(app) as alice, _client(app) as bob:
        _new(alice, "Alice")
        _new(bob, "Bob")
        confirm = _confirm_form(_save(alice, existing).text)
        before = _state(existing)
        assert bob.post("/save/confirm-overwrite", data=confirm).status_code == 409
        assert _state(existing) == before
        assert alice.post("/save/confirm-overwrite", data=confirm, follow_redirects=False).status_code == 303
        assert "experiment_name: Alice" in existing.read_text(encoding="utf-8")


def test_the_token_is_never_in_a_url(client, existing):
    _new(client)
    response = _save(client, existing)
    token = _confirm_form(response.text)["token"]
    assert token not in str(response.url)
    assert f"token={token}" not in response.text
