"""Per-browser editor state, held in memory by the local web app (Web-P1D).

No database and no persistence: each browser session owns at most one open
ExperimentConfigDocument, kept in this process only. Restarting the server
discards every session; nothing here ever touches the filesystem.

Isolation rests on three properties, each tested:

* Session ids are 32 bytes from `secrets` (not sequential, not derived
  from anything the client sends), and travel only in an HttpOnly cookie.
* A lookup with an unknown, missing or forged id finds nothing; the caller
  then gets a *new* server-generated session -- a client can never choose
  its own session id.
* Each session holds its own document object; nothing is shared between
  sessions.

Overwriting an existing file is authorized by a one-time token bound to
this session, the resolved destination path, and the document revision at
the moment the overwrite was offered -- so a stale confirmation page (the
document changed since) or a token for a different path is refused.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

from lidar_analysis.webapp.experiment_document import ExperimentConfigDocument

SESSION_COOKIE_NAME = "lidar_config_editor_session"
_TOKEN_BYTES = 32


def _new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


@dataclass(frozen=True)
class _PendingOverwrite:
    token: str
    path: Path
    revision: int


@dataclass
class EditorSession:
    """One browser's editor state. Callers hold `lock` for the whole of any
    read-modify-write of the document (requests run concurrently in a
    thread pool)."""

    session_id: str
    document: ExperimentConfigDocument | None = None
    revision: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _pending_overwrite: _PendingOverwrite | None = field(default=None, repr=False)

    def replace_document(self, document: ExperimentConfigDocument) -> None:
        self.document = document
        self.mark_changed()

    def mark_changed(self) -> None:
        """Advance the revision; any offered overwrite no longer applies."""
        self.revision += 1
        self._pending_overwrite = None

    def issue_overwrite_token(self, path: Path) -> str:
        if self.document is None:
            raise RuntimeError("no open document to save")
        token = _new_token()
        self._pending_overwrite = _PendingOverwrite(token, Path(path).resolve(), self.revision)
        return token

    def consume_overwrite_token(self, token: str, path: Path) -> bool:
        """True exactly once, for the token most recently issued, the same
        resolved path, and an unchanged document. A wrong token leaves the
        pending authorization in place."""
        pending = self._pending_overwrite
        if pending is None or not secrets.compare_digest(str(token), pending.token):
            return False
        self._pending_overwrite = None
        return pending.path == Path(path).resolve() and pending.revision == self.revision


class SessionStore:
    """Process-local map of session id -> EditorSession. No expiry in P1D."""

    def __init__(self) -> None:
        self._sessions: dict[str, EditorSession] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def create(self) -> EditorSession:
        with self._lock:
            session_id = _new_token()
            while session_id in self._sessions:
                session_id = _new_token()
            session = EditorSession(session_id=session_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str | None) -> EditorSession | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None) -> tuple[EditorSession, bool]:
        """(session, created). An unknown id is never adopted: a fresh
        session with a new server-generated id is returned instead."""
        session = self.get(session_id)
        if session is not None:
            return session, False
        return self.create(), True
