"""Command-line benchmark: Bloom filter vs. Python set (F-08).

Use this for large runs (over 200,000 items); the web page limits itself to
200,000 so it never freezes.

Examples (run from the project root):
    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --sizes 10000 100000 500000 1000000
    python scripts/run_benchmark.py --sizes 100000 --counting --csv results/bench.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:  # lets "python scripts/run_benchmark.py" find core/ and services/
    sys.path.insert(0, ROOT)

from services.benchmark_service import BENCHMARK_COLUMNS, run_benchmark  # noqa: E402

HONESTY_NOTE = (
    "Note: a pure-Python Bloom filter is slower per query than a native set;\n"
    "its advantage is memory. The ratio column is set memory / filter memory."
)


def format_table(rows: list[dict]) -> str:
    header = (
        f"{'type':<9}{'n':>10}{'m (bits)':>13}{'k':>3}{'bloom MB':>10}{'set MB':>9}"
        f"{'ratio':>7}{'b.ins s':>9}{'s.ins s':>9}{'b.qry s':>9}{'s.qry s':>9}"
        f"{'FP':>8}{'FN':>4}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['filter_type']:<9}{r['n_items']:>10,}{r['m_bits']:>13,}{r['k_hashes']:>3}"
            f"{r['bloom_mem_bytes'] / 2**20:>10.2f}{r['set_mem_bytes'] / 2**20:>9.2f}"
            f"{r['memory_ratio']:>7.1f}{r['bloom_insert_s']:>9.3f}{r['set_insert_s']:>9.3f}"
            f"{r['bloom_query_s']:>9.3f}{r['set_query_s']:>9.3f}"
            f"{r['false_positives']:>8,}{r['false_negatives']:>4}"
        )
    return "\n".join(lines)


def write_csv(path: str, rows: list[dict]) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Bloom filter vs Python set")
    parser.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000, 500_000, 1_000_000])
    parser.add_argument("--queries", type=int, default=200_000, help="unseen keys to query")
    parser.add_argument("--fp", type=float, default=0.01, help="target false-positive rate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=5, help="timed runs (median is reported)")
    parser.add_argument("--warmup", type=int, default=1, help="discarded warm-up runs")
    parser.add_argument("--counting", action="store_true", help="also benchmark the counting filter")
    parser.add_argument("--csv", default=os.path.join(ROOT, "results", "benchmark.csv"))
    args = parser.parse_args(argv)

    def progress(label: str, done: int, total: int) -> None:
        print(f"  [{done}/{total}] finished {label}", flush=True)

    print(f"Benchmark: sizes={args.sizes} queries={args.queries:,} fp={args.fp} seed={args.seed}")
    result = run_benchmark(
        args.sizes, args.queries, args.fp, args.counting, args.seed,
        args.repeats, args.warmup, progress=progress,
    )
    print()
    print(format_table(result["rows"]))
    print()
    print(HONESTY_NOTE)
    write_csv(args.csv, result["rows"])
    print(f"\nSaved {len(result['rows'])} row(s) to {args.csv}")
    if any(r["false_negatives"] for r in result["rows"]):
        print("ERROR: false negatives found (must be 0)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
