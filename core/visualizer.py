"""Teaching filter for the bit-array visualizer (F-11, A11).

A tiny Bloom filter (m = 16..512 bits, k = 1..8) that is separate from the
main filter, so demo actions never touch real data. It uses the REAL
BloomFilter and hashing code (the visualizer must call the backend so the
hashing stays identical; a JavaScript reimplementation is not allowed).

On top of the plain filter it remembers the inserted words and which word
FIRST set each bit, so the page can explain a false positive:
"bit 41 was set by 'world'".

Every method returns plain dicts shaped like the API in BACKEND_SCHEMA 4.8,
so B's endpoints only need to call these and return the result:

    TeachingFilter(m, k).state()          -> {"m", "k", "bits"}                 (reset)
    .insert(item)                         -> {"item", "indexes", "bits", ...}   (insert)
    .query(item)                          -> {"indexes", "bit_values", "result", "bits", ...}
    .find_false_positive(max_tries)       -> {"item", "indexes", "explained_by", ...}

"bits" is a string of "0" / "1" characters of length m; character i is bit i.
Items are cleaned with normalize(item, "other") (trimmed, 1..2048 chars).
"""
from __future__ import annotations

import random
import string
from typing import Collection, Optional

from core.bloom import BloomFilter
from core.normalizer import normalize

MIN_M, MAX_M = 16, 512
MIN_K, MAX_K = 1, 8
MAX_WORDS = 1000            # keeps the in-memory demo bounded
DEFAULT_MAX_TRIES = 200_000
MAX_TRIES_LIMIT = 1_000_000
_ALPHABET = string.ascii_lowercase + string.digits


def find_false_positive(
    bf: BloomFilter,
    inserted: Collection[str],
    max_tries: int = DEFAULT_MAX_TRIES,
    seed: Optional[int] = None,
    length: int = 6,
) -> tuple[Optional[str], int]:
    """Try random words until one passes the filter although it was never inserted.

    Returns (word, tries), or (None, tries) if none was found. With nothing
    inserted every bit is 0, so no false positive can exist (returns (None, 0)).
    Expected tries is about 1 / (fill_ratio ** k). O(max_tries * k).
    """
    if not isinstance(max_tries, int) or isinstance(max_tries, bool) or not (1 <= max_tries <= MAX_TRIES_LIMIT):
        raise ValueError(f"max_tries must be an integer between 1 and {MAX_TRIES_LIMIT}")
    if not inserted:
        return None, 0
    rng = random.Random(seed)
    for tries in range(1, max_tries + 1):
        word = "".join(rng.choices(_ALPHABET, k=length))
        if word not in inserted and word in bf:
            return word, tries
    return None, max_tries


class TeachingFilter:
    """Small Bloom filter that can explain itself."""

    def __init__(self, m: int = 128, k: int = 3):
        if not isinstance(m, int) or isinstance(m, bool) or not (MIN_M <= m <= MAX_M):
            raise ValueError(f"m must be an integer between {MIN_M} and {MAX_M}")
        if not isinstance(k, int) or isinstance(k, bool) or not (MIN_K <= k <= MAX_K):
            raise ValueError(f"k must be an integer between {MIN_K} and {MAX_K}")
        self.m = m
        self.k = k
        self.bf = BloomFilter.with_size(m, k)
        self._words: dict[str, None] = {}      # inserted words, in insertion order
        self._owners: dict[int, str] = {}      # bit index -> first word that set it

    # ---- helpers -----------------------------------------------------------

    @property
    def words(self) -> list[str]:
        return list(self._words)

    def bits_string(self) -> str:
        bits = self.bf.bits
        return "".join("1" if bits[i >> 3] & (1 << (i & 7)) else "0" for i in range(self.m))

    def _bit_is_set(self, idx: int) -> bool:
        return bool(self.bf.bits[idx >> 3] & (1 << (idx & 7)))

    def explain(self, item: str) -> dict[str, str]:
        """{bit index (as text): word that first set it} for the item's SET bits."""
        item = normalize(item, "other")
        return {str(i): self._owners[i] for i in self.bf.indexes(item) if i in self._owners}

    # ---- API-shaped operations ---------------------------------------------

    def state(self) -> dict:
        """Response for "reset": the empty (or current) bit string."""
        return {"m": self.m, "k": self.k, "bits": self.bits_string()}

    def insert(self, item: str) -> dict:
        """Insert a word. Inserting the same word again changes nothing."""
        item = normalize(item, "other")
        indexes = self.bf.indexes(item)
        duplicate = item in self._words
        if not duplicate:
            if len(self._words) >= MAX_WORDS:
                raise ValueError(f"teaching filter is full ({MAX_WORDS} words); reset it")
            self.bf.add(item)
            self._words[item] = None
            for idx in indexes:
                self._owners.setdefault(idx, item)
        return {
            "item": item,
            "indexes": indexes,
            "bits": self.bits_string(),
            "duplicate": duplicate,
        }

    def query(self, item: str) -> dict:
        """Look a word up and explain the answer bit by bit."""
        item = normalize(item, "other")
        indexes = self.bf.indexes(item)
        bit_values = [1 if self._bit_is_set(i) else 0 for i in indexes]
        probable = all(bit_values)
        if probable:
            message = f"All {self.k} bits are 1 -> PROBABLY PRESENT"
        else:
            message = f"Bit {indexes[bit_values.index(0)]} is 0 -> DEFINITELY NOT PRESENT"
        truly_inserted = item in self._words
        return {
            "item": item,
            "indexes": indexes,
            "bit_values": bit_values,
            "result": "PROBABLE" if probable else "ABSENT",
            "message": message,
            "truly_inserted": truly_inserted,
            "false_positive": probable and not truly_inserted,
            "explained_by": self.explain(item),
            "bits": self.bits_string(),
        }

    def find_false_positive(
        self, max_tries: int = DEFAULT_MAX_TRIES, seed: Optional[int] = None
    ) -> dict:
        """Search for a never-inserted word that the filter reports as present."""
        word, tries = find_false_positive(self.bf, self._words, max_tries, seed)
        if word is None:
            reason = (
                "Insert some words first: an empty filter has no false positives."
                if not self._words
                else f"No false positive found in {tries:,} tries. Insert more words or try again."
            )
            return {"found": False, "item": None, "indexes": [], "explained_by": {},
                    "tries": tries, "message": reason, "bits": self.bits_string()}
        return {
            "found": True,
            "item": word,
            "indexes": self.bf.indexes(word),
            "explained_by": {str(i): self._owners[i] for i in self.bf.indexes(word)},
            "tries": tries,
            "message": f"'{word}' was never inserted, but all {self.k} of its bits were "
                       f"already set by other words after {tries:,} tries.",
            "bits": self.bits_string(),
        }
