"""Standard Bloom filter. STUB - real implementation is tasks A3/A4.

Contract (IMPLEMENTATION_PLAN section 2): attributes size (m), num_hashes (k),
count, bits.
"""
from __future__ import annotations


class BloomFilter:
    def __init__(self, n_items: int, fp_rate: float = 0.01):
        raise NotImplementedError("A3")

    def add(self, key: str) -> None:
        raise NotImplementedError("A3")

    def __contains__(self, key: str) -> bool:
        raise NotImplementedError("A3")

    def indexes(self, key: str) -> list[int]:
        raise NotImplementedError("A3")

    def fill_ratio(self) -> float:
        raise NotImplementedError("A3")

    def estimated_fp_rate(self) -> float:
        raise NotImplementedError("A3")

    def memory_bytes(self) -> int:
        raise NotImplementedError("A3")

    def to_bytes(self) -> bytes:
        raise NotImplementedError("A4")

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        raise NotImplementedError("A4")
