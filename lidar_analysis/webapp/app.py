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
from typing import Any
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException as StarletteHTTPException

from lidar_analysis.webapp import experiment_document as documents
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

    @app.get("/editor")
    async def editor(request: Request) -> Response:
        session: EditorSession = request.state.session
        if session.document is None:
            return RedirectResponse("/", status_code=303)
        return render(request, "editor.html", {"document": session.document})

    return app
