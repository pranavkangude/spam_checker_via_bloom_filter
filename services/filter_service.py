"""Active filter service (B3): create, load, save, rebuild, add, remove.

SQLite is the source of truth. The in-memory filter is a fast copy and the
.bin file is a restart snapshot. One RLock guards every write.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Iterable, Optional

from core.bloom import BloomFilter, FilterFormatError
from core.counting_bloom import MAX_COUNTING_M, CountingBloomFilter
from core.estimates import bloom_memory_bytes, counting_memory_bytes, set_memory_estimate
from core.normalizer import KEY_TYPES
from core.params import fp_rate as theoretical_fp
from core.params import optimal_k, optimal_m
from db import database
from services.errors import ConflictError, NotFoundError, ValidationError
from services.keys import clean_key

log = logging.getLogger(__name__)

STATE_FILENAME = "filter_state.bin"
N_MAX = 50_000_000
P_MIN, P_MAX = 0.0001, 0.5
NAME_MAX = 100
FETCH_SIZE = 10_000
ASSUMED_KEY_LEN = 15          # average key length used for the set-memory ESTIMATE
LABELS = ("fraud", "spam", "phishing", "other")

_lock = threading.RLock()
_filter: Optional[BloomFilter] = None
_active_id: Optional[int] = None     # id of the active filters row (cached for fast checks)
_rebuilt_on_startup = False


# ---- validation helpers ------------------------------------------------------

def _validate_params(n, p) -> tuple[int, float]:
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= N_MAX):
        raise ValidationError(f"n must be an integer between 1 and {N_MAX:,}", field="n")
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not (P_MIN <= p <= P_MAX):
        raise ValidationError(f"p must be between {P_MIN} and {P_MAX}", field="p")
    return n, float(p)


def _cls(filter_type):
    if filter_type == "standard":
        return BloomFilter
    if filter_type == "counting":
        return CountingBloomFilter
    raise ValidationError("type must be 'standard' or 'counting'", field="type")


def _check_key_type(key_type):
    if key_type not in KEY_TYPES:
        raise ValidationError(f"key_type must be one of {', '.join(KEY_TYPES)}", field="key_type")
    return key_type


def _check_label(label):
    if label not in LABELS:
        raise ValidationError(f"label must be one of {', '.join(LABELS)}", field="label")
    return label


def _state_path():
    return database.storage_dir() / STATE_FILENAME


def _active_row() -> sqlite3.Row:
    row = database.query_one("SELECT * FROM filters WHERE is_active = 1")
    if row is None:
        raise NotFoundError("No active filter")
    return row


def _fill_from_db(f: BloomFilter, conn: sqlite3.Connection, filter_id: int) -> None:
    cur = conn.execute("SELECT item_key FROM blacklist_entries WHERE filter_id = ?", (filter_id,))
    add = f.add
    while True:
        rows = cur.fetchmany(FETCH_SIZE)
        if not rows:
            break
        for r in rows:
            add(r[0])


def _save() -> None:
    if _filter is not None:
        _filter.save(_state_path())


# ---- public: state -----------------------------------------------------------

def has_filter() -> bool:
    return _filter is not None


def active_id() -> int:
    """Row id of the active filter (NotFoundError if none). No database access."""
    if _active_id is None:
        raise NotFoundError("No active filter")
    return _active_id


def get_filter() -> BloomFilter:
    """The active in-memory filter (NotFoundError if none)."""
    if _filter is None:
        raise NotFoundError("No active filter")
    return _filter


def rebuilt_on_startup() -> bool:
    return _rebuilt_on_startup


def calc(n, p, filter_type: str = "standard") -> dict:
    """Parameter calculator (no side effects)."""
    n, p = _validate_params(n, p)
    _cls(filter_type)
    try:
        m = optimal_m(n, p)
    except ValueError as exc:
        raise ValidationError(str(exc), field="n")
    k = optimal_k(m, n)
    if filter_type == "counting":
        if m > MAX_COUNTING_M:
            raise ValidationError(
                f"counting filter would need {m:,} bytes; the limit is {MAX_COUNTING_M:,}", field="n"
            )
        bloom_bytes = counting_memory_bytes(m)
    else:
        bloom_bytes = bloom_memory_bytes(m)
    return {
        "m": m, "k": k, "bits_per_item": m / n, "filter_type": filter_type,
        "bloom_bytes": bloom_bytes,
        "set_bytes_estimate": set_memory_estimate(n, ASSUMED_KEY_LEN),
    }


def get_info() -> dict:
    """Active filter details and stats (BACKEND_SCHEMA 4.2)."""
    f = get_filter()
    row = _active_row()
    counts = {
        r["verdict"]: r["c"]
        for r in database.query_all(
            "SELECT verdict, COUNT(*) AS c FROM check_logs WHERE filter_id = ? GROUP BY verdict",
            (row["id"],),
        )
    }  # based on check_logs, which keeps only the newest 10,000 rows
    items = row["item_count"]
    return {
        "id": row["id"], "name": row["name"], "type": row["filter_type"],
        "n_capacity": row["n_capacity"], "target_fp": row["target_fp"],
        "m_bits": row["m_bits"], "k_hashes": row["k_hashes"],
        "item_count": items,
        "fill_ratio": f.fill_ratio(),
        "estimated_fp": theoretical_fp(row["m_bits"], items, row["k_hashes"]),
        "memory_bytes": f.memory_bytes(),
        "set_memory_estimate_bytes": set_memory_estimate(items, ASSUMED_KEY_LEN),
        "over_capacity": items > row["n_capacity"],
        "rebuilt_on_startup": _rebuilt_on_startup,
        "counters": {
            "checks": sum(counts.values()),
            "clean": counts.get("CLEAN", 0),
            "blacklisted": counts.get("BLACKLISTED", 0),
            "false_positives": counts.get("FALSE_POSITIVE", 0),
        },
    }


# ---- public: lifecycle -------------------------------------------------------

def load_on_startup() -> Optional[BloomFilter]:
    """Load and validate the saved filter; rebuild from SQLite if anything is off."""
    global _filter, _active_id, _rebuilt_on_startup
    with _lock:
        _filter = None
        _active_id = None
        _rebuilt_on_startup = False
        row = database.query_one("SELECT * FROM filters WHERE is_active = 1")
        if row is None:
            return None
        _active_id = row["id"]
        cls = _cls(row["filter_type"])
        db_count = database.query_one(
            "SELECT COUNT(*) AS c FROM blacklist_entries WHERE filter_id = ?", (row["id"],)
        )["c"]
        problem = None
        loaded = None
        try:
            loaded = cls.load(_state_path())
            if loaded.size != row["m_bits"] or loaded.num_hashes != row["k_hashes"]:
                problem = "filter parameters differ from the database"
            elif loaded.count != db_count or row["item_count"] != db_count:
                problem = "item count differs from the database"
        except (OSError, FilterFormatError) as exc:
            problem = str(exc) or exc.__class__.__name__
        if problem is None:
            _filter = loaded
            return _filter

        log.warning("Saved filter rejected (%s); rebuilding from SQLite", problem)
        new = cls.with_size(row["m_bits"], row["k_hashes"])
        with database.connection() as conn:
            _fill_from_db(new, conn, row["id"])
        database.execute(
            "UPDATE filters SET item_count = ?, updated_at = datetime('now') WHERE id = ?",
            (new.count, row["id"]),
        )
        _filter = new
        _rebuilt_on_startup = True
        try:
            _save()
        except OSError as exc:
            log.warning("Could not save rebuilt filter: %s", exc)
        return _filter


def create_filter(name, filter_type, n, p, confirm_replace=False) -> dict:
    """Create a filter. Replaces the active one (and its blacklist) if confirmed."""
    global _filter, _active_id, _rebuilt_on_startup
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= NAME_MAX):
        raise ValidationError(f"name must be 1 to {NAME_MAX} characters", field="name")
    name = name.strip()
    n, p = _validate_params(n, p)
    cls = _cls(filter_type)
    with _lock:
        existing = database.query_one("SELECT id FROM filters WHERE is_active = 1")
        if existing is not None and confirm_replace is not True:
            raise ConflictError(
                "A filter already exists; set confirm_replace to true to replace it",
                field="confirm_replace",
            )
        try:
            new = cls(n, p)
        except ValueError as exc:
            raise ValidationError(str(exc), field="n")
        with database.connection() as conn:
            if existing is not None:
                conn.execute("DELETE FROM filters WHERE id = ?", (existing["id"],))
            cur = conn.execute(
                "INSERT INTO filters (name, filter_type, n_capacity, target_fp, m_bits, "
                "k_hashes, item_count, is_active, state_file) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?)",
                (name, filter_type, n, p, new.size, new.num_hashes, STATE_FILENAME),
            )
            new_id = cur.lastrowid
            new.save(_state_path())   # if saving fails, the DB change is rolled back
        _filter = new
        _active_id = new_id
        _rebuilt_on_startup = False
    return get_info()


def add_item(item, key_type: str = "other", label: str = "fraud", source: str = "manual") -> dict:
    """Add one item: SQLite first (duplicate -> 409), then the filter, then save."""
    key_type, label = _check_key_type(key_type), _check_label(label)
    try:
        key = clean_key(item, key_type)
    except ValueError as exc:
        raise ValidationError(str(exc), field="item")
    with _lock:
        f = get_filter()
        row = _active_row()
        try:
            with database.connection() as conn:
                conn.execute(
                    "INSERT INTO blacklist_entries (filter_id, item_raw, item_key, key_type, "
                    "label, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["id"], item, key, key_type, label, source),
                )
                conn.execute(
                    "UPDATE filters SET item_count = item_count + 1, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
        except sqlite3.IntegrityError:
            raise ConflictError("Already in blacklist", field="item", code="DUPLICATE")
        f.add(key)
        _save()
    return {"item_key": key, "added": True}


def add_many(keys: Iterable[str], key_type: str = "other", label: str = "fraud",
             source: str = "manual", file_name: Optional[str] = None) -> dict:
    """Bulk add. Returns the import summary (read = added + duplicate + invalid)."""
    key_type, label = _check_key_type(key_type), _check_label(label)
    if not isinstance(source, str) or not source:
        raise ValidationError("source must be a non-empty string", field="source")
    started = time.perf_counter()
    read = added = duplicate = invalid = 0
    new_keys: list[str] = []
    with _lock:
        f = get_filter()
        row = _active_row()
        with database.connection() as conn:
            for raw in keys:
                read += 1
                try:
                    key = clean_key(raw, key_type)
                except ValueError:
                    invalid += 1
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO blacklist_entries (filter_id, item_raw, item_key, "
                    "key_type, label, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["id"], raw, key, key_type, label, source),
                )
                if cur.rowcount == 1:
                    added += 1
                    new_keys.append(key)
                else:
                    duplicate += 1
            if added:
                conn.execute(
                    "UPDATE filters SET item_count = item_count + ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (added, row["id"]),
                )
        add = f.add
        for key in new_keys:
            add(key)
        if added:
            _save()
        duration = time.perf_counter() - started
        with database.connection() as conn:
            cur = conn.execute(
                "INSERT INTO import_jobs (filter_id, source, file_name, rows_read, rows_added, "
                "rows_duplicate, rows_invalid, duration_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], source, file_name, read, added, duplicate, invalid, duration),
            )
            job_id = cur.lastrowid
        item_count = row["item_count"] + added
        return {
            "job_id": job_id, "source": source, "rows_read": read, "rows_added": added,
            "rows_duplicate": duplicate, "rows_invalid": invalid,
            "duration_s": round(duration, 3),
            "filter": {
                "item_count": item_count,
                "fill_ratio": f.fill_ratio(),
                "over_capacity": item_count > row["n_capacity"],
            },
        }


def remove_item(item, key_type: str = "other") -> dict:
    """Remove one item (Counting only). Confirms the key exists in SQLite first."""
    key_type = _check_key_type(key_type)
    try:
        key = clean_key(item, key_type)
    except ValueError as exc:
        raise ValidationError(str(exc), field="item")
    with _lock:
        f = get_filter()
        row = _active_row()
        if row["filter_type"] != "counting":
            raise ConflictError(
                "Standard Bloom filters cannot delete. Use Rebuild after removing from the "
                "database, or switch to Counting."
            )
        with database.connection() as conn:
            found = conn.execute(
                "SELECT id FROM blacklist_entries WHERE filter_id = ? AND item_key = ?",
                (row["id"], key),
            ).fetchone()
            if found is None:
                raise NotFoundError("Item is not in the blacklist", field="item")
            conn.execute("DELETE FROM blacklist_entries WHERE id = ?", (found["id"],))
            conn.execute(
                "UPDATE filters SET item_count = item_count - 1, "
                "updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        f.remove(key)
        _save()
    return {"item_key": key, "removed": True}


def list_entries(page: int = 1, page_size: int = 20, q: Optional[str] = None,
                 key_type: Optional[str] = None, label: Optional[str] = None) -> dict:
    """Paged blacklist listing, newest first (BACKEND_SCHEMA 4.3).

    q is a case-insensitive substring match on the normalized key.
    """
    row = _active_row()
    where = ["filter_id = ?"]
    params: list = [row["id"]]
    if q is not None and q.strip():
        where.append("instr(lower(item_key), ?) > 0")
        params.append(q.strip().lower())
    if key_type:
        where.append("key_type = ?")
        params.append(_check_key_type(key_type))
    if label:
        where.append("label = ?")
        params.append(_check_label(label))
    clause = " AND ".join(where)    # fixed fragments only; every value is a ? parameter
    total = database.query_one(
        f"SELECT COUNT(*) AS c FROM blacklist_entries WHERE {clause}", params
    )["c"]
    rows = database.query_all(
        "SELECT id, item_raw, item_key, key_type, label, source, added_at "
        f"FROM blacklist_entries WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    )
    return {"items": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def rebuild(n, p) -> dict:
    """Build a new filter for (n, p) and re-insert every entry from SQLite."""
    global _filter
    n, p = _validate_params(n, p)
    started = time.perf_counter()
    with _lock:
        get_filter()
        row = _active_row()
        cls = _cls(row["filter_type"])
        try:
            new = cls(n, p)
        except ValueError as exc:
            raise ValidationError(str(exc), field="n")
        with database.connection() as conn:
            _fill_from_db(new, conn, row["id"])
            conn.execute(
                "UPDATE filters SET n_capacity = ?, target_fp = ?, m_bits = ?, k_hashes = ?, "
                "item_count = ?, updated_at = datetime('now') WHERE id = ?",
                (n, p, new.size, new.num_hashes, new.count, row["id"]),
            )
            new.save(_state_path())
        _filter = new   # swap last: checks keep using the old filter until now
        reinserted = new.count
    return {
        "reinserted": reinserted,
        "duration_s": round(time.perf_counter() - started, 3),
        "filter": get_info(),
    }


def reset_all() -> None:
    """Delete the filter, blacklist, check logs and import jobs."""
    global _filter, _active_id, _rebuilt_on_startup
    with _lock:
        with database.connection() as conn:
            conn.execute("DELETE FROM check_logs")
            conn.execute("DELETE FROM import_jobs")
            conn.execute("DELETE FROM filters")   # cascades to blacklist_entries
        _filter = None
        _active_id = None
        _rebuilt_on_startup = False
        for path in (_state_path(), _state_path().with_name(STATE_FILENAME + ".tmp")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
