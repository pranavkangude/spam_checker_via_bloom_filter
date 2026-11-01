"""Benchmark: Bloom filter vs. Python set (F-08, TRD section 8).

Methodology (so the numbers are defensible in the report):
  1. Fixed seed. Keys come from a private random.Random(seed), so the global
     random state is untouched and the same seed gives the same key sets.
  2. Blacklist keys ("bl_...") and unseen keys ("un_...") never overlap, so
     every "found" for an unseen key is a true false positive.
  3. Timing uses time.perf_counter(); each measurement is run `warmup`
     (default 1) times and discarded, then `repeats` (default 5) times, and
     the median is reported. The garbage collector is paused while timing.
  4. Memory: Bloom filter = len(bits) bytes (exact). Set =
     sys.getsizeof(set) + sum(sys.getsizeof(key)). A tracemalloc peak while
     building each structure is recorded as a cross-check.
  5. A pure-Python Bloom query is SLOWER than a native set lookup; the win
     is memory. The numbers show both honestly.

This module has no Flask or database code. run_benchmark() returns rows whose
keys are the columns of the benchmark_runs table (BACKEND_SCHEMA 2.5); the
caller (B's API layer) saves them.
"""
from __future__ import annotations

import gc
import random
import statistics
import sys
import time
import tracemalloc
import uuid
from typing import Callable, Iterator, Optional

from core.bloom import BloomFilter
from core.counting_bloom import CountingBloomFilter
from core.params import validate_n_p

WEB_MAX_ITEMS = 200_000  # larger runs go through scripts/run_benchmark.py

BENCHMARK_COLUMNS = (
    "run_group", "filter_type", "n_items", "n_queries", "fp_target", "m_bits",
    "k_hashes", "bloom_mem_bytes", "set_mem_bytes", "memory_ratio",
    "bloom_insert_s", "set_insert_s", "bloom_query_s", "set_query_s",
    "false_negatives", "false_positives", "seed",
)

_FILTER_CLASSES = {"standard": BloomFilter, "counting": CountingBloomFilter}


# ---- key generation ---------------------------------------------------------

def _keys(prefix: str, count: int, rng: random.Random) -> Iterator[str]:
    for i in range(count):
        yield f"{prefix}_{i}_{rng.getrandbits(40):010x}"


def make_key_sets(n_items: int, n_queries: int, seed: int) -> tuple[list[str], list[str]]:
    """(blacklist_keys, unseen_keys): unique, disjoint, reproducible from seed."""
    rng = random.Random(seed)
    blacklist = list(_keys("bl", n_items, rng))
    unseen = list(_keys("un", n_queries, rng))
    return blacklist, unseen


# ---- measuring helpers ------------------------------------------------------

def _median_time(fn: Callable[[], object], repeats: int, warmup: int) -> float:
    """Median seconds of `repeats` timed runs after `warmup` discarded runs."""
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        gc.collect()
        gc.disable()
        try:
            start = time.perf_counter()
            fn()
            times.append(time.perf_counter() - start)
        finally:
            gc.enable()
    return statistics.median(times)


def _tracemalloc_peak(build: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        obj = build()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del obj
    return peak


def _set_memory(py_set: set) -> int:
    return sys.getsizeof(py_set) + sum(sys.getsizeof(k) for k in py_set)


# ---- one measurement --------------------------------------------------------

def benchmark_one(
    n_items: int,
    n_queries: int,
    fp: float,
    filter_type: str = "standard",
    seed: int = 42,
    repeats: int = 5,
    warmup: int = 1,
    run_group: Optional[str] = None,
) -> tuple[dict, dict]:
    """Benchmark one size. Returns (row, details).

    row     : keys are exactly BENCHMARK_COLUMNS (ready for benchmark_runs).
    details : extra cross-checks (tracemalloc peaks, repeats, warmup).
    """
    if filter_type not in _FILTER_CLASSES:
        raise ValueError("filter_type must be 'standard' or 'counting'")
    if n_queries < 1 or repeats < 1 or warmup < 0:
        raise ValueError("n_queries and repeats must be >= 1, warmup >= 0")
    validate_n_p(n_items, fp)
    cls = _FILTER_CLASSES[filter_type]
    blacklist, unseen = make_key_sets(n_items, n_queries, seed)

    # --- insert timing (fresh structure every run) ---
    built: dict = {}

    def build_filter():
        bf = cls(n_items, fp)
        add = bf.add
        for key in blacklist:
            add(key)
        built["bf"] = bf

    def build_set():
        s: set = set()
        add = s.add
        for key in blacklist:
            add(key)
        built["set"] = s

    bloom_insert_s = _median_time(build_filter, repeats, warmup)
    set_insert_s = _median_time(build_set, repeats, warmup)
    bf: BloomFilter = built["bf"]
    py_set: set = built["set"]

    # --- query timing (unseen keys against the filled structures) ---
    hits: dict = {}

    def query_filter():
        found = 0
        for key in unseen:
            if key in bf:
                found += 1
        hits["bloom"] = found

    def query_set():
        found = 0
        for key in unseen:
            if key in py_set:
                found += 1
        hits["set"] = found

    bloom_query_s = _median_time(query_filter, repeats, warmup)
    set_query_s = _median_time(query_set, repeats, warmup)

    false_positives = hits["bloom"]
    false_negatives = sum(1 for key in blacklist if key not in bf)
    assert hits["set"] == 0, "key sets are not disjoint"

    # --- memory ---
    bloom_mem = bf.memory_bytes()
    set_mem = _set_memory(py_set)

    details = {
        "filter_type": filter_type,
        "n_items": n_items,
        "repeats": repeats,
        "warmup": warmup,
        "tracemalloc_set_peak_bytes": _tracemalloc_peak(
            lambda: set(_keys("bl", n_items, random.Random(seed)))
        ),
        "tracemalloc_filter_peak_bytes": _tracemalloc_peak(lambda: cls(n_items, fp)),
        "estimated_fp_rate": bf.estimated_fp_rate(),
        "empirical_fp_rate": false_positives / n_queries,
    }
    row = {
        "run_group": run_group or str(uuid.uuid4()),
        "filter_type": filter_type,
        "n_items": n_items,
        "n_queries": n_queries,
        "fp_target": fp,
        "m_bits": bf.size,
        "k_hashes": bf.num_hashes,
        "bloom_mem_bytes": bloom_mem,
        "set_mem_bytes": set_mem,
        "memory_ratio": set_mem / bloom_mem,
        "bloom_insert_s": bloom_insert_s,
        "set_insert_s": set_insert_s,
        "bloom_query_s": bloom_query_s,
        "set_query_s": set_query_s,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "seed": seed,
    }
    return row, details


# ---- full run ---------------------------------------------------------------

def run_benchmark(
    sizes: list[int],
    queries: int = 200_000,
    fp: float = 0.01,
    include_counting: bool = False,
    seed: int = 42,
    repeats: int = 5,
    warmup: int = 1,
    max_items: Optional[int] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """Benchmark every size in `sizes`.

    Returns {"run_group": str, "rows": [...], "details": [...]} where each row
    has the benchmark_runs columns. Pass max_items=WEB_MAX_ITEMS from the web
    API to refuse large runs. progress(label, done, total) is called after
    each finished measurement.
    """
    if not sizes:
        raise ValueError("sizes must not be empty")
    for n in sizes:
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError("every size must be an integer >= 1")
        if max_items is not None and n > max_items:
            raise ValueError(
                f"size {n} exceeds the limit of {max_items}; use scripts/run_benchmark.py"
            )
    validate_n_p(sizes[0], fp)

    run_group = str(uuid.uuid4())
    types = ["standard"] + (["counting"] if include_counting else [])
    total = len(sizes) * len(types)
    rows, details, done = [], [], 0
    for n in sizes:
        for filter_type in types:
            row, extra = benchmark_one(
                n, queries, fp, filter_type, seed, repeats, warmup, run_group
            )
            rows.append(row)
            details.append(extra)
            done += 1
            if progress:
                progress(f"{filter_type} n={n}", done, total)
    return {"run_group": run_group, "rows": rows, "details": details}
