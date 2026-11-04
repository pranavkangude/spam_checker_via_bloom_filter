"""Bulk import (B6): CSV/TXT upload and the synthetic key generator.

Both paths end in filter_service.add_many(), which does the real work:
  * every row is normalized (bad rows -> rows_invalid)
  * INSERT OR IGNORE into SQLite (ignored rows -> rows_duplicate)
  * only rows really inserted go into the Bloom filter
  * one snapshot save and one import_jobs row at the end
  * all-or-nothing: if parsing fails half way, SQLite rolls back and the
    filter is untouched
Invariant: rows_read = rows_added + rows_duplicate + rows_invalid.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Iterator, Optional

from services import filter_service
from services.errors import PayloadTooLargeError, ValidationError

ALLOWED_EXTENSIONS = (".csv", ".txt")
GEN_MAX_COUNT = 500_000      # measured about 45,000 rows/s, so about 11 s at the limit
GEN_MAX_PREFIX = 50
FILE_NAME_MAX = 255


def _decode(data: bytes) -> str:
    """UTF-8 (BOM allowed) first, latin-1 as the fallback (never fails)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _iter_txt(text: str) -> Iterator[str]:
    """One key per line; blank lines are skipped and not counted."""
    for line in text.splitlines():
        if line.strip():
            yield line


def _iter_csv(text: str, column: Optional[str]) -> Iterator[str]:
    """Yield the chosen column of every data row. The first row is the header."""
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next(reader, None)
        if header is None:
            raise ValidationError("file is empty", field="file")
        header = [h.strip() for h in header]
        if column:
            if column not in header:
                raise ValidationError(
                    f"column '{column}' not found; columns are: {', '.join(header)}",
                    field="column",
                )
            idx = header.index(column)
        else:
            idx = 0                                   # default: first column
        for row in reader:
            if not row:                               # blank line
                continue
            yield row[idx] if idx < len(row) else ""  # short row -> counted invalid
    except csv.Error as exc:
        raise ValidationError(f"CSV could not be parsed: {exc}", field="file")


def import_file(filename, data: bytes, column=None, key_type: str = "other",
                label: str = "fraud") -> dict:
    """Import an uploaded .csv or .txt file. Returns the import summary (4.5)."""
    name = os.path.basename(filename or "")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError("only .csv and .txt files are accepted", field="file")
    if column is not None and (not isinstance(column, str) or len(column) > 200):
        raise ValidationError("column must be a text value", field="column")
    column = column.strip() if column else None
    if not data or not data.strip():
        raise ValidationError("file is empty", field="file")

    text = _decode(data)
    keys = _iter_csv(text, column) if ext == ".csv" else _iter_txt(text)
    return filter_service.add_many(
        keys, key_type, label, source="csv", file_name=name[:FILE_NAME_MAX]
    )


def generate(count, prefix="fraud_txn_", label: str = "fraud",
             key_type: str = "transaction_id", start=0) -> dict:
    """Add `count` synthetic keys prefix{start}, prefix{start+1}, ... (F-03)."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValidationError("count must be an integer >= 1", field="count")
    if count > GEN_MAX_COUNT:
        raise PayloadTooLargeError(
            f"count is limited to {GEN_MAX_COUNT:,} per request", field="count"
        )
    if not isinstance(prefix, str) or len(prefix) > GEN_MAX_PREFIX:
        raise ValidationError(f"prefix must be text of at most {GEN_MAX_PREFIX} characters",
                              field="prefix")
    if isinstance(start, bool) or not isinstance(start, int) or not (0 <= start <= 10**12):
        raise ValidationError("start must be an integer between 0 and 10^12", field="start")
    keys = (f"{prefix}{i}" for i in range(start, start + count))
    return filter_service.add_many(keys, key_type, label, source="synthetic")
