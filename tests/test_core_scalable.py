import pytest

from core.bloom import BloomFilter
from core.scalable_bloom import ScalableBloomFilter
from services.benchmark_service import make_key_sets


def test_first_stage_is_tighter_than_target():
    sf = ScalableBloomFilter(100, 0.01, growth=2, tightening=0.8)
    assert sf.first_stage_fp == pytest.approx(0.002)          # p0 = target * (1 - r)
    assert sf.num_filters == 1 and sf.capacities == [100]


def test_stages_grow_and_tighten():
    sf = ScalableBloomFilter(100, 0.01)
    for i in range(350):
        sf.add(f"k{i}")
    assert sf.num_filters == 3
    assert sf.capacities == [100, 200, 400]
    assert sf.stage_fp_targets == pytest.approx([0.002, 0.0016, 0.00128])
    assert [f.count for f in sf.filters] == [100, 200, 50]     # older stages stay full
    assert sf.count == 350


def test_new_stage_opens_only_when_full():
    sf = ScalableBloomFilter(10, 0.01)
    for i in range(10):
        sf.add(f"k{i}")
    assert sf.num_filters == 1
    sf.add("one_more")
    assert sf.num_filters == 2


def test_bound_never_exceeds_target():
    sf = ScalableBloomFilter(50, 0.01, tightening=0.8)
    for i in range(5000):                                      # many stages
        sf.add(f"k{i}")
    assert sf.num_filters >= 6
    assert sf.fp_bound() < 0.01
    assert sf.estimated_fp_rate() < 0.01


def test_no_false_negatives_across_stages():
    sf = ScalableBloomFilter(100, 0.01)
    keys = [f"key_{i}" for i in range(5000)]
    for key in keys:
        sf.add(key)
    assert sf.num_filters > 3
    assert all(key in sf for key in keys)


def test_empirical_rate_stays_below_target_when_overfilled():
    keys, unseen = make_key_sets(8000, 20_000, seed=3)
    sf = ScalableBloomFilter(500, 0.01)                         # 16x its initial capacity
    for key in keys:
        sf.add(key)
    rate = sum(1 for q in unseen if q in sf) / len(unseen)
    assert rate < 0.012
    fixed = BloomFilter(500, 0.01)                              # same keys, fixed size
    for key in keys:
        fixed.add(key)
    assert sum(1 for q in unseen if q in fixed) / len(unseen) > 0.5


def test_memory_grows_with_stages():
    sf = ScalableBloomFilter(100, 0.01)
    before = sf.memory_bytes()
    for i in range(101):
        sf.add(f"k{i}")
    assert sf.memory_bytes() > before
    assert sf.memory_bytes() == sum(f.memory_bytes() for f in sf.filters)


def test_stage_info_fields():
    sf = ScalableBloomFilter(100, 0.01)
    for i in range(150):
        sf.add(f"k{i}")
    info = sf.stage_info()
    assert [s["stage"] for s in info] == [0, 1]
    assert info[0]["count"] == 100 and info[1]["count"] == 50
    assert all(0 < s["fill_ratio"] < 1 and s["m_bits"] > 0 for s in info)


def test_non_integer_growth_rounds_capacity_up():
    sf = ScalableBloomFilter(10, 0.01, growth=1.5)
    for i in range(26):
        sf.add(f"k{i}")
    assert sf.capacities[:3] == [10, 15, 23]


def test_empty_chain_finds_nothing():
    assert "x" not in ScalableBloomFilter(10)


def test_non_string_key_rejected():
    sf = ScalableBloomFilter(10)
    with pytest.raises(TypeError):
        sf.add(5)
    with pytest.raises(TypeError):
        _ = 5 in sf


@pytest.mark.parametrize("kwargs", [
    dict(initial_capacity=0), dict(initial_capacity=-1), dict(fp_rate=0), dict(fp_rate=1),
    dict(growth=1), dict(growth=0.5), dict(growth="2"), dict(tightening=0), dict(tightening=1),
    dict(tightening=1.5),
])
def test_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        ScalableBloomFilter(**kwargs)
