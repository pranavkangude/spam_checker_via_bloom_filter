"""Batch check (C13, PRD F-14): check many identifiers in one request.

Input is a JSON list or an uploaded .csv/.txt file (same parsing as the bulk import).
Rows that cannot be cleaned (empty, over-long) do not fail the batch; they get the
verdict INVALID and are counted in the summary. Batch checks are not written to the
check history, so a 100,000-row batch cannot flood it.
Invariant: summary.total = clean + blacklisted + false_positive + possibly_blacklisted + invalid.
"""
from __future__ import annotations

import csv
import io
import time
from typing import Iterable

from core.normalizer import KEY_TYPES
from services import check_service, import_service
from services.errors import PayloadTooLargeError, ValidationError

MAX_BATCH = 100_000                 # BACKEND_SCHEMA section 6, TRD section 13
INVALID = "INVALID"

_SUMMARY_KEY = {
    "CLEAN": "clean",
    "BLACKLISTED": "blacklisted",
    "FALSE_POSITIVE": "false_positive",
    "POSSIBLY_BLACKLISTED": "possibly_blacklisted",
    INVALID: "invalid",
}
CSV_COLUMNS = ["row", "item", "item_key", "verdict", "label", "bloom_result", "exact_result", "note"]


def _limit(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if len(out) >= MAX_BATCH:
            raise PayloadTooLargeError(
                f"a batch may hold at most {MAX_BATCH:,} items; split it into several batches",
                field="items")
        out.append(item)
    return out


def items_from_list(items) -> list[str]:
    if not isinstance(items, list):
        raise ValidationError("items must be a list of text values", field="items")
    for i, item in enumerate(items):
        if not isinstance(item, str):
            raise ValidationError(f"items[{i}] must be text", field="items")
    if not items:
        raise ValidationError("items must not be empty", field="items")
    return _limit(items)


def items_from_file(filename, data: bytes, column=None) -> list[str]:
    _, rows = import_service.rows_from_upload(filename, data, column)
    items = _limit(rows)
    if not items:
        raise ValidationError("the file has no rows to check", field="file")
    return items


def check_batch(items: list[str], key_type: str = "other", mode: str = "two_stage") -> dict:
    """Check every item. Returns {summary, results, duration_s} (BACKEND_SCHEMA 4.4)."""
    if key_type not in KEY_TYPES:
        raise ValidationError(f"key_type must be one of {', '.join(KEY_TYPES)}", field="key_type")
    if mode not in check_service.MODES:
        raise ValidationError(f"mode must be one of {', '.join(check_service.MODES)}", field="mode")
    summary = {name: 0 for name in _SUMMARY_KEY.values()}
    results = []
    started = time.perf_counter()
    for row, item in enumerate(items, start=1):
        try:
            r = check_service.check_item(item, key_type, mode, log_it=False)
        except ValidationError as exc:
            if exc.field != "item":                 # a bad key_type or mode is the caller's mistake
                raise
            results.append({"row": row, "item": item, "item_key": None, "verdict": INVALID,
                            "label": None, "bloom_result": None, "exact_result": None,
                            "note": exc.message})
            summary["invalid"] += 1
            continue
        summary[_SUMMARY_KEY[r["verdict"]]] += 1
        results.append({"row": row, "item": item, "item_key": r["item_key"], "verdict": r["verdict"],
                        "label": r["label"], "bloom_result": r["bloom_result"],
                        "exact_result": r["exact_result"], "note": None})
    summary["total"] = len(items)
    return {"summary": summary, "results": results, "key_type": key_type, "mode": mode,
            "duration_s": round(time.perf_counter() - started, 3)}


def _safe_cell(value) -> str:
    """Stop spreadsheet programs from running a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def results_to_csv(results: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for r in results:
        writer.writerow([_safe_cell(r[c]) if c != "row" else r[c] for c in CSV_COLUMNS])
    return out.getvalue()
