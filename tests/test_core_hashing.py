import hashlib

import pytest

from core.hashing import HASH_SCHEME, base_hashes, hash_indexes


def test_scheme_version():
    assert HASH_SCHEME == 1


def test_deterministic():
    assert hash_indexes("fraud_txn_1", 1000, 7) == hash_indexes("fraud_txn_1", 1000, 7)


def test_matches_reference_definition():
    key = "hello"
    h1, h2 = base_hashes(key)
    assert h1 == int.from_bytes(hashlib.sha256(b"hello").digest()[:8], "big")
    assert h2 == int.from_bytes(hashlib.md5(b"hello").digest()[:8], "big") | 1
    assert hash_indexes(key, 1009, 4) == [(h1 + i * h2) % 1009 for i in range(4)]


def test_h2_always_odd():
    for key in ["a", "b", "user@mail.com", "x" * 500, "ключ", "🙂"]:
        assert base_hashes(key)[1] % 2 == 1


def test_count_and_range():
    idx = hash_indexes("abc", 9_585_059, 7)
    assert len(idx) == 7
    assert all(0 <= i < 9_585_059 for i in idx)


def test_unicode_ok():
    assert len(hash_indexes("ключ🙂", 100, 3)) == 3


def test_different_keys_differ():
    assert hash_indexes("key1", 10**6, 5) != hash_indexes("key2", 10**6, 5)


def test_distribution_roughly_uniform():
    m, buckets = 10_000, [0] * 10
    for i in range(20_000):
        for idx in hash_indexes(f"k{i}", m, 3):
            buckets[idx * 10 // m] += 1
    avg = sum(buckets) / 10
    assert all(abs(b - avg) / avg < 0.05 for b in buckets)


@pytest.mark.parametrize("m,k", [(0, 3), (10, 0), (-1, 3)])
def test_invalid(m, k):
    with pytest.raises(ValueError):
        hash_indexes("a", m, k)
