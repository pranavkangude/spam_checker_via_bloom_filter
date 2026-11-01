import pytest

from core.bloom import BloomFilter, FilterFormatError
from core.counting_bloom import COUNTER_MAX, CountingBloomFilter
from core.params import optimal_m


def test_attributes_and_memory():
    cf = CountingBloomFilter(1000, 0.01)
    sf = BloomFilter(1000, 0.01)
    assert cf.size == sf.size and cf.num_hashes == sf.num_hashes
    assert len(cf.bits) == cf.size  # one byte per counter
    assert cf.memory_bytes() == cf.size
    assert cf.memory_bytes() / sf.memory_bytes() == pytest.approx(8, rel=0.01)
    assert cf.counters is cf.bits


def test_add_contains_remove_acceptance():
    cf = CountingBloomFilter(1000)
    cf.add("X")
    assert "X" in cf
    assert cf.remove("X") is True
    assert "X" not in cf
    assert cf.count == 0
    assert cf.fill_ratio() == 0.0


def test_remove_absent_key_changes_nothing():
    cf = CountingBloomFilter(1000)
    cf.add("a")
    before = bytes(cf.bits)
    assert cf.remove("never_added") is False
    assert bytes(cf.bits) == before
    assert cf.count == 1


def _colliding_pair(cf):
    """Two different keys that share at least one counter."""
    seen = {}
    for i in range(100_000):
        key = f"k{i}"
        for idx in set(cf.indexes(key)):
            if idx in seen:
                return seen[idx], key
            seen[idx] = key
    raise AssertionError("no collision found")


def test_shared_counter_removal_keeps_other_key():
    cf = CountingBloomFilter(50, 0.1)
    a, b = _colliding_pair(cf)
    assert set(cf.indexes(a)) & set(cf.indexes(b))
    cf.add(a)
    cf.add(b)
    assert cf.remove(a) is True
    assert b in cf          # no false negative for the other key
    assert cf.remove(b) is True
    assert a not in cf and b not in cf
    assert cf.fill_ratio() == 0.0


def test_double_add_needs_double_remove():
    cf = CountingBloomFilter(1000)
    cf.add("dup")
    cf.add("dup")
    cf.remove("dup")
    assert "dup" in cf
    cf.remove("dup")
    assert "dup" not in cf


def test_saturation_never_overflows():
    cf = CountingBloomFilter(10, 0.5)
    for _ in range(300):
        cf.add("hot")
    assert max(cf.bits) == COUNTER_MAX == 255
    assert cf.saturated_counters() >= 1
    assert cf.count == 300


def test_saturated_counters_are_not_decremented():
    cf = CountingBloomFilter(10, 0.5)
    for _ in range(300):
        cf.add("hot")
    saturated_before = cf.saturated_counters()
    assert cf.remove("hot") is True
    assert cf.saturated_counters() == saturated_before
    assert "hot" in cf  # safe side: stays present, never a false negative


def test_counters_never_go_below_zero():
    cf = CountingBloomFilter(100)
    cf.add("a")
    cf.remove("a")
    cf.remove("a")  # second remove: not present -> False, still zeros
    assert max(cf.bits) == 0


def test_no_false_negatives_100k_then_remove_half():
    n = 100_000
    cf = CountingBloomFilter(n, 0.01)
    keys = [f"fraud_txn_{i}" for i in range(n)]
    for key in keys:
        cf.add(key)
    assert all(key in cf for key in keys)
    for key in keys[: n // 2]:
        assert cf.remove(key) is True
    assert cf.count == n // 2
    assert all(key in cf for key in keys[n // 2:])  # survivors all still found
    still_present = sum(1 for key in keys[: n // 2] if key in cf)
    assert still_present / (n // 2) < 0.02  # removed keys are (almost) gone
    assert cf.saturated_counters() == 0


def test_estimated_fp_rate_and_fill_ratio_inherited():
    cf = CountingBloomFilter(1000)
    for i in range(1000):
        cf.add(f"i{i}")
    assert cf.estimated_fp_rate() == pytest.approx(0.01, rel=0.1)
    assert cf.fill_ratio() == pytest.approx(0.5, abs=0.05)


def test_serialization_round_trip():
    cf = CountingBloomFilter(500)
    for i in range(200):
        cf.add(f"k{i}")
    data = cf.to_bytes()
    assert len(data) == 27 + cf.size + 4
    assert data[5] == 1  # header byte 5 is filter_type (0 standard, 1 counting)
    cf2 = CountingBloomFilter.from_bytes(data)
    assert isinstance(cf2, CountingBloomFilter)
    assert cf2.bits == cf.bits and cf2.count == cf.count
    assert all(f"k{i}" in cf2 for i in range(200))
    assert cf2.remove("k0") is True
    assert cf2.count == 199


def test_filter_types_do_not_mix():
    sf_bytes = BloomFilter(100).to_bytes()
    cf_bytes = CountingBloomFilter(100).to_bytes()
    with pytest.raises(FilterFormatError):
        CountingBloomFilter.from_bytes(sf_bytes)
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(cf_bytes)


def test_save_load_file(tmp_path):
    cf = CountingBloomFilter(100)
    cf.add("x")
    cf.save(tmp_path / "c.bin")
    loaded = CountingBloomFilter.load(tmp_path / "c.bin")
    assert "x" in loaded and loaded.bits == cf.bits


def test_size_cap():
    with pytest.raises(ValueError):
        CountingBloomFilter(10 ** 9, 0.001)  # would need > 256 MiB of counters


def test_params_match_standard():
    assert CountingBloomFilter(1_000_000).size == optimal_m(1_000_000, 0.01)
