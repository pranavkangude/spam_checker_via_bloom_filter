"""Bit-array visualizer endpoints' logic (B8, BACKEND_SCHEMA 4.8).

One module-level TeachingFilter (core/visualizer.py, by Member A) lives in
memory only. It is completely separate from the real filter: it never reads or
writes SQLite or filter_state.bin. A lock serialises access because Flask runs
requests on several threads. Restarting the server resets it to m=128, k=3.

A's class raises ValueError for bad input; this module turns those into the
standard error JSON (400, or 409 when the demo filter is full).
"""
from __future__ import annotations

import threading

from core.visualizer import DEFAULT_MAX_TRIES, TeachingFilter
from services.errors import ConflictError, ValidationError

DEFAULT_M, DEFAULT_K = 128, 3

_lock = threading.RLock()
_teaching = TeachingFilter(DEFAULT_M, DEFAULT_K)


def _field(message: str, default: str) -> str:
    """Name the offending field from A's messages ("m must ...", "max_tries must ...")."""
    for name in ("max_tries", "m", "k"):
        if message.startswith(name + " "):
            return name
    return default


def _call(fn, *args, field: str, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        msg = str(exc)
        if "is full" in msg:
            raise ConflictError(msg, code="VISUALIZER_FULL")
        raise ValidationError(msg, field=_field(msg, field))


def state() -> dict:
    """Current teaching filter, including the inserted words (for page reloads)."""
    with _lock:
        return {**_teaching.state(), "words": _teaching.words}


def reset(m=DEFAULT_M, k=DEFAULT_K) -> dict:
    """Replace the teaching filter with a new empty one (m 16-512, k 1-8)."""
    global _teaching
    new = _call(TeachingFilter, m, k, field="m")
    with _lock:
        _teaching = new
        return _teaching.state()


def insert(item) -> dict:
    with _lock:
        return _call(_teaching.insert, item, field="item")


def query(item) -> dict:
    with _lock:
        return _call(_teaching.query, item, field="item")


def find_false_positive(max_tries=DEFAULT_MAX_TRIES, seed=None) -> dict:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValidationError("seed must be an integer", field="seed")
    with _lock:
        return _call(_teaching.find_false_positive, max_tries, seed, field="max_tries")
