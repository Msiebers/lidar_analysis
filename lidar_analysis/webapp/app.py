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

from lidar_analysis.webapp import editor_view, form_handling, pointcloud_ops_form
from lidar_analysis.webapp import experiment_document as documents
from lidar_analysis.webapp.config_service import LockedFieldViolation, ValidationError
from lidar_analysis.webapp.config_ui_metadata import POINTCLOUD_OP_METADATA, Tier, UI_METADATA
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
        op_index: int | None = None,
        save_value: str | None = None,
        save_error: str | None = None,
        status_code: int = 200,
    ) -> Response:
        """Re-renders the editor. `submitted`/`errors` belong to the field
        form, or -- when op_index is given -- to that pipeline entry's form."""
        document = session.document
        submitted = submitted or {}
        by_field = {e.field: e.message for e in errors if e.field}
        if op_index is None:
            field_submitted, field_errors = submitted, by_field
            error_links = [(e.message, editor_view.error_anchor(e.field)) for e in errors]
        else:
            field_submitted, field_errors = {}, {}
            error_links = [(e.message, f"op{op_index}-{e.field}" if e.field else None) for e in errors]
        return render(request, "editor.html", {
            "document": document,
            "revision": session.revision,
            "outer_fields": editor_view.build_outer_fields(document, field_submitted, field_errors),
            "sections": editor_view.build_sections(document, field_submitted, field_errors),
            "pipeline": editor_view.build_pipeline(
                document, edit_index=op_index, submitted=submitted, errors=by_field,
            ),
            "addable_ops": editor_view.addable_ops(),
            "read_only_items": editor_view.build_read_only_items(document),
            "error_links": error_links,
            "notice": notice,
            "problem": problem,
            "save_value": save_value if save_value is not None else (
                str(document.source_path) if document.source_path else ""
            ),
            "save_error": save_error,
        }, status_code)

    def revision_matches(form: FormData, session: EditorSession) -> bool:
        return _form_text(form, "revision") == str(session.revision)

    stale_message = (
        "This page was out of date — the document changed after it was loaded "
        "(perhaps in another tab). Nothing was applied; the current values are shown below."
    )

    @app.get("/editor")
    async def editor(request: Request) -> Response:
        session: EditorSession = request.state.session
        if session.document is None:
            return RedirectResponse("/", status_code=303)
        changed = request.query_params.get("changed", "")
        notice = None
        if request.query_params.get("saved") == "1" and session.document.source_path:
            notice = f"Saved to {session.document.source_path}."
            problems = len(editor_view.build_validation(session.document).problems)
            if problems:
                notice += (
                    f" {problems} validation problem{'s remain' if problems != 1 else ' remains'}"
                    " — see Validate."
                )
        elif changed.isdigit():
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

    # --- Validate and preview (read-only: nothing here writes anything) ------

    @app.get("/validate")
    async def validate(request: Request) -> Response:
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            return render(request, "validate.html", {
                "document": session.document,
                "validation": editor_view.build_validation(session.document),
            })

    @app.get("/preview")
    async def preview(request: Request) -> Response:
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            document = session.document
            validation = editor_view.build_validation(document)
            try:
                yaml_text = documents.render_document_yaml(document)
            except LockedFieldViolation:
                conflicts = [
                    (spec.label, f"/editor#{editor_view.error_anchor(spec.name)}")
                    for spec in form_handling.analysis_field_specs()
                    if spec.read_only and spec.name in document.analysis
                    and document.analysis[spec.name] != spec.metadata.locked_value
                ]
                return render(request, "preview.html", {
                    "document": document, "validation": validation, "yaml_text": None,
                    "locked_conflicts": conflicts,
                }, status_code=409)
            return render(request, "preview.html", {
                "document": document, "validation": validation, "yaml_text": yaml_text,
                "locked_conflicts": [],
            })

    # --- Save (the only routes that write a file) ----------------------------

    def save_target_problem(path: Path) -> str | None:
        if path.is_dir():
            return f"{path} is a folder. Enter a file path, such as {path / 'experiment_config.yaml'}."
        if not path.parent.exists():
            return f"The folder {path.parent} does not exist. Create it first, or choose another location."
        if not path.parent.is_dir():
            return f"{path.parent} is not a folder."
        return None

    def save_refused(request: Request, session: EditorSession, raw: str, message: str, status_code: int = 422) -> Response:
        return render_editor(
            request, session, problem=f"Not saved. {message}", save_value=raw, save_error=message,
            status_code=status_code,
        )

    def locked_conflict_message() -> str:
        return (
            "A locked setting in this document has a different value, so it cannot be "
            "saved. Reset it in the editor first (see Validate)."
        )

    def confirm_overwrite(request: Request, session: EditorSession, path: Path) -> Response:
        token = session.issue_overwrite_token(path)
        return render(request, "confirm_overwrite.html", {
            "document": session.document,
            "path": path,
            "token": token,
            "is_source": session.document.source_path is not None
            and Path(session.document.source_path).resolve() == path,
        })

    def write(request: Request, session: EditorSession, path: Path, raw: str, *, overwrite: bool) -> Response:
        try:
            documents.save_document(session.document, path, overwrite=overwrite)
        except FileExistsError:
            # Created by something else after the existence check above.
            return confirm_overwrite(request, session, path)
        except LockedFieldViolation:
            return save_refused(request, session, raw, locked_conflict_message(), 409)
        except PermissionError:
            return save_refused(request, session, raw, f"Permission denied when writing {path}. Nothing was written.")
        except OSError as exc:
            reason = exc.strerror or "the operating system refused the write"
            return save_refused(request, session, raw, f"{path} could not be written ({reason}). Nothing was written.")
        return RedirectResponse("/editor?saved=1", status_code=303)

    @app.post("/save")
    async def save(request: Request) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            if not revision_matches(form, session):
                return render_editor(request, session, problem=stale_message, status_code=409)
            raw = _form_text(form, "path").strip()
            if not raw:
                return save_refused(request, session, raw, "Enter the path of the file to save to.")
            path = Path(raw).expanduser().resolve()
            problem = save_target_problem(path)
            if problem:
                return save_refused(request, session, raw, problem)
            try:
                documents.render_document_yaml(session.document)
            except LockedFieldViolation:
                return save_refused(request, session, raw, locked_conflict_message(), 409)
            if path.exists():
                return confirm_overwrite(request, session, path)
            return write(request, session, path, raw, overwrite=False)

    @app.post("/save/confirm-overwrite")
    async def save_confirm_overwrite(request: Request) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            raw = _form_text(form, "path").strip()
            path = Path(raw).expanduser().resolve() if raw else None
            if path is None or not session.consume_overwrite_token(_form_text(form, "token"), path):
                return render_editor(
                    request, session, status_code=409,
                    problem=(
                        "That overwrite confirmation is no longer valid — it was already used, "
                        "is for a different file, or the document changed since. Nothing was "
                        "written. Save again to confirm afresh."
                    ),
                )
            problem = save_target_problem(path)
            if problem:
                return save_refused(request, session, raw, problem)
            return write(request, session, path, raw, overwrite=True)

    # --- Pointcloud-ops pipeline ---------------------------------------------

    def recognized_op_name(name: str) -> str:
        if name not in POINTCLOUD_OP_METADATA:
            raise StarletteHTTPException(status_code=404)
        return name

    def render_new_op(
        request: Request,
        session: EditorSession,
        name: str,
        *,
        submitted: Mapping[str, str] | None = None,
        errors: tuple[ValidationError, ...] = (),
        problem: str | None = None,
        status_code: int = 200,
    ) -> Response:
        ops = session.document.analysis.get("pointcloud_ops")
        ops = ops if isinstance(ops, list) else []
        return render(request, "new_op.html", {
            "document": session.document,
            "revision": session.revision,
            "op_name": name,
            "op_meta": POINTCLOUD_OP_METADATA[name],
            "position": pointcloud_ops_form.insert_position(ops, name) + 1,
            "position_note": pointcloud_ops_form.position_note(name),
            "fields": editor_view.build_new_op_fields(name, submitted, {e.field: e.message for e in errors if e.field}),
            "problem": problem,
        }, status_code)

    @app.get("/editor/ops/new")
    async def new_op_page(request: Request) -> Response:
        session: EditorSession = request.state.session
        if session.document is None:
            return RedirectResponse("/", status_code=303)
        name = recognized_op_name(request.query_params.get("op", ""))
        return render_new_op(request, session, name)

    @app.post("/editor/ops/add")
    async def add_op(request: Request) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            name = recognized_op_name(_form_text(form, "op"))
            if not revision_matches(form, session):
                return render_new_op(request, session, name, problem=stale_message, status_code=409)
            submitted = {k: v for k, v in form.multi_items() if isinstance(v, str)}
            op, errors = pointcloud_ops_form.build_new_op(name, submitted)
            if op is None:
                return render_new_op(
                    request, session, name, submitted=submitted, errors=errors,
                    problem="Some values need attention. The operation was not added.", status_code=422,
                )
            try:
                pointcloud_ops_form.add_op(session.document, op)
            except ValueError as exc:
                return render_editor(request, session, problem=str(exc), status_code=422)
            session.mark_changed()
        return RedirectResponse("/editor?changed=1#pipeline", status_code=303)

    def existing_op(session: EditorSession, index: int) -> Any:
        try:
            return pointcloud_ops_form.get_op(session.document, index)
        except (IndexError, ValueError):
            raise StarletteHTTPException(status_code=404) from None

    @app.post("/editor/ops/{index}/update")
    async def update_op(request: Request, index: int) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            op = existing_op(session, index)
            if not pointcloud_ops_form.is_recognized(op):
                raise StarletteHTTPException(status_code=404)
            if not revision_matches(form, session):
                return render_editor(request, session, problem=stale_message, status_code=409)
            submitted = {k: v for k, v in form.multi_items() if isinstance(v, str)}
            updated, errors = pointcloud_ops_form.apply_op_form(op, submitted)
            if updated is None:
                return render_editor(
                    request, session, submitted=submitted, errors=errors, op_index=index,
                    problem=f"Operation {index + 1}: some values need attention. Nothing was applied.",
                    status_code=422,
                )
            changed = sum(1 for k in updated if k not in op or updated[k] != op[k] or type(updated[k]) is not type(op[k]))
            if changed:
                pointcloud_ops_form.replace_op(session.document, index, updated)
                session.mark_changed()
        return RedirectResponse(f"/editor?changed={changed}#op{index}", status_code=303)

    @app.post("/editor/ops/{index}/remove")
    async def remove_op(request: Request, index: int) -> Response:
        form = await request.form()
        session: EditorSession = request.state.session
        with session.lock:
            if session.document is None:
                return RedirectResponse("/", status_code=303)
            existing_op(session, index)
            if not revision_matches(form, session):
                return render_editor(request, session, problem=stale_message, status_code=409)
            pointcloud_ops_form.remove_op(session.document, index)
            session.mark_changed()
        return RedirectResponse("/editor?changed=1#pipeline", status_code=303)

    return app
