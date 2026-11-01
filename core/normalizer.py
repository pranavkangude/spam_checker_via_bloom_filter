"""Key normalization (F-07, TRD 4.6).

Identifiers are cleaned BEFORE hashing so that equivalent forms map to the
same key. Both "add" and "check" must call normalize() so they always agree.

Rules per key type:
    email           trim, lowercase
    url             trim, lowercase scheme and host, strip #fragment and
                    trailing slash (path, query and user-info keep their case)
    phone           keep digits and one leading "+" only
    ip              trim
    transaction_id  trim
    other           trim

Empty (after trimming) or over-long (> 2048 chars) values raise ValueError.
"""
from __future__ import annotations

from urllib.parse import urlsplit

KEY_TYPES = ("transaction_id", "email", "url", "ip", "phone", "other")
MAX_LEN = 2048
_DIGITS = "0123456789"


def _normalize_url(value: str) -> str:
    has_scheme = "://" in value
    parts = urlsplit(value if has_scheme else "//" + value)  # no scheme: first part is the host
    netloc = parts.netloc
    if "@" in netloc:  # keep user-info case, lowercase only host[:port]
        userinfo, hostport = netloc.rsplit("@", 1)
        netloc = userinfo + "@" + hostport.lower()
    else:
        netloc = netloc.lower()
    out = (parts.scheme.lower() + "://" if has_scheme and parts.scheme else "") + netloc
    out += parts.path.rstrip("/")
    if parts.query:
        out += "?" + parts.query
    return out  # fragment is dropped


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch in _DIGITS)
    if not digits:
        raise ValueError("phone number contains no digits")
    return ("+" if value.startswith("+") else "") + digits


def normalize(value: str, key_type: str) -> str:
    """Return the canonical key for value. Raises ValueError on bad input."""
    if key_type not in KEY_TYPES:
        raise ValueError(f"unknown key type {key_type!r}; expected one of {', '.join(KEY_TYPES)}")
    if not isinstance(value, str):
        raise ValueError("value must be text")
    value = value.strip()
    if not value:
        raise ValueError("value is empty")
    if len(value) > MAX_LEN:
        raise ValueError(f"value is too long ({len(value)} characters; maximum is {MAX_LEN})")

    if key_type == "email":
        result = value.lower()
    elif key_type == "url":
        result = _normalize_url(value)
    elif key_type == "phone":
        result = _normalize_phone(value)
    else:  # transaction_id, ip, other: trim only
        result = value
    if not result:
        raise ValueError("value is empty after cleaning")
    return result
