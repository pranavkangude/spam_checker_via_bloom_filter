"""Counting Bloom filter. STUB - real implementation is task A6."""
from __future__ import annotations

from core.bloom import BloomFilter


class CountingBloomFilter(BloomFilter):
    def remove(self, key: str) -> bool:
        raise NotImplementedError("A6")
