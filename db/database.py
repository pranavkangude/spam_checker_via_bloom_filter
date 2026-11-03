"""SQLite helpers (B2): connections, schema setup, query helpers, log pruning."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_DIR = BASE_DIR / "storage"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DB_NAME = "bloomguard.db"
MAX_LOG_ROWS = 10_000

_storage_dir: Path = DEFAULT_STORAGE_DIR


def configure(storage_dir=None) -> None:
    """Choose the storage folder (tests pass a temp folder). None = ./storage."""
    global _storage_dir
    _storage_dir = Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR


def storage_dir() -> Path:
    return _storage_dir


def db_path() -> Path:
    return _storage_dir / DB_NAME


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception, always close."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the storage folder and all tables (safe to call on every start)."""
    _storage_dir.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def query_one(sql: str, params: Sequence = ()) -> Optional[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: Sequence = ()) -> int:
    """Run one write statement; returns rowcount."""
    with connection() as conn:
        return conn.execute(sql, params).rowcount


def prune_check_logs(conn: sqlite3.Connection, keep: int = MAX_LOG_ROWS) -> None:
    """Keep only the newest `keep` rows of check_logs (call after each log insert)."""
    conn.execute(
        "DELETE FROM check_logs WHERE id <= (SELECT MAX(id) - ? FROM check_logs)", (keep,)
    )
