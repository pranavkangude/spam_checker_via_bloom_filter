"""Member C's routes: built-in datasets (C12) and batch check (C13).

app.py registers this blueprint under /api, so the routes here are written
without the prefix: "/datasets" becomes /api/datasets. Validation lives in the
services; this file reads input and shapes the response.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from api import _body, _body_or_empty
from services import batch_service, dataset_service
from services.errors import ValidationError

bp = Blueprint("api_extra", __name__)


@bp.get("/datasets")
def datasets():
    return jsonify(dataset_service.list_datasets())


@bp.post("/datasets/load")
def datasets_load():
    body = _body()
    return jsonify(dataset_service.load_dataset(body.get("name"), body.get("limit")))


@bp.post("/check/batch")
def check_batch():
    """JSON {items, key_type, mode} or multipart (file, column, key_type, mode).

    Add ?format=csv to get the results as a CSV download instead of JSON.
    """
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv"):
        raise ValidationError("format must be json or csv", field="format")

    if request.mimetype == "multipart/form-data":
        upload = request.files.get("file")
        if upload is None:
            raise ValidationError("choose a .csv or .txt file to check", field="file")
        form = request.form
        items = batch_service.items_from_file(upload.filename, upload.read(), form.get("column") or None)
        key_type, mode = form.get("key_type", "other"), form.get("mode", "two_stage")
    else:
        body = _body_or_empty()
        items = batch_service.items_from_list(body.get("items"))
        key_type, mode = body.get("key_type", "other"), body.get("mode", "two_stage")
        if not isinstance(key_type, str):
            raise ValidationError("key_type must be text", field="key_type")
        if not isinstance(mode, str):
            raise ValidationError("mode must be text", field="mode")

    result = batch_service.check_batch(items, key_type, mode)
    if fmt == "csv":
        return Response(
            batch_service.results_to_csv(result["results"]), mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="bloomguard-batch-results.csv"'})
    return jsonify(result)
