"""Tests for sessions.py -- per-browser, in-memory editor state (Web-P1D)."""
from __future__ import annotations

import re
import threading
import pytest

from lidar_analysis.webapp import experiment_document as doc
from lidar_analysis.webapp import sessions

_URLSAFE = re.compile(r"[A-Za-z0-9_-]+")


# --- Session identifiers ------------------------------------------------------

def test_session_ids_are_long_unique_and_url_safe():
    store = sessions.SessionStore()
    ids = [store.create().session_id for _ in range(1000)]
    assert len(set(ids)) == 1000
    for session_id in ids:
        assert len(session_id) >= 43  # 32 random bytes, base64url
        assert _URLSAFE.fullmatch(session_id)


def test_session_ids_come_from_the_secrets_module(monkeypatch):
    calls = []

    def fake_token_urlsafe(nbytes):
        calls.append(nbytes)
        return f"token-{len(calls)}"

    monkeypatch.setattr(sessions.secrets, "token_urlsafe", fake_token_urlsafe)
    store = sessions.SessionStore()
    assert store.create().session_id == "token-1"
    assert calls == [32]


def test_an_id_collision_is_never_reused(monkeypatch):
    tokens = iter(["same", "same", "different"])
    monkeypatch.setattr(sessions.secrets, "token_urlsafe", lambda nbytes: next(tokens))
    store = sessions.SessionStore()
    first = store.create()
    second = store.create()
    assert (first.session_id, second.session_id) == ("same", "different")


# --- Isolation within one store -------------------------------------------------

def test_sessions_in_the_same_store_do_not_share_documents():
    store = sessions.SessionStore()
    a = store.create()
    b = store.create()
    a.replace_document(doc.new_document("A"))

    assert b.document is None
    b.replace_document(doc.new_document("B"))
    a.document.analysis["row_width_u"] = 9.0
    a.document.experiment_name = "A-renamed"

    assert b.document.analysis["row_width_u"] != 9.0
    assert b.document.experiment_name == "B"
    assert a.document is not b.document
    assert a.document.analysis is not b.document.analysis


def test_lookup_returns_only_the_matching_session():
    store = sessions.SessionStore()
    a = store.create()
    b = store.create()
    assert store.get(a.session_id) is a
    assert store.get(b.session_id) is b


def test_unknown_missing_or_forged_ids_find_nothing():
    store = sessions.SessionStore()
    real = store.create()
    real.replace_document(doc.new_document("A"))
    for forged in (None, "", "forged", real.session_id[:-1], real.session_id + "x", real.session_id.upper()):
        if forged == real.session_id:
            continue
        assert store.get(forged) is None


def test_get_or_create_never_adopts_a_client_supplied_id():
    """An unknown cookie value gets a fresh session with a server-generated
    id -- the client cannot choose (fixate) its session id."""
    store = sessions.SessionStore()
    session, created = store.get_or_create("attacker-chosen-id")
    assert created is True
    assert session.session_id != "attacker-chosen-id"
    assert store.get("attacker-chosen-id") is None


def test_get_or_create_returns_an_existing_session_unchanged():
    store = sessions.SessionStore()
    existing = store.create()
    session, created = store.get_or_create(existing.session_id)
    assert created is False
    assert session is existing


def test_concurrent_creation_yields_distinct_sessions():
    store = sessions.SessionStore()
    created: list[sessions.EditorSession] = []
    guard = threading.Lock()

    def worker():
        for _ in range(50):
            session = store.create()
            with guard:
                created.append(session)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(created) == 400
    assert len({s.session_id for s in created}) == 400
    assert len(store) == 400


# --- Revisions ------------------------------------------------------------------

def test_replacing_or_changing_the_document_advances_the_revision():
    session = sessions.SessionStore().create()
    assert session.revision == 0
    session.replace_document(doc.new_document("A"))
    assert session.revision == 1
    session.mark_changed()
    assert session.revision == 2


# --- One-time overwrite authorization --------------------------------------------

def test_overwrite_token_is_valid_once_for_its_path_and_revision(tmp_path):
    session = sessions.SessionStore().create()
    session.replace_document(doc.new_document("A"))
    target = tmp_path / "experiment_config.yaml"

    token = session.issue_overwrite_token(target)
    assert session.consume_overwrite_token(token, target) is True
    assert session.consume_overwrite_token(token, target) is False


def test_overwrite_token_is_bound_to_the_resolved_path(tmp_path):
    session = sessions.SessionStore().create()
    session.replace_document(doc.new_document("A"))
    (tmp_path / "sub").mkdir()
    target = tmp_path / "experiment_config.yaml"

    token = session.issue_overwrite_token(tmp_path / "sub" / ".." / "experiment_config.yaml")
    assert session.consume_overwrite_token(token, tmp_path / "other.yaml") is False

    token = session.issue_overwrite_token(target)
    assert session.consume_overwrite_token(token, tmp_path / "sub" / ".." / "experiment_config.yaml") is True


def test_overwrite_token_expires_when_the_document_changes(tmp_path):
    session = sessions.SessionStore().create()
    session.replace_document(doc.new_document("A"))
    target = tmp_path / "experiment_config.yaml"

    token = session.issue_overwrite_token(target)
    session.mark_changed()
    assert session.consume_overwrite_token(token, target) is False


def test_a_wrong_token_does_not_consume_the_pending_authorization(tmp_path):
    session = sessions.SessionStore().create()
    session.replace_document(doc.new_document("A"))
    target = tmp_path / "experiment_config.yaml"

    token = session.issue_overwrite_token(target)
    assert session.consume_overwrite_token("not-the-token", target) is False
    assert session.consume_overwrite_token(token, target) is True


def test_overwrite_tokens_are_not_valid_across_sessions(tmp_path):
    store = sessions.SessionStore()
    a = store.create()
    b = store.create()
    a.replace_document(doc.new_document("A"))
    b.replace_document(doc.new_document("B"))
    target = tmp_path / "experiment_config.yaml"

    token = a.issue_overwrite_token(target)
    assert b.consume_overwrite_token(token, target) is False
    assert a.consume_overwrite_token(token, target) is True


def test_overwrite_tokens_are_unpredictable(tmp_path):
    session = sessions.SessionStore().create()
    session.replace_document(doc.new_document("A"))
    target = tmp_path / "experiment_config.yaml"
    tokens = {session.issue_overwrite_token(target) for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 43 for t in tokens)


def test_issuing_requires_an_open_document(tmp_path):
    session = sessions.SessionStore().create()
    with pytest.raises(RuntimeError):
        session.issue_overwrite_token(tmp_path / "x.yaml")
