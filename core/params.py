"""Bloom filter parameter math (F-01).

Formulas (see TRD 4.3):
    m = ceil(-(n * ln p) / (ln 2)^2)
    k = max(1, round((m / n) * ln 2))
    p ~= (1 - e^(-k n / m))^k
All functions are O(1).
"""
from __future__ import annotations

import math

MAX_M_BITS = 2 ** 33  # 1 GiB cap, protects memory (TRD 4.3)


def validate_n_p(n: int, p: float) -> None:
    """Raise ValueError unless n >= 1 and 0 < p < 1."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("n must be an integer >= 1")
    if not isinstance(p, (int, float)) or isinstance(p, bool) or not (0 < p < 1):
        raise ValueError("p must satisfy 0 < p < 1")


def optimal_m(n: int, p: float) -> int:
    """Number of bits for n items at target false-positive rate p.

    Raises ValueError if inputs are invalid or m exceeds MAX_M_BITS.
    """
    validate_n_p(n, p)
    m = math.ceil(-(n * math.log(p)) / (math.log(2) ** 2))
    if m > MAX_M_BITS:
        raise ValueError(
            f"required filter size {m} bits exceeds the limit of {MAX_M_BITS} bits"
        )
    return m


def optimal_k(m: int, n: int) -> int:
    """Optimal number of hash functions for m bits and n items (at least 1)."""
    if m < 1 or n < 1:
        raise ValueError("m and n must be >= 1")
    return max(1, round((m / n) * math.log(2)))


def fp_rate(m: int, n: int, k: int) -> float:
    """Theoretical false-positive rate after n insertions into m bits with k hashes."""
    if m < 1 or k < 1 or n < 0:
        raise ValueError("m and k must be >= 1 and n >= 0")
    return (1.0 - math.exp(-k * n / m)) ** k


def bits_per_item(m: int, n: int) -> float:
    """m / n (about 9.585 for p = 1%)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    return m / n
