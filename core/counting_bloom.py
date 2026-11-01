"""Counting Bloom filter with deletion (F-10, TRD 4.4).

Each bit of the standard filter becomes a 1-byte counter (bytearray(m)):
    add     increments the k counters, saturating at 255 (never overflows)
    remove  decrements the k counters, except counters stuck at 255
    in      true when all k counters are > 0

Rules:
  * Only remove keys that were really added. Removing a never-added key that
    happens to be a false positive would corrupt other entries; the service
    layer confirms the key exists in the exact store before calling remove().
  * A counter that reached 255 can no longer be trusted (it may have lost
    increments), so it is never decremented. Such keys may stay "present"
    after remove(); that is the safe side (no false negatives for others).
  * Memory is 8x a standard filter with the same m (1 byte vs 1 bit).
"""
from __future__ import annotations

from core.bloom import BloomFilter

COUNTER_MAX = 255
MAX_COUNTING_M = 2 ** 28  # 256 MiB of counters; the standard filter allows 2**33 bits


class CountingBloomFilter(BloomFilter):
    """Bloom filter whose cells are saturating 1-byte counters.

    Attributes are the same as BloomFilter; `bits` holds one counter per
    cell (m bytes), also available as `counters`.
    """

    FILTER_TYPE = 1  # stored in the file header

    def __init__(self, n_items: int, fp_rate: float = 0.01):
        super().__init__(n_items, fp_rate)  # sizes via params, allocates m bytes
        if self.size > MAX_COUNTING_M:
            raise ValueError(
                f"counting filter would need {self.size} bytes; the limit is {MAX_COUNTING_M}"
            )

    @staticmethod
    def _payload_size(m: int) -> int:
        return m  # one byte per counter

    @property
    def counters(self) -> bytearray:
        return self.bits

    def add(self, key: str) -> None:
        """Increment the k counters (saturating at 255). O(k)."""
        counters = self.bits
        for idx in self.indexes(key):
            if counters[idx] < COUNTER_MAX:
                counters[idx] += 1
        self.count += 1

    def __contains__(self, key: str) -> bool:
        """True only if all k counters are > 0. O(k)."""
        counters = self.bits
        return all(counters[idx] > 0 for idx in self.indexes(key))

    def remove(self, key: str) -> bool:
        """Remove a previously added key. O(k).

        Returns False (and changes nothing) if the key is not reported
        present; True after decrementing its counters. Saturated counters
        (255) are left alone.
        """
        if key not in self:
            return False
        counters = self.bits
        for idx in self.indexes(key):
            if 0 < counters[idx] < COUNTER_MAX:
                counters[idx] -= 1
        if self.count > 0:
            self.count -= 1
        return True

    def fill_ratio(self) -> float:
        """Fraction of counters that are non-zero. O(m)."""
        return (self.size - self.bits.count(0)) / self.size

    def saturated_counters(self) -> int:
        """How many counters are stuck at 255 (should be 0 in normal use). O(m)."""
        return self.bits.count(COUNTER_MAX)
