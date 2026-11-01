import sys

import pytest

from core.estimates import (
    STR_OVERHEAD, bloom_memory_bytes, counting_memory_bytes, format_bytes,
    memory_ratio, set_memory_estimate, set_table_slots,
)


def test_overhead_matches_interpreter():
    assert STR_OVERHEAD == sys.getsizeof("")


@pytest.mark.parametrize("n", [1_000, 10_000, 100_000, 300_000])
def test_estimate_close_to_real_set(n):
    keys = [f"fraud_txn_{i}" for i in range(n)]
    real = sys.getsizeof(set(keys)) + sum(sys.getsizeof(k) for k in keys)
    avg = sum(len(k) for k in keys) / n
    assert set_memory_estimate(n, avg) == pytest.approx(real, rel=0.03)


def test_table_slots_power_of_two_and_load_factor():
    for n in [0, 1, 5, 100, 1000, 12345, 10 ** 6]:
        s = set_table_slots(n)
        assert s & (s - 1) == 0 and s >= 8
        assert n <= s * 3 / 5 + 1e-9


def test_filter_vs_set_ratio_about_10x_at_1pct():
    n, m = 1_000_000, 9_585_059
    ratio = memory_ratio(set_memory_estimate(n, 15), bloom_memory_bytes(m))
    assert ratio > 10


def test_bloom_and_counting_bytes():
    assert bloom_memory_bytes(9_585_059) == 1_198_133
    assert bloom_memory_bytes(8) == 1 and bloom_memory_bytes(9) == 2
    assert counting_memory_bytes(9_585_059) == 9_585_059


def test_format_bytes():
    assert format_bytes(512) == "512 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(1_198_133) == "1.1 MB"


@pytest.mark.parametrize("fn,args", [
    (set_table_slots, (-1,)), (set_memory_estimate, (-1, 5)), (set_memory_estimate, (5, -1)),
    (bloom_memory_bytes, (0,)), (counting_memory_bytes, (0,)), (memory_ratio, (10, 0)),
])
def test_invalid_args(fn, args):
    with pytest.raises(ValueError):
        fn(*args)
