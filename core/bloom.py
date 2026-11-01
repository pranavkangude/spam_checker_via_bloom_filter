"""Standard Bloom filter (F-02, F-04) with saving and loading (F-06).

A Bloom filter answers "have I seen this key?" using m bits and k hash
functions. It can say "probably yes" (false positives are possible) or
"definitely no" (false negatives are impossible, because a key's k bits are
never cleared once set).

Contract (IMPLEMENTATION_PLAN section 2): attributes size (m), num_hashes (k),
count, bits.

File format (TRD 4.5), all little-endian:
    header  27 bytes  struct "<4sBBBQIQ":
            magic b"BLMF" | version | filter_type | hash_scheme | m | k | count
    payload standard: ceil(m / 8) bytes
    trailer 4 bytes   struct "<I": CRC32 of the payload
"""
from __future__ import annotations

import os
import struct
import zlib

from core.hashing import HASH_SCHEME, hash_indexes
from core.params import MAX_M_BITS, optimal_k, optimal_m, validate_n_p
from core.params import fp_rate as _theoretical_fp_rate

MAGIC = b"BLMF"
FORMAT_VERSION = 1
_HEADER = struct.Struct("<4sBBBQIQ")
_TRAILER = struct.Struct("<I")
HEADER_SIZE = _HEADER.size  # 27


class FilterFormatError(ValueError):
    """Saved filter data is damaged, truncated or from an unsupported version."""


def atomic_write_bytes(path, data: bytes) -> None:
    """Write data to path so a crash can never leave a half-written file.

    Writes to "<path>.tmp", flushes to disk, then os.replace()s it over path.
    """
    path = os.fspath(path)
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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

    FILTER_TYPE = 0  # value stored in the file header (1 = counting)

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
        self.bits = bytearray(self._payload_size(self.size))

    @staticmethod
    def _payload_size(m: int) -> int:
        return (m + 7) // 8

    @classmethod
    def with_size(cls, m: int, k: int) -> "BloomFilter":
        """Empty filter with an explicit number of bits m and hashes k.

        Used by the experiments, which must choose m and k freely instead of
        deriving them from (n, p). capacity and target_fp_rate are None.
        """
        if not isinstance(m, int) or isinstance(m, bool) or not (1 <= m <= MAX_M_BITS):
            raise ValueError(f"m must be an integer between 1 and {MAX_M_BITS}")
        if not isinstance(k, int) or isinstance(k, bool) or k < 1:
            raise ValueError("k must be an integer >= 1")
        obj = cls.__new__(cls)
        obj.capacity = None
        obj.target_fp_rate = None
        obj.size = m
        obj.num_hashes = k
        obj.count = 0
        obj.bits = bytearray(cls._payload_size(m))
        return obj

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

    # ---- saving and loading (A4) -------------------------------------------

    def to_bytes(self) -> bytes:
        """Header + payload + CRC32 trailer. O(m / 8)."""
        payload = bytes(self.bits)
        header = _HEADER.pack(
            MAGIC, FORMAT_VERSION, self.FILTER_TYPE, HASH_SCHEME,
            self.size, self.num_hashes, self.count,
        )
        return header + payload + _TRAILER.pack(zlib.crc32(payload) & 0xFFFFFFFF)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        """Rebuild a filter from to_bytes() output.

        Raises FilterFormatError on a wrong magic, version, filter type or
        hash scheme, bad sizes, wrong length, or CRC32 mismatch.
        """
        if len(data) < HEADER_SIZE + _TRAILER.size:
            raise FilterFormatError("file too short")
        magic, version, ftype, scheme, m, k, count = _HEADER.unpack_from(data, 0)
        if magic != MAGIC:
            raise FilterFormatError("bad magic number (not a BloomGuard filter file)")
        if version != FORMAT_VERSION:
            raise FilterFormatError(f"unsupported format version {version}")
        if ftype != cls.FILTER_TYPE:
            raise FilterFormatError(f"wrong filter type {ftype}")
        if scheme != HASH_SCHEME:
            raise FilterFormatError(f"unsupported hash scheme {scheme}")
        if not (1 <= m <= MAX_M_BITS) or k < 1:
            raise FilterFormatError("invalid size parameters")
        payload_len = cls._payload_size(m)
        if len(data) != HEADER_SIZE + payload_len + _TRAILER.size:
            raise FilterFormatError("payload length does not match header")
        payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
        (crc,) = _TRAILER.unpack_from(data, HEADER_SIZE + payload_len)
        if zlib.crc32(payload) & 0xFFFFFFFF != crc:
            raise FilterFormatError("CRC32 mismatch (data is corrupted)")

        obj = cls.__new__(cls)  # skip __init__: sizes come from the file
        obj.capacity = None
        obj.target_fp_rate = None
        obj.size = m
        obj.num_hashes = k
        obj.count = count
        obj.bits = bytearray(payload)
        return obj

    def save(self, path) -> None:
        """Atomically write the filter to path."""
        atomic_write_bytes(path, self.to_bytes())

    @classmethod
    def load(cls, path) -> "BloomFilter":
        """Read a filter from path (FilterFormatError if damaged)."""
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())
