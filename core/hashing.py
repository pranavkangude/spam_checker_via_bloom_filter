"""Double hashing for the Bloom filter (F-02, TRD 4.2).

    h1 = first 8 bytes of SHA-256(key)           (big-endian int)
    h2 = first 8 bytes of MD5(key), forced odd
    index_i = (h1 + i * h2) mod m,  i = 0 .. k-1

Python's built-in hash() is NEVER used: it is randomized per process, so a
saved filter would break after a restart. Reference: Kirsch and Mitzenmacher
(2006), "Less Hashing, Same Performance: Building a Better Bloom Filter".
"""
from __future__ import annotations

from hashlib import md5, sha256

HASH_SCHEME = 1  # stored in the filter file header; bump if the scheme changes


def base_hashes(key: str) -> tuple[int, int]:
    """Return (h1, h2) for a key; h2 is always odd. O(len(key))."""
    data = key.encode("utf-8")
    h1 = int.from_bytes(sha256(data).digest()[:8], "big")
    h2 = int.from_bytes(md5(data).digest()[:8], "big") | 1
    return h1, h2


def hash_indexes(key: str, m: int, k: int) -> list[int]:
    """The k bit positions (0 <= idx < m) for a key. O(k)."""
    if m < 1 or k < 1:
        raise ValueError("m and k must be >= 1")
    h1, h2 = base_hashes(key)
    return [(h1 + i * h2) % m for i in range(k)]
