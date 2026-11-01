import pytest

from core.bloom import BloomFilter
from core.hashing import hash_indexes
from core.params import optimal_k, optimal_m


def test_attributes_match_params():
    bf = BloomFilter(1_000_000, 0.01)
    assert bf.size == optimal_m(1_000_000, 0.01) == 9_585_059
    assert bf.num_hashes == optimal_k(bf.size, 1_000_000) == 7
    assert bf.count == 0
    assert len(bf.bits) == (9_585_059 + 7) // 8
    assert bf.memory_bytes() == len(bf.bits)


def test_default_fp_rate_is_one_percent():
    assert BloomFilter(1000).size == BloomFilter(1000, 0.01).size


def test_empty_filter():
    bf = BloomFilter(1000)
    assert "anything" not in bf
    assert bf.fill_ratio() == 0.0
    assert bf.estimated_fp_rate() == 0.0


def test_add_then_contains():
    bf = BloomFilter(1000)
    bf.add("fraud_txn_1")
    assert "fraud_txn_1" in bf
    assert bf.count == 1


def test_unknown_key_not_found_in_small_filter():
    bf = BloomFilter(1000)
    bf.add("fraud_txn_1")
    assert "clean_txn_1" not in bf


def test_indexes_match_hashing_and_set_exact_bits():
    bf = BloomFilter(1000)
    idx = bf.indexes("abc")
    assert idx == hash_indexes("abc", bf.size, bf.num_hashes)
    assert len(idx) == bf.num_hashes
    bf.add("abc")
    for i in idx:
        assert bf.bits[i >> 3] & (1 << (i & 7))
    assert bf.fill_ratio() == pytest.approx(len(set(idx)) / bf.size)


def test_padding_bits_never_set():
    bf = BloomFilter(10, 0.5)  # tiny m, last byte partly unused
    for i in range(200):
        bf.add(f"k{i}")
    last_byte_bits = bf.size % 8
    if last_byte_bits:
        assert bf.bits[-1] >> last_byte_bits == 0


def test_no_false_negatives_100k():
    n = 100_000
    bf = BloomFilter(n, 0.01)
    keys = [f"fraud_txn_{i}" for i in range(n)]
    for key in keys:
        bf.add(key)
    assert bf.count == n
    assert all(key in bf for key in keys)


def test_fill_ratio_and_fp_rate_at_capacity():
    n = 20_000
    bf = BloomFilter(n, 0.01)
    for i in range(n):
        bf.add(f"item_{i}")
    assert bf.fill_ratio() == pytest.approx(0.5, abs=0.02)  # optimal filter is ~half full
    assert bf.estimated_fp_rate() == pytest.approx(0.01, rel=0.1)


def test_empirical_fp_rate_near_target():
    n = 20_000
    bf = BloomFilter(n, 0.01)
    for i in range(n):
        bf.add(f"in_{i}")
    trials = 50_000
    fps = sum(1 for i in range(trials) if f"out_{i}" in bf)
    assert fps / trials < 0.02  # target 1%, generous bound


def test_non_string_key_rejected():
    bf = BloomFilter(100)
    with pytest.raises(TypeError):
        bf.add(123)
    with pytest.raises(TypeError):
        _ = 123 in bf


@pytest.mark.parametrize("n,p", [(0, 0.01), (10, 0), (10, 1)])
def test_invalid_constructor_args(n, p):
    with pytest.raises(ValueError):
        BloomFilter(n, p)


def test_with_size_explicit_m_and_k():
    bf = BloomFilter.with_size(1000, 3)
    assert (bf.size, bf.num_hashes, bf.count) == (1000, 3, 0)
    assert len(bf.bits) == 125
    bf.add("x")
    assert "x" in bf and "y" not in bf


@pytest.mark.parametrize("m,k", [(0, 3), (-1, 3), (10, 0), (2 ** 33 + 1, 3), (10.5, 3), (10, 2.5)])
def test_with_size_invalid(m, k):
    with pytest.raises(ValueError):
        BloomFilter.with_size(m, k)


def test_with_size_counting_keeps_cap():
    from core.counting_bloom import CountingBloomFilter, MAX_COUNTING_M

    cf = CountingBloomFilter.with_size(100, 2)
    assert isinstance(cf, CountingBloomFilter) and len(cf.bits) == 100
    with pytest.raises(ValueError):
        CountingBloomFilter.with_size(MAX_COUNTING_M + 1, 2)
