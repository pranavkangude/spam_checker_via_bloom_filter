"""Memory estimates for the parameter calculator and the dashboard (A7).

All set-memory numbers are ESTIMATES (label them so in the UI). The model
mirrors how CPython stores a set of strings:

    set object + hash table : sys.getsizeof(set()) + 16 bytes * table slots
    each string             : per-string overhead + len(key)
                              (overhead = sys.getsizeof("") = 49 on Python 3.10)

CPython keeps a set's table at most about 3/5 full, with a power-of-two
number of slots, so slots = smallest power of two >= n * 5 / 3 (min 8).
Sets of 4 or fewer items live in a small table inside the object itself.
"""
from __future__ import annotations

import sys

STR_OVERHEAD = sys.getsizeof("")  # 49 on CPython 3.10
SET_BASE_BYTES = sys.getsizeof(set())  # 216 on CPython 3.10
SLOT_BYTES = 16  # hash (8) + pointer (8) per table slot
_SMALL_SET_LIMIT = 4


def set_table_slots(n: int) -> int:
    """Estimated number of hash-table slots for a set holding n items."""
    if n < 0:
        raise ValueError("n must be >= 0")
    slots = 8
    while slots * 3 < n * 5:
        slots *= 2
    return slots


def set_memory_estimate(n: int, avg_key_len: float) -> int:
    """Estimated bytes for a Python set of n strings of average length avg_key_len."""
    if n < 0 or avg_key_len < 0:
        raise ValueError("n and avg_key_len must be >= 0")
    table = 0 if n <= _SMALL_SET_LIMIT else SLOT_BYTES * set_table_slots(n)
    return int(SET_BASE_BYTES + table + n * (STR_OVERHEAD + avg_key_len))


def bloom_memory_bytes(m: int) -> int:
    """Bytes used by a standard filter with m bits."""
    if m < 1:
        raise ValueError("m must be >= 1")
    return (m + 7) // 8


def counting_memory_bytes(m: int) -> int:
    """Bytes used by a counting filter with m counters (1 byte each)."""
    if m < 1:
        raise ValueError("m must be >= 1")
    return m


def memory_ratio(set_bytes: int, filter_bytes: int) -> float:
    """How many times larger the set is than the filter (e.g. 9.8 means 9.8x)."""
    if filter_bytes < 1:
        raise ValueError("filter_bytes must be >= 1")
    return set_bytes / filter_bytes


def format_bytes(num_bytes: float) -> str:
    """Human readable size such as '9.1 MB' (1024-based)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # unreachable
