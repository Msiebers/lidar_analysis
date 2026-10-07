"""The pointcloud_ops pipeline on the editor page: add, edit, remove (Web-P1D)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from lidar_analysis.webapp import app as webapp
from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp.config_ui_metadata import POINTCLOUD_OP_ORDER

from .html_forms import form_posting_to, forms_posting_to

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "lidar_analysis" / "example_configs"
TEMPLATE = EXAMPLES / "full_experiment_config_template.yaml"
REAL_CONFIG_PATHS = (
    REPO_ROOT / "experiment_config.yaml",
    TEMPLATE,
    EXAMPLES / "premerge_pai_biomass.yaml",
    EXAMPLES / "additional_scans_marked_plants_pcl_side_split.yaml",
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


def _revision(page: str) -> str:
    return form_posting_to(page, "/editor/fields")["revision"]


def _ops(client: TestClient) -> list:
    return _document(client).analysis.get("pointcloud_ops") or []


# --- Rendering ------------------------------------------------------------------

def test_each_recognized_op_gets_an_edit_form_and_every_op_a_remove_form(client):
    page = _open(client, TEMPLATE)
    for index in range(len(POINTCLOUD_OP_ORDER)):
        assert len(forms_posting_to(page, f"/editor/ops/{index}/update")) == 1
        assert len(forms_posting_to(page, f"/editor/ops/{index}/remove")) == 1


def test_add_menu_offers_every_recognized_operation(client):
    page = _open(client, TEMPLATE)
    for name in POINTCLOUD_OP_ORDER:
        assert f'<option value="{name}"' in page


def test_voxel_position_note_is_shown(client):
    page = _open(client, TEMPLATE)
    assert "after all other operations" in page


def test_unrecognized_op_is_shown_read_only_with_a_warning(client, tmp_path):
    path = tmp_path / "custom.yaml"
    path.write_text(
        "experiment_name: X\nanalysis:\n  run_height: true\n  pointcloud_ops:\n"
        "    - op: custom_thing\n      size: 3\n    - op: sor_filter\n      mean_k: 3\n      std_ratio: 2.0\n",
        encoding="utf-8",
    )
    page = _open(client, path)
    assert "custom_thing" in page
    assert "not a recognized operation" in page
    assert forms_posting_to(page, "/editor/ops/0/update") == []
    assert len(forms_posting_to(page, "/editor/ops/1/update")) == 1


def test_keys_the_editor_does_not_edit_are_listed(client):
    page = _open(client, EXAMPLES / "additional_scans_marked_plants_pcl_side_split.yaml")
    assert "stddev_mul" in page
    assert "sigma_s" in page


# --- Editing ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_CONFIG_PATHS, ids=lambda p: p.name)
def test_resubmitting_every_op_form_unchanged_changes_nothing(client, path):
    page = _open(client, path)
    document = _document(client)
    yaml_before = doc.render_document_yaml(document)
    ops_before = copy.deepcopy(_ops(client))
    for index in range(len(ops_before)):
        for form in forms_posting_to(page, f"/editor/ops/{index}/update"):
            response = client.post(f"/editor/ops/{index}/update", data=form, follow_redirects=False)
            assert response.status_code == 303
    assert _ops(client) == ops_before
    assert doc.render_document_yaml(document) == yaml_before


def test_editing_one_parameter(client):
    page = _open(client, TEMPLATE)
    form = form_posting_to(page, "/editor/ops/1/update")
    form["op.std_ratio"] = "2.5"
    response = client.post("/editor/ops/1/update", data=form, follow_redirects=False)
    assert response.status_code == 303
    op = _ops(client)[1]
    assert op == {"op": "sor_filter", "enabled": False, "mean_k": 12, "std_ratio": 2.5}


def test_clearing_a_required_parameter_shows_an_error(client):
    page = _open(client, TEMPLATE)
    form = dict(form_posting_to(page, "/editor/ops/1/update"), **{"op.mean_k": ""})
    response = client.post("/editor/ops/1/update", data=form)
    assert response.status_code == 422
    assert "Neighbors (k) is required" in response.text
    assert "NoneType" not in response.text
    assert _ops(client)[1]["mean_k"] == 12


def test_a_stale_op_form_is_refused(client):
    page = _open(client, TEMPLATE)
    form = dict(form_posting_to(page, "/editor/ops/1/update"), **{"op.std_ratio": "3.0"})
    client.post("/editor/ops/0/remove", data={"revision": _revision(page)})
    response = client.post("/editor/ops/1/update", data=form)
    assert response.status_code == 409


def test_editing_an_out_of_range_or_unrecognized_op_is_404(client, tmp_path):
    page = _open(client, TEMPLATE)
    assert client.post("/editor/ops/99/update", data={"revision": _revision(page)}).status_code == 404
    assert client.post("/editor/ops/-1/update", data={"revision": _revision(page)}).status_code == 404


# --- Removing ----------------------------------------------------------------------

def test_removing_an_op(client):
    page = _open(client, TEMPLATE)
    response = client.post("/editor/ops/1/remove", data={"revision": _revision(page)}, follow_redirects=False)
    assert response.status_code == 303
    assert [op["op"] for op in _ops(client)] == [n for n in POINTCLOUD_OP_ORDER if n != "sor_filter"]


def test_removing_with_a_stale_revision_is_refused(client):
    page = _open(client, TEMPLATE)
    response = client.post("/editor/ops/1/remove", data={"revision": "999"})
    assert response.status_code == 409
    assert len(_ops(client)) == len(POINTCLOUD_OP_ORDER)


def test_removing_out_of_range_is_404(client):
    page = _open(client, TEMPLATE)
    assert client.post("/editor/ops/99/remove", data={"revision": _revision(page)}).status_code == 404


# --- Adding --------------------------------------------------------------------------

def test_add_page_leaves_mean_k_blank_with_reference_values(client):
    _open(client, TEMPLATE)
    page = client.get("/editor/ops/new", params={"op": "sor_filter"}).text
    form = form_posting_to(page, "/editor/ops/add")
    assert form["op.mean_k"] == ""
    assert form["op.std_ratio"] == "2.0"
    assert "uses 12" in page and "uses 3" in page


def test_adding_requires_mean_k(client):
    page = _open(client, TEMPLATE)
    form = form_posting_to(client.get("/editor/ops/new", params={"op": "sor_filter"}).text, "/editor/ops/add")
    response = client.post("/editor/ops/add", data=form)
    assert response.status_code == 422
    assert "Neighbors (k) is required" in response.text
    assert len(_ops(client)) == len(POINTCLOUD_OP_ORDER)


def test_adding_inserts_at_the_canonical_position(client):
    _open(client, TEMPLATE)
    add_page = client.get("/editor/ops/new", params={"op": "height_range_filter"}).text
    form = form_posting_to(add_page, "/editor/ops/add")
    response = client.post("/editor/ops/add", data=form, follow_redirects=False)
    assert response.status_code == 303
    names = [op["op"] for op in _ops(client)]
    assert names[3:5] == ["height_range_filter", "height_range_filter"]
    assert names[5] == "voxel_count"
    assert _ops(client)[4] == {"op": "height_range_filter", "enabled": True, "axis": "Y", "min_m": 0.05, "max_m": None}


def test_added_op_appears_in_the_rendered_yaml_and_still_validates(client):
    client.post("/documents/new", data={"experiment_name": "X"})
    form = form_posting_to(client.get("/editor/ops/new", params={"op": "sor_filter"}).text, "/editor/ops/add")
    form["op.mean_k"] = "12"
    assert client.post("/editor/ops/add", data=form, follow_redirects=False).status_code == 303
    document = _document(client)
    text = doc.render_document_yaml(document)
    assert "op: sor_filter" in text and "mean_k: 12" in text
    assert doc.validate_document(document).valid


def test_adding_with_a_stale_revision_is_refused(client):
    _open(client, TEMPLATE)
    form = form_posting_to(client.get("/editor/ops/new", params={"op": "voxel_count"}).text, "/editor/ops/add")
    form["revision"] = "999"
    assert client.post("/editor/ops/add", data=form).status_code == 409
    assert len(_ops(client)) == len(POINTCLOUD_OP_ORDER)


@pytest.mark.parametrize("name", ["not_an_op", "voxel_grid", ""])
def test_unknown_operations_cannot_be_added(client, name):
    _open(client, TEMPLATE)
    assert client.get("/editor/ops/new", params={"op": name}).status_code == 404
    page = client.get("/editor").text
    assert client.post("/editor/ops/add", data={"op": name, "revision": _revision(page)}).status_code == 404


def test_pipeline_routes_without_a_document_go_home(client):
    for method, url in (("get", "/editor/ops/new?op=sor_filter"), ("post", "/editor/ops/add"),
                        ("post", "/editor/ops/0/update"), ("post", "/editor/ops/0/remove")):
        data = {"op": "sor_filter", "revision": "0"} if method == "post" else None
        response = getattr(client, method)(url, data=data, follow_redirects=False) if data else client.get(url, follow_redirects=False)
        assert response.status_code == 303, url
        assert response.headers["location"] == "/"
