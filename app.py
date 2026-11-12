"""Flask app factory (B1). Run: python app.py"""
from __future__ import annotations

import importlib.util
import logging
import sqlite3
import uuid

from flask import Flask, jsonify, redirect, render_template, request, url_for
from jinja2 import TemplateNotFound
from werkzeug.exceptions import HTTPException

import api
from db import database
from services import filter_service
from services.errors import ServiceError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# path -> (endpoint name, template file). Templates are built by Member C.
PAGES = {
    "/": ("dashboard", "dashboard.html"),
    "/setup": ("setup", "setup.html"),
    "/check": ("check", "checker.html"),
    "/blacklist": ("blacklist", "blacklist.html"),
    "/import": ("import_page", "import.html"),
    "/benchmark": ("benchmark", "benchmark.html"),
    "/experiments": ("experiments", "experiments.html"),
    "/visualizer": ("visualizer", "visualizer.html"),
    "/history": ("history", "history.html"),
    "/settings": ("settings", "settings.html"),
}

_HTTP_CODES = {400: "VALIDATION_ERROR", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
               413: "PAYLOAD_TOO_LARGE"}


def _page_view(template: str):
    def view():
        try:
            return render_template(template)
        except TemplateNotFound:
            return f"Page '{template}' is not built yet (Member C).", 200
    return view


_ERROR_HEADINGS = {400: "Bad request", 403: "Not allowed", 404: "Page not found", 405: "Method not allowed",
                   413: "File too large", 500: "Something went wrong"}


def _error_page(code: int, message: str, request_id: str | None = None):
    """A styled HTML error page for browser requests (the API keeps its JSON errors)."""
    if code == 404:
        message = "That page does not exist. Check the address, or go back to the dashboard."
    try:
        html = render_template("error.html", code=code, heading=_ERROR_HEADINGS.get(code, "Error"),
                               message=message, request_id=request_id)
    except Exception:                      # the error page itself must never fail
        suffix = f" Request id: {request_id}" if request_id else ""
        return f"{code} {message}{suffix}", code
    return html, code


def create_app(storage_dir=None, testing: bool = False) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["TESTING"] = testing

    database.configure(storage_dir)
    database.init_db()
    filter_service.load_on_startup()

    app.register_blueprint(api.bp)
    # Member C's routes: api_extra.py must define a Blueprint named `bp`
    # (registered under /api, so its routes are "/datasets", "/check/batch").
    if importlib.util.find_spec("api_extra") is not None:
        import api_extra
        app.register_blueprint(api_extra.bp, url_prefix="/api")

    for path, (endpoint, template) in PAGES.items():
        app.add_url_rule(path, endpoint, _page_view(template))

    @app.before_request
    def require_filter():
        path = request.path
        if path.startswith(("/api/", "/static/")):
            return None
        has = filter_service.has_filter()
        if path == "/setup":
            return redirect(url_for("dashboard")) if has else None
        if not has:
            return redirect(url_for("setup"))
        return None

    @app.errorhandler(ServiceError)
    def handle_service_error(exc: ServiceError):
        err = {"code": exc.code, "message": exc.message}
        if exc.field:
            err["field"] = exc.field
        return jsonify({"error": err}), exc.status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if not request.path.startswith("/api/"):
            return _error_page(exc.code or 500, exc.description)
        code = _HTTP_CODES.get(exc.code, "HTTP_ERROR")
        response = jsonify({"error": {"code": code, "message": exc.description}})
        response.status_code = exc.code
        allow = dict(exc.get_headers()).get("Allow")     # 405: tell the client what is allowed
        if allow:
            response.headers["Allow"] = allow
        return response

    @app.errorhandler(sqlite3.OperationalError)
    def handle_db_busy(exc: sqlite3.OperationalError):
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            return handle_unexpected(exc)
        app.logger.warning("Database busy: %s", exc)
        message = "The database is busy. Try again in a moment."
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "DATABASE_BUSY", "message": message}}), 503
        return message, 503

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        request_id = uuid.uuid4().hex[:8]
        app.logger.exception("Unhandled error (request %s)", request_id)
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "INTERNAL_ERROR",
                                      "message": "Something went wrong. Check the terminal.",
                                      "request_id": request_id}}), 500
        return _error_page(500, "Something went wrong. Check the terminal for details.", request_id)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False, threaded=True)
