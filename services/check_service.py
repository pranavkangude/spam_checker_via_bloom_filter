"""Two-stage check service and history (B5).

Stage 1: the Bloom filter (memory, O(k)). Stage 2: an indexed SQLite lookup,
run only when stage 1 says "probably present" and mode is two_stage.
"""
from __future__ import annotations

import logging
import time

from core.counting_bloom import CountingBloomFilter
from core.normalizer import KEY_TYPES
from db import database
from services import filter_service
from services.errors import ValidationError
from services.keys import clean_key

log = logging.getLogger(__name__)

MODES = ("two_stage", "bloom_only")
VERDICTS = ("CLEAN", "BLACKLISTED", "FALSE_POSITIVE", "POSSIBLY_BLACKLISTED")


def _bits_set(f, indexes: list[int]) -> int:
    """How many of the key's positions are set (standard) or non-zero (counting)."""
    cells = f.bits
    if isinstance(f, CountingBloomFilter):
        return sum(1 for i in indexes if cells[i] > 0)
    return sum(1 for i in indexes if cells[i >> 3] & (1 << (i & 7)))


def _write_log(filter_id, key, key_type, mode, bloom_result, exact_result, verdict, latency_us):
    with database.connection() as conn:
        conn.execute(
            "INSERT INTO check_logs (filter_id, item_key, key_type, mode, bloom_result, "
            "exact_result, verdict, latency_us) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (filter_id, key, key_type, mode, bloom_result, exact_result, verdict, latency_us),
        )
        database.prune_check_logs(conn, database.MAX_LOG_ROWS)


def check_item(item, key_type: str = "other", mode: str = "two_stage", log_it: bool = True) -> dict:
    """Check one item. Response shape: BACKEND_SCHEMA 4.4.

    Public so batch checking (C13) can reuse it. Logging is best effort: a
    failure to write the log never fails the check (BACKEND_SCHEMA 5.5).
    """
    if key_type not in KEY_TYPES:
        raise ValidationError(f"key_type must be one of {', '.join(KEY_TYPES)}", field="key_type")
    if mode not in MODES:
        raise ValidationError(f"mode must be one of {', '.join(MODES)}", field="mode")
    try:
        key = clean_key(item, key_type)
    except ValueError as exc:
        raise ValidationError(str(exc), field="item")

    f = filter_service.get_filter()
    filter_id = filter_service.active_id()

    started = time.perf_counter()
    indexes = f.indexes(key)                      # hashed once
    bits_set = _bits_set(f, indexes)
    present = bits_set == len(indexes)            # same rule as `key in f`
    exact_result = None
    label = None
    if not present:
        bloom_result, verdict = "ABSENT", "CLEAN"
    elif mode == "bloom_only":
        bloom_result, verdict = "PROBABLE", "POSSIBLY_BLACKLISTED"
    else:
        bloom_result = "PROBABLE"
        row = database.query_one(
            "SELECT label FROM blacklist_entries WHERE filter_id = ? AND item_key = ?",
            (filter_id, key),
        )
        if row is None:
            exact_result, verdict = "NOT_FOUND", "FALSE_POSITIVE"
        else:
            exact_result, verdict, label = "FOUND", "BLACKLISTED", row["label"]
    latency_us = int((time.perf_counter() - started) * 1_000_000)

    if log_it:
        try:
            _write_log(filter_id, key, key_type, mode, bloom_result, exact_result,
                       verdict, latency_us)
        except Exception as exc:                  # never fail the check because of the log
            log.warning("Could not write check log: %s", exc)

    return {
        "item_key": key, "key_type": key_type, "mode": mode,
        "bloom_result": bloom_result, "exact_result": exact_result, "verdict": verdict,
        "label": label, "indexes": indexes, "bits_set": bits_set, "k": f.num_hashes,
        "latency_us": latency_us,
    }


def history(page: int = 1, page_size: int = 20, verdict=None) -> dict:
    """Newest-first page of check logs, optionally filtered by verdict."""
    where, params = "", []
    if verdict:
        if verdict not in VERDICTS:
            raise ValidationError(f"verdict must be one of {', '.join(VERDICTS)}", field="verdict")
        where, params = "WHERE verdict = ?", [verdict]
    total = database.query_one(f"SELECT COUNT(*) AS c FROM check_logs {where}", params)["c"]
    rows = database.query_all(
        "SELECT id, item_key, key_type, mode, bloom_result, exact_result, verdict, "
        f"latency_us, checked_at FROM check_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    )
    return {"items": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def clear_history() -> None:
    """Delete every check log (also resets the dashboard counters)."""
    database.execute("DELETE FROM check_logs")
