"""The field editor page and its form submission (Web-P1D)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from markupsafe import escape
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp import editor_view
from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp import form_handling as fh
from lidar_analysis.webapp.config_ui_metadata import Tier, UI_METADATA

from .html_forms import form_posting_to

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_PATHS = (
    REPO_ROOT / "experiment_config.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "full_experiment_config_template.yaml",
    REPO_ROOT / "lidar_analysis" / "example_configs" / "premerge_pai_biomass.yaml",
)
FIELDS_ACTION = "/editor/fields"


def _form(page: str, action: str = FIELDS_ACTION) -> dict[str, str]:
    return form_posting_to(page, action)


def _client(app=None) -> TestClient:
    return TestClient(app or webapp.create_app(), base_url="http://127.0.0.1:8000")


@pytest.fixture
def client():
    with _client() as c:
        yield c


def _session(client: TestClient):
    return client.app.state.sessions.get(client.cookies["lidar_config_editor_session"])


def _open(client: TestClient, path: Path) -> str:
    response = client.post("/documents/open", data={"path": str(path)})
    assert response.status_code == 200, response.text
    return response.text


# --- What the page renders ---------------------------------------------------

def test_every_editable_field_has_exactly_one_input(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    fields = _form(page)
    expected = {s.form_key for s in fh.analysis_field_specs() if not s.read_only}
    expected |= {s.form_key for s in fh.outer_field_specs()}
    expected.add("revision")
    assert set(fields) == expected


def test_hidden_locked_and_mirrored_fields_are_not_inputs(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    fields = _form(page)
    for name, meta in UI_METADATA.items():
        if meta.tier in (Tier.HIDDEN_SYSTEM, Tier.LOCKED):
            assert f"analysis.{name}" not in fields, name
    assert "analysis.use_local_ground_filter" not in fields


def test_locked_fields_are_shown_with_value_and_reason(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    for name, meta in UI_METADATA.items():
        if meta.tier is Tier.LOCKED:
            assert str(escape(meta.label)) in page
            assert str(escape(meta.description)) in page


def test_hidden_system_labels_are_not_shown(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    for name in ("cart_id", "data_dirs", "write_o3d_ply", "mta_lo_deg"):
        assert str(escape(UI_METADATA[name].label)) not in page


def test_sections_group_fields_by_metadata_tier():
    document = doc.load_document(REAL_CONFIG_PATHS[0])
    for section in editor_view.build_sections(document, {}, {}):
        for group_name, tier in (("basic", Tier.BASIC), ("advanced", Tier.ADVANCED), ("expert", Tier.EXPERT), ("locked", Tier.LOCKED)):
            for field in getattr(section, group_name):
                assert field.spec.metadata.tier is tier
                assert field.spec.metadata.section == section.title


def test_n_plots_note_is_shown(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    assert "Not currently applied" in page


def test_absent_fields_render_blank_with_a_not_set_hint(client):
    client.post("/documents/new", data={"experiment_name": "X"})
    page = client.get("/editor").text
    assert _form(page)["analysis.mta_max_observation_range_m"] == ""
    assert "Not set in this file" in page


# --- Unchanged submission ---------------------------------------------------------

@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_resubmitting_the_rendered_form_changes_nothing(client, path):
    page = _open(client, path)
    document = _session(client).document
    analysis_before = copy.deepcopy(document.analysis)
    yaml_before = doc.render_document_yaml(document)

    response = client.post(FIELDS_ACTION, data=_form(page), follow_redirects=False)

    assert response.status_code == 303
    assert document.analysis == analysis_before
    assert doc.render_document_yaml(document) == yaml_before


# --- Changes and errors ------------------------------------------------------------

def test_a_valid_change_is_applied_and_reported(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    fields = _form(page)
    fields["analysis.row_width_u"] = "1.25"
    response = client.post(FIELDS_ACTION, data=fields, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/editor?changed=1"
    assert _session(client).document.analysis["row_width_u"] == 1.25
    assert "1 change applied" in client.get(response.headers["location"]).text


def test_clearing_a_required_number_shows_a_field_error(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    document = _session(client).document
    before = copy.deepcopy(document.analysis)
    fields = _form(page)
    fields["analysis.row_width_u"] = ""
    fields["analysis.start_u"] = "abc"

    response = client.post(FIELDS_ACTION, data=fields)

    assert response.status_code == 422
    assert "Row width is required" in response.text
    assert "must be a number" in response.text
    for raw in ("NoneType", "float()", "Traceback"):
        assert raw not in response.text
    assert document.analysis == before
    assert _form(response.text)["analysis.start_u"] == "abc"


def test_a_stale_form_is_refused(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    stale = _form(page)
    fresh = dict(stale, **{"analysis.row_width_u": "2.0"})
    assert client.post(FIELDS_ACTION, data=fresh, follow_redirects=False).status_code == 303

    stale["analysis.row_width_u"] = "3.0"
    response = client.post(FIELDS_ACTION, data=stale)
    assert response.status_code == 409
    assert _session(client).document.analysis["row_width_u"] == 2.0


def test_a_missing_or_garbled_revision_is_refused(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    for revision in (None, "", "abc"):
        fields = dict(_form(page), **{"analysis.row_width_u": "9.0"})
        if revision is None:
            del fields["revision"]
        else:
            fields["revision"] = revision
        assert client.post(FIELDS_ACTION, data=fields).status_code == 409
    assert _session(client).document.analysis["row_width_u"] != 9.0


def test_posting_without_an_open_document_goes_home(client):
    response = client.post(FIELDS_ACTION, data={"revision": "0"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_ground_filter_change_through_the_page_sets_both_keys(client):
    page = _open(client, REAL_CONFIG_PATHS[0])
    fields = dict(_form(page), **{"analysis.apply_ground_filter": "false"})
    client.post(FIELDS_ACTION, data=fields)
    analysis = _session(client).document.analysis
    assert analysis["apply_ground_filter"] is False
    assert analysis["use_local_ground_filter"] is False


# --- LOCKED conflicts ------------------------------------------------------------------

def _open_with_locked_conflict(client: TestClient, tmp_path: Path) -> None:
    original = REAL_CONFIG_PATHS[0].read_text(encoding="utf-8")
    assert original.count("  pai_g_function: spherical\n") == 1
    text = original.replace("  pai_g_function: spherical\n", "  pai_g_function: ellipsoidal\n")
    path = tmp_path / "conflict.yaml"
    path.write_text(text, encoding="utf-8")
    _open(client, path)


def test_a_locked_conflict_is_shown_not_silently_fixed(client, tmp_path):
    _open_with_locked_conflict(client, tmp_path)
    page = client.get("/editor").text
    assert "ellipsoidal" in page
    assert "/editor/locked/pai_g_function/reset" in page
    assert _session(client).document.analysis["pai_g_function"] == "ellipsoidal"


def test_resubmitting_fields_does_not_fix_a_locked_conflict(client, tmp_path):
    _open_with_locked_conflict(client, tmp_path)
    client.post(FIELDS_ACTION, data=_form(client.get("/editor").text))
    assert _session(client).document.analysis["pai_g_function"] == "ellipsoidal"


def test_reset_sets_the_locked_value(client, tmp_path):
    _open_with_locked_conflict(client, tmp_path)
    revision = _form(client.get("/editor").text)["revision"]
    response = client.post("/editor/locked/pai_g_function/reset", data={"revision": revision}, follow_redirects=False)
    assert response.status_code == 303
    assert _session(client).document.analysis["pai_g_function"] == "spherical"


def test_reset_with_a_stale_revision_is_refused(client, tmp_path):
    _open_with_locked_conflict(client, tmp_path)
    response = client.post("/editor/locked/pai_g_function/reset", data={"revision": "999"})
    assert response.status_code == 409
    assert _session(client).document.analysis["pai_g_function"] == "ellipsoidal"


@pytest.mark.parametrize("name", ["row_width_u", "cart_id", "not_a_field"])
def test_reset_only_applies_to_locked_fields(client, name):
    _open(client, REAL_CONFIG_PATHS[0])
    revision = _form(client.get("/editor").text)["revision"]
    response = client.post(f"/editor/locked/{name}/reset", data={"revision": revision})
    assert response.status_code == 404
