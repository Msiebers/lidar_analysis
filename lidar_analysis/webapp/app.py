"""Local browser-based editor for experiment_config.yaml (Web-P1D).

FastAPI + server-rendered Jinja2, no JavaScript, no database. Meant to run
on 127.0.0.1 only (see __main__.py); reached from another machine through
an SSH tunnel, never by binding a public interface.

Layering -- this module only does HTTP:

    routes/templates (this module)
        -> form_handling.py   (form strings -> typed document changes)
        -> sessions.py        (per-browser in-memory document state)
        -> experiment_document.py -> config_service.py -> build_config()

Every request passes one middleware that, in order:

1. rejects any Host header other than localhost/127.0.0.1 (DNS rebinding);
2. rejects state-changing requests whose Origin header is present but is
   not this server's own origin (another web page posting to the local
   server). A missing Origin is allowed so non-browser local clients such
   as curl keep working;
3. attaches the caller's EditorSession, creating one (with a new
   server-generated id, set in an HttpOnly SameSite=Strict cookie) when
   the cookie is missing or unknown.

Users only ever see HTML pages: framework errors (404/405/400) and any
unexpected exception are rendered by templates/error.html, never as JSON or
a traceback.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException as StarletteHTTPException

from lidar_analysis.webapp import editor_view, form_handling
from lidar_analysis.webapp import experiment_document as documents
from lidar_analysis.webapp.config_service import ValidationError
from lidar_analysis.webapp.config_ui_metadata import Tier, UI_METADATA
from lidar_analysis.webapp.sessions import SESSION_COOKIE_NAME, EditorSession, SessionStore

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_SECURITY_HEADERS = {
    # Document contents are shown in pages; don't keep them in any cache.
    "Cache-Control": "no-store",
    # No scripts at all; inline <style> only; no framing (save buttons
    # must not be clickable through another site's overlay).
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

_HTTP_ERROR_MESSAGES = {
    404: "There is no page at this address.",
    405: "That action is not available at this address.",
}


def _form_text(form: FormData, key: str) -> str:
    value = form.get(key)
    return value if isinstance(value, str) else ""


def _hostname(host_header: str) -> str | None:
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


def _open_error_message(path: Path, exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return f"No file exists at {path}."
    if isinstance(exc, IsADirectoryError):
        return f"{path} is a folder, not a file."
    if isinstance(exc, PermissionError):
        return f"Permission denied when reading {path}."
    if isinstance(exc, UnicodeDecodeError):
        return f"{path} is not a UTF-8 text file."
    if isinstance(exc, yaml.YAMLError):
        mark = getattr(exc, "problem_mark", None)
        where = f" (problem near line {mark.line + 1})" if mark is not None else ""
        return f"{path} is not valid YAML{where}."
    return (
        f"{path} could not be opened as an experiment configuration. "
        "It should be a YAML file of key: value settings, like experiment_config.yaml."
    )


def create_app() -> FastAPI:
    """A new app with its own, empty SessionStore (app.state.sessions)."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = SessionStore()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def render(request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200) -> Response:
        session: EditorSession | None = getattr(request.state, "session", None)
        base = {"current_document": session.document if session else None}
        return templates.TemplateResponse(request, name, {**base, **(context or {})}, status_code=status_code)

    def error_page(request: Request, status_code: int, title: str, message: str) -> Response:
        return render(request, "error.html", {"title": title, "message": message}, status_code)

    # --- Middleware --------------------------------------------------------

    @app.middleware("http")
    async def guard_and_session(request: Request, call_next):
        host_header = request.headers.get("host", "")
        if _hostname(host_header) not in ALLOWED_HOSTNAMES:
            response = error_page(
                request, 400, "Unrecognized address",
                "This editor only answers on localhost / 127.0.0.1.",
            )
        elif request.method not in _SAFE_METHODS and (
            request.headers.get("origin") is not None
            and request.headers["origin"].lower() != f"http://{host_header.lower()}"
        ):
            response = error_page(
                request, 403, "Request refused",
                "This change was sent from another web page, so it was not applied.",
            )
        else:
            session, created = app.state.sessions.get_or_create(request.cookies.get(SESSION_COOKIE_NAME))
            request.state.session = session
            response = await call_next(request)
            if created:
                response.set_cookie(SESSION_COOKIE_NAME, session.session_id, httponly=True, samesite="strict", path="/")
        response.headers.update(_SECURITY_HEADERS)
        return response

    # --- Error pages -------------------------------------------------------

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        message = _HTTP_ERROR_MESSAGES.get(exc.status_code, "The request could not be handled.")
        return error_page(request, exc.status_code, "Not available", message)

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, exc: RequestValidationError) -> Response:
        return error_page(request, 400, "Incomplete request", "The submitted form was incomplete.")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> Response:
        logger.exception("Unhandled error in the configuration editor", exc_info=exc)
        response = error_page(
            request, 500, "Something went wrong",
            "The editor hit an unexpected problem and did not finish this action. "
            "Your open document was not saved or changed by it.",
        )
        response.headers.update(_SECURITY_HEADERS)
        return response

    # --- Pages -------------------------------------------------------------

    @app.get("/")
    async def home(request: Request) -> Response:
        return render(request, "home.html")

    @app.post("/documents/new")
    async def new_document(request: Request) -> Response:
        name = _form_text(await request.form(), "experiment_name").strip()
        if not name:
            return render(
                request, "home.html",
                {"new_error": "Enter an experiment name.", "new_value": name}, status_code=422,
            )
        document = documents.new_document(name)
        session: EditorSession = request.state.session
        with session.lock:
            session.replace_document(document)
        return RedirectResponse("/editor", status_code=303)

    @app.post("/documents/open")
    async def open_document(request: Request) -> Response:
        raw_path = _form_text(await request.form(), "path").strip()
        if not raw_path:
            return render(
                request, "home.html",
                {"open_error": "Enter the path of an experiment_config.yaml file to open."}, status_code=422,
            )
        path = Path(raw_path).expanduser().resolve()
        try:
            document = documents.load_document(path)
        except Exception as exc:  # noqa: BLE001 -- every failure becomes a readable message
            logger.info("Could not open %s", path, exc_info=exc)
            return render(
                request, "home.html",
                {"open_error": _open_error_message(path, exc), "open_value": raw_path}, status_code=422,
            )
        session: EditorSession = request.state.session
        with session.lock:
            session.replace_document(document)
        return RedirectResponse("/editor", status_code=303)

    def render_editor(
        request: Request,
        session: EditorSession,
        *,
        submitted: Mapping[str, str] | None = None,
        errors: tuple[ValidationError, ...] = (),
        notice: str | None = None,
        problem: str | None = None,
        status_code: int = 200,
    ) -> Response:
        document = session.document
        submitted = submitted or {}
        by_field = {e.field: e.message for e in errors if e.field}
        return render(request, "editor.html", {
            "document": document,
            "revision": session.revision,
            "outer_fields": editor_view.build_outer_fields(document, submitted, by_field),
            "sections": editor_view.build_sections(document, submitted, by_field),
            "read_only_items": editor_view.build_read_only_items(document),
            "error_links": [(e.message, editor_view.error_anchor(e.field)) for e in errors],
            "notice": notice,
            "problem": problem,
        }, status_code)

    def revision_matches(form: FormData, session: EditorSession) -> bool:
        return _form_text(form, "revision") == str(session.revision)

    stale_message = (
        "This page was out of date -- the document changed after it was loaded "
        "(perhaps in another tab). Nothing was applied; the current values are shown below."
    )

    @app.get("/editor")
    async def editor(request: Request) -> Response:
        session: EditorSession = request.state.session
        if session.document is None:
            return RedirectResponse("/", status_code=303)
        changed = request.query_params.get("changed", "")
        notice = None
        if changed.isdigit():
            count = int(changed)
            notice = "No changes to apply." if count == 0 else (
                f"{count} change{'s' if count != 1 else ''} applied to the open document. "
                "Nothing has been written to disk."
            )
        return render_editor(request, session, notice=notice)

    @app.post("/editor/fields")
    async def update_fields(request: Request) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            if not revision_matches(form, session):
                return render_editor(request, session, problem=stale_message, status_code=409)
            submitted = {k: v for k, v in form.multi_items() if isinstance(v, str)}
            result = form_handling.apply_field_form(session.document, submitted)
            if not result.applied:
                return render_editor(
                    request, session, submitted=submitted, errors=result.errors,
                    problem="Some values need attention. Nothing was applied.", status_code=422,
                )
            if result.changed_fields:
                session.mark_changed()
        return RedirectResponse(f"/editor?changed={len(result.changed_fields)}", status_code=303)

    @app.post("/editor/locked/{name}/reset")
    async def reset_locked(request: Request, name: str) -> Response:
        meta = UI_METADATA.get(name)
        if meta is None or meta.tier is not Tier.LOCKED:
            raise StarletteHTTPException(status_code=404)
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            if not revision_matches(form, session):
                return render_editor(request, session, problem=stale_message, status_code=409)
            form_handling.reset_locked_field(session.document, name)
            session.mark_changed()
        return RedirectResponse("/editor?changed=1", status_code=303)

    return app
