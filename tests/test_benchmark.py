import csv

import pytest

from core.params import optimal_m
from scripts.run_benchmark import main
from services.benchmark_service import (
    BENCHMARK_COLUMNS, WEB_MAX_ITEMS, benchmark_one, make_key_sets, run_benchmark,
)

FAST = dict(repeats=2, warmup=0)


def test_key_sets_disjoint_unique_reproducible():
    bl, un = make_key_sets(2000, 3000, seed=42)
    assert len(bl) == len(set(bl)) == 2000
    assert len(un) == len(set(un)) == 3000
    assert not set(bl) & set(un)
    assert make_key_sets(2000, 3000, seed=42) == (bl, un)
    assert make_key_sets(2000, 3000, seed=7) != (bl, un)


def test_row_has_exactly_the_table_columns():
    row, details = benchmark_one(2000, 4000, 0.01, **FAST)
    assert tuple(row) == BENCHMARK_COLUMNS
    assert details["tracemalloc_set_peak_bytes"] > 0
    assert details["tracemalloc_filter_peak_bytes"] > 0


def test_row_values():
    row, _ = benchmark_one(5000, 10_000, 0.01, **FAST)
    assert row["filter_type"] == "standard"
    assert row["m_bits"] == optimal_m(5000, 0.01)
    assert row["bloom_mem_bytes"] == (row["m_bits"] + 7) // 8
    assert row["false_negatives"] == 0
    assert row["memory_ratio"] == pytest.approx(row["set_mem_bytes"] / row["bloom_mem_bytes"])
    assert row["memory_ratio"] > 5          # set is several times larger
    assert row["seed"] == 42 and row["n_queries"] == 10_000
    for col in ("bloom_insert_s", "set_insert_s", "bloom_query_s", "set_query_s"):
        assert row[col] > 0


def test_python_bloom_query_slower_than_set():
    row, _ = benchmark_one(5000, 20_000, 0.01, **FAST)
    assert row["bloom_query_s"] > row["set_query_s"]  # the honest result


def test_false_positive_rate_near_target():
    row, details = benchmark_one(20_000, 50_000, 0.01, **FAST)
    assert row["false_positives"] / row["n_queries"] < 0.02
    assert details["estimated_fp_rate"] == pytest.approx(0.01, rel=0.1)


def test_same_seed_gives_same_deterministic_results():
    a, _ = benchmark_one(3000, 6000, 0.01, seed=1, **FAST)
    b, _ = benchmark_one(3000, 6000, 0.01, seed=1, **FAST)
    for col in ("m_bits", "k_hashes", "bloom_mem_bytes", "set_mem_bytes",
                "false_positives", "false_negatives"):
        assert a[col] == b[col]


def test_counting_rows_and_memory_cost():
    result = run_benchmark([3000], queries=5000, include_counting=True, **FAST)
    std, cnt = result["rows"]
    assert (std["filter_type"], cnt["filter_type"]) == ("standard", "counting")
    assert cnt["false_negatives"] == 0
    assert cnt["bloom_mem_bytes"] == cnt["m_bits"]                       # 1 byte per counter
    assert cnt["bloom_mem_bytes"] / std["bloom_mem_bytes"] == pytest.approx(8, rel=0.01)
    assert cnt["memory_ratio"] < std["memory_ratio"]


def test_run_group_shared_and_progress_called():
    calls = []
    result = run_benchmark([1000, 2000], queries=2000,
                           progress=lambda label, d, t: calls.append((d, t)), **FAST)
    assert len(result["rows"]) == 2 and len(result["details"]) == 2
    assert {r["run_group"] for r in result["rows"]} == {result["run_group"]}
    assert calls == [(1, 2), (2, 2)]


def test_web_limit_enforced():
    with pytest.raises(ValueError, match="scripts/run_benchmark.py"):
        run_benchmark([WEB_MAX_ITEMS + 1], max_items=WEB_MAX_ITEMS)
    run_benchmark([1000], queries=500, max_items=WEB_MAX_ITEMS, **FAST)  # at or under is fine


@pytest.mark.parametrize("kwargs", [
    dict(sizes=[]), dict(sizes=[0]), dict(sizes=[-5]), dict(sizes=[10.5]),
    dict(sizes=[100], fp=0), dict(sizes=[100], fp=1),
])
def test_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        run_benchmark(**kwargs)


def test_invalid_filter_type_and_counts():
    with pytest.raises(ValueError):
        benchmark_one(100, 100, 0.01, filter_type="cuckoo")
    with pytest.raises(ValueError):
        benchmark_one(100, 0, 0.01)


def test_cli_writes_csv(tmp_path, capsys):
    out = tmp_path / "bench.csv"
    code = main(["--sizes", "1000", "--queries", "2000", "--repeats", "1", "--warmup", "0",
                 "--counting", "--csv", str(out)])
    assert code == 0
    assert "slower per query" in capsys.readouterr().out  # honesty note printed
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["filter_type"] for r in rows] == ["standard", "counting"]
    assert tuple(rows[0]) == BENCHMARK_COLUMNS
