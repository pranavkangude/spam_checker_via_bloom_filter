"""Key cleaning shared by every service that accepts user text (B9).

core.normalizer.normalize() (Member A) trims and canonicalises a value. This
wrapper adds one check that normalize() does not make: the text must be
encodable as UTF-8. A JSON string such as "\\ud800" (a lone surrogate) is valid
JSON but cannot be hashed or stored in SQLite; without this check it would
crash with a 500 instead of a clean 400.
"""
from __future__ import annotations

from core.normalizer import normalize


def clean_key(value, key_type: str) -> str:
    """normalize(value, key_type), plus a UTF-8 check. Raises ValueError."""
    key = normalize(value, key_type)          # raises ValueError for non-text, empty, too long
    try:
        value.encode("utf-8")                 # the raw text is stored too (item_raw)
        key.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("value contains invalid Unicode characters")
    return key
