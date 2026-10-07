"""Route-level tests for the local editor app (Web-P1D): home, create,
open, session isolation between browsers, and user-facing error pages."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp.sessions import SESSION_COOKIE_NAME

REAL_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "experiment_config.yaml"
BASE_URL = "http://127.0.0.1:8000"
RAW_ERROR_MARKERS = ("Traceback", "NoneType", '{"detail"', "Exception", "Error:")


def _client(app=None, **kwargs) -> TestClient:
    return TestClient(app or webapp.create_app(), base_url=BASE_URL, **kwargs)


@pytest.fixture
def client():
    with _client() as c:
        yield c


def _assert_no_raw_errors(text: str) -> None:
    for marker in RAW_ERROR_MARKERS:
        assert marker not in text, marker


def _new(client: TestClient, name: str):
    return client.post("/documents/new", data={"experiment_name": name}, follow_redirects=False)


# --- Home and session cookie -----------------------------------------------------

def test_home_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'name="experiment_name"' in response.text
    assert 'name="path"' in response.text


def test_session_cookie_is_httponly_and_samesite_strict(client):
    response = client.get("/")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()


def test_session_id_never_appears_in_the_page(client):
    response = client.get("/")
    session_id = response.cookies[SESSION_COOKIE_NAME]
    assert session_id not in response.text
    _new(client, "Alpha")
    assert session_id not in client.get("/editor").text


def test_responses_are_not_cached_and_cannot_be_framed(client):
    response = client.get("/")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


# --- Create ----------------------------------------------------------------------

def test_new_document_redirects_to_the_editor(client):
    response = _new(client, "Alpha")
    assert response.status_code == 303
    assert response.headers["location"] == "/editor"
    page = client.get("/editor")
    assert page.status_code == 200
    assert "Alpha" in page.text


def test_blank_experiment_name_is_a_form_error(client):
    response = _new(client, "   ")
    assert response.status_code == 422
    assert "experiment name" in response.text.lower()
    _assert_no_raw_errors(response.text)
    assert client.get("/editor", follow_redirects=False).status_code == 303


def test_missing_form_field_is_handled_like_a_blank_one(client):
    response = client.post("/documents/new", data={}, follow_redirects=False)
    assert response.status_code == 422
    _assert_no_raw_errors(response.text)


def test_html_in_input_is_escaped(client):
    _new(client, "<script>alert(1)</script>")
    page = client.get("/editor").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# --- Open --------------------------------------------------------------------------

def test_open_real_config(client):
    response = client.post("/documents/open", data={"path": str(REAL_TEMPLATE_PATH)}, follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/editor").text
    assert "example_experiment" in page
    assert str(REAL_TEMPLATE_PATH) in page


def test_opening_does_not_modify_the_file(client, tmp_path):
    source = tmp_path / "experiment_config.yaml"
    source.write_text(REAL_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    client.post("/documents/open", data={"path": str(source)})
    client.get("/editor")
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["experiment_config.yaml"]


def test_relative_paths_are_shown_resolved(client, tmp_path, monkeypatch):
    (tmp_path / "cfg.yaml").write_text("experiment_name: Rel\nanalysis: {run_height: true}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    client.post("/documents/open", data={"path": "cfg.yaml"})
    assert str(tmp_path.resolve() / "cfg.yaml") in client.get("/editor").text


@pytest.mark.parametrize(
    "setup, expected",
    [
        (lambda d: d / "missing.yaml", "no file exists"),
        (lambda d: d, "is a folder"),
        (lambda d: _write(d / "bad.yaml", "analysis: [unclosed\n"), "not valid yaml"),
        (lambda d: _write(d / "list.yaml", "- a\n- b\n"), "could not be opened"),
        (lambda d: _write_bytes(d / "bin.yaml", b"\xff\xfe\x00bad"), "not a utf-8 text file"),
    ],
    ids=["missing", "directory", "invalid-yaml", "top-level-list", "not-utf8"],
)
def test_open_failures_are_readable(client, tmp_path, setup, expected):
    path = setup(tmp_path)
    response = client.post("/documents/open", data={"path": str(path)}, follow_redirects=False)
    assert response.status_code == 422
    assert expected in response.text.lower()
    _assert_no_raw_errors(response.text)
    assert client.get("/editor", follow_redirects=False).status_code == 303


def test_blank_open_path_is_a_form_error(client):
    response = client.post("/documents/open", data={"path": " "}, follow_redirects=False)
    assert response.status_code == 422
    _assert_no_raw_errors(response.text)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _write_bytes(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


# --- Editor without a document ------------------------------------------------------

def test_editor_without_a_document_redirects_home(client):
    response = client.get("/editor", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


# --- Isolation between browsers ------------------------------------------------------

def test_two_browsers_never_see_each_others_documents():
    app = webapp.create_app()
    with _client(app) as alice, _client(app) as bob:
        _new(alice, "AliceExperiment")
        assert bob.get("/editor", follow_redirects=False).status_code == 303

        _new(bob, "BobExperiment")
        alice_page = alice.get("/editor").text
        bob_page = bob.get("/editor").text
        assert "AliceExperiment" in alice_page and "BobExperiment" not in alice_page
        assert "BobExperiment" in bob_page and "AliceExperiment" not in bob_page
        assert alice.cookies[SESSION_COOKIE_NAME] != bob.cookies[SESSION_COOKIE_NAME]


def test_a_forged_cookie_gets_a_fresh_empty_session():
    app = webapp.create_app()
    with _client(app) as alice, _client(app) as mallory:
        _new(alice, "AliceExperiment")
        mallory.cookies.set(SESSION_COOKIE_NAME, "forged-session-id", domain="127.0.0.1")
        response = mallory.get("/editor", follow_redirects=False)
        assert response.status_code == 303
        assert mallory.cookies[SESSION_COOKIE_NAME] != "forged-session-id"
        assert "AliceExperiment" not in mallory.get("/").text


def test_separate_app_instances_share_nothing():
    with _client() as first, _client() as second:
        _new(first, "First")
        second.cookies.set(SESSION_COOKIE_NAME, first.cookies[SESSION_COOKIE_NAME], domain="127.0.0.1")
        assert second.get("/editor", follow_redirects=False).status_code == 303


# --- Error pages ----------------------------------------------------------------------

def test_unknown_page_is_an_html_404(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    _assert_no_raw_errors(response.text)


def test_wrong_method_is_an_html_405(client):
    response = client.get("/documents/new")
    assert response.status_code == 405
    assert "text/html" in response.headers["content-type"]
    _assert_no_raw_errors(response.text)


def test_unexpected_failure_shows_a_generic_page(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("internal detail that must not leak")

    monkeypatch.setattr(doc, "new_document", explode)
    with _client(raise_server_exceptions=False) as client:
        response = _new(client, "Alpha")
    assert response.status_code == 500
    assert "text/html" in response.headers["content-type"]
    assert "internal detail" not in response.text
    _assert_no_raw_errors(response.text)
