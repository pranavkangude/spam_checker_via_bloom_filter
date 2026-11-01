"""Standard Bloom filter (F-02, F-04).

A Bloom filter answers "have I seen this key?" using m bits and k hash
functions. It can say "probably yes" (false positives are possible) or
"definitely no" (false negatives are impossible, because a key's k bits are
never cleared once set).

Contract (IMPLEMENTATION_PLAN section 2): attributes size (m), num_hashes (k),
count, bits.  Serialization (to_bytes / from_bytes) is task A4.
"""
from __future__ import annotations

from core.hashing import hash_indexes
from core.params import fp_rate as _theoretical_fp_rate
from core.params import optimal_k, optimal_m, validate_n_p


class BloomFilter:
    """Bit-array Bloom filter.

    Attributes:
        size (int): number of bits m.
        num_hashes (int): number of hash functions k.
        count (int): number of add() calls made. The caller (service layer)
            must avoid adding the same key twice, because a Bloom filter
            cannot tell a duplicate from a new key.
        bits (bytearray): the bit array, (m + 7) // 8 bytes.
    """

    def __init__(self, n_items: int, fp_rate: float = 0.01):
        """Size the filter for n_items at target false-positive rate fp_rate.

        Time O(m) once (allocating the bit array).
        """
        validate_n_p(n_items, fp_rate)
        self.capacity = n_items
        self.target_fp_rate = fp_rate
        self.size = optimal_m(n_items, fp_rate)
        self.num_hashes = optimal_k(self.size, n_items)
        self.count = 0
        self.bits = bytearray((self.size + 7) // 8)

    @staticmethod
    def _check_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be a str (normalize it first)")

    def indexes(self, key: str) -> list[int]:
        """The k bit positions for key (used by the visualizer). O(k)."""
        self._check_key(key)
        return hash_indexes(key, self.size, self.num_hashes)

    def add(self, key: str) -> None:
        """Set the k bits of key. O(k)."""
        for idx in self.indexes(key):
            self.bits[idx >> 3] |= 1 << (idx & 7)
        self.count += 1

    def __contains__(self, key: str) -> bool:
        """True only if all k bits are set ("probably present"). O(k)."""
        bits = self.bits
        for idx in self.indexes(key):
            if not bits[idx >> 3] & (1 << (idx & 7)):
                return False
        return True

    def fill_ratio(self) -> float:
        """Fraction of bits that are set (0.0 - 1.0). O(m / 8)."""
        set_bits = int.from_bytes(self.bits, "little").bit_count()
        return set_bits / self.size

    def estimated_fp_rate(self) -> float:
        """(1 - e^(-k * count / m))^k using the real item count. O(1)."""
        return _theoretical_fp_rate(self.size, self.count, self.num_hashes)

    def memory_bytes(self) -> int:
        """Size of the bit array in bytes. O(1)."""
        return len(self.bits)

    def to_bytes(self) -> bytes:
        raise NotImplementedError("A4")

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        raise NotImplementedError("A4")
