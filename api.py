"""HTTP routes (B4 blacklist, B5 check and history, plus the filter routes).

Validation lives in the services; this file only reads input and returns JSON.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import check_service, filter_service, import_service
from services.errors import ValidationError

bp = Blueprint("api", __name__, url_prefix="/api")

MAX_PAGE_SIZE = 100


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    return data


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(f"{name} must be an integer", field=name)
    if not lo <= value <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}", field=name)
    return value


def _paging() -> tuple[int, int]:
    return _int_arg("page", 1, 1, 10**9), _int_arg("page_size", 20, 1, MAX_PAGE_SIZE)


# ---- health and filter -------------------------------------------------------

@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.post("/filter/calc")
def filter_calc():
    d = _body()
    return jsonify(filter_service.calc(d.get("n"), d.get("p"), d.get("type", "standard")))


@bp.get("/filter")
def filter_get():
    return jsonify(filter_service.get_info())


@bp.post("/filter")
def filter_create():
    d = _body()
    info = filter_service.create_filter(
        d.get("name", "main"), d.get("type", "standard"), d.get("n"), d.get("p"),
        d.get("confirm_replace", False),
    )
    return jsonify(info), 201


@bp.post("/filter/rebuild")
def filter_rebuild():
    d = _body()
    return jsonify(filter_service.rebuild(d.get("n"), d.get("p")))


@bp.delete("/filter")
def filter_reset():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or d.get("confirm") != "RESET":
        raise ValidationError('send {"confirm": "RESET"} to reset everything', field="confirm")
    filter_service.reset_all()
    return "", 204


# ---- blacklist (B4) ----------------------------------------------------------

@bp.post("/blacklist")
def blacklist_add():
    d = _body()
    out = filter_service.add_item(
        d.get("item"), d.get("key_type", "other"), d.get("label", "fraud"), "manual"
    )
    return jsonify(out), 201


@bp.delete("/blacklist")
def blacklist_remove():
    d = _body()
    filter_service.remove_item(d.get("item"), d.get("key_type", "other"))
    return "", 204


@bp.get("/blacklist")
def blacklist_list():
    page, page_size = _paging()
    return jsonify(filter_service.list_entries(
        page, page_size,
        q=request.args.get("q"),
        key_type=request.args.get("key_type") or None,
        label=request.args.get("label") or None,
    ))


@bp.post("/blacklist/bulk")
def blacklist_bulk():
    """multipart/form-data: file, column, key_type, label (BACKEND_SCHEMA 4.3)."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValidationError("a file is required (form field 'file')", field="file")
    return jsonify(import_service.import_file(
        upload.filename, upload.read(),
        column=request.form.get("column") or None,
        key_type=request.form.get("key_type") or "other",
        label=request.form.get("label") or "fraud",
    ))


@bp.post("/blacklist/generate")
def blacklist_generate():
    d = _body()
    return jsonify(import_service.generate(
        d.get("count"), d.get("prefix", "fraud_txn_"), d.get("label", "fraud"),
        d.get("key_type", "transaction_id"), d.get("start", 0),
    ))


# ---- check and history (B5) --------------------------------------------------

@bp.post("/check")
def check():
    d = _body()
    return jsonify(check_service.check_item(
        d.get("item"), d.get("key_type", "other"), d.get("mode", "two_stage")
    ))


@bp.get("/history")
def history_list():
    page, page_size = _paging()
    return jsonify(check_service.history(page, page_size, request.args.get("verdict") or None))


@bp.delete("/history")
def history_clear():
    check_service.clear_history()
    return "", 204
