"""Localhost-only protections for the editor app (Web-P1D): Host allowlist
(DNS rebinding) and Origin checking on state-changing requests (another
web page in the same browser posting to the local server)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp.sessions import SESSION_COOKIE_NAME


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost"])
def test_local_hosts_are_allowed(base_url):
    with TestClient(webapp.create_app(), base_url=base_url) as client:
        assert client.get("/").status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "localhost.evil.example", "0.0.0.0:8000", ""])
def test_other_hosts_are_rejected_before_any_session_is_created(host):
    app = webapp.create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/", headers={"host": host})
    assert response.status_code == 400
    assert "text/html" in response.headers["content-type"]
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert len(app.state.sessions) == 0


@pytest.fixture
def client():
    with TestClient(webapp.create_app(), base_url="http://127.0.0.1:8000") as c:
        yield c


def test_post_without_origin_is_allowed(client):
    """Local non-browser clients (curl smoke tests) send no Origin."""
    response = client.post("/documents/new", data={"experiment_name": "A"}, follow_redirects=False)
    assert response.status_code == 303


def test_post_with_matching_origin_is_allowed(client):
    response = client.post(
        "/documents/new", data={"experiment_name": "A"},
        headers={"origin": "http://127.0.0.1:8000"}, follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "http://127.0.0.1:9999", "http://localhost:8000", "https://127.0.0.1:8000", "null"],
)
def test_post_with_foreign_origin_is_rejected_without_side_effects(client, origin):
    client.get("/")
    response = client.post(
        "/documents/new", data={"experiment_name": "Injected"},
        headers={"origin": origin}, follow_redirects=False,
    )
    assert response.status_code == 403
    assert "text/html" in response.headers["content-type"]
    assert client.get("/editor", follow_redirects=False).status_code == 303


def test_get_with_foreign_origin_is_not_blocked(client):
    """Reads are side-effect free; only state-changing methods are checked."""
    assert client.get("/", headers={"origin": "http://evil.example"}).status_code == 200


def test_referrer_policy_keeps_the_real_origin_on_our_own_forms(client):
    """Regression (found in a real browser): with Referrer-Policy:
    no-referrer, Firefox and Chrome send `Origin: null` on same-site form
    POSTs, so every form submission was refused as cross-site. The test
    client does not emulate that, hence this explicit check."""
    policy = client.get("/").headers["referrer-policy"]
    assert policy == "same-origin"


def test_null_origin_is_still_refused(client):
    response = client.post(
        "/documents/new", data={"experiment_name": "A"},
        headers={"origin": "null"}, follow_redirects=False,
    )
    assert response.status_code == 403
