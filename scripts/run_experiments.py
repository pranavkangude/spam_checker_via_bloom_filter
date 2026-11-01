"""Command-line false-positive experiments (F-09).

Use this for runs above the web limits (n > 200,000 or trials > 500,000).
Results are printed and saved as CSV files for the report charts.

Examples (run from the project root):
    python scripts/run_experiments.py --kind all
    python scripts/run_experiments.py --kind vary_k --n 100000 --trials 200000
    python scripts/run_experiments.py --kind overfill --n 50000 --seed 7 --outdir results
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:  # lets "python scripts/run_experiments.py" find core/ and services/
    sys.path.insert(0, ROOT)

from services.experiment_service import KINDS, POINT_COLUMNS, run_experiment  # noqa: E402

CSV_COLUMNS = POINT_COLUMNS + ("abs_diff", "rel_diff", "std_error", "z_score")


def format_table(result: dict) -> str:
    header = (
        f"{'param':<10}{'m (bits)':>12}{'k':>4}{'inserted':>10}"
        f"{'theoretical':>13}{'empirical':>11}{'FP':>8}{'rel diff':>10}{'z':>7}"
    )
    lines = [header, "-" * len(header)]
    for pt, an in zip(result["points"], result["analysis"]):
        lines.append(
            f"{pt['param_label']:<10}{pt['m_bits']:>12,}{pt['k_hashes']:>4}{pt['n_inserted']:>10,}"
            f"{pt['theoretical_fp']:>13.5f}{pt['empirical_fp']:>11.5f}{pt['false_positives']:>8,}"
            f"{an['rel_diff']:>+10.1%}{an['z_score']:>+7.1f}"
        )
    return "\n".join(lines)


def write_csv(path: str, result: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for pt, an in zip(result["points"], result["analysis"]):
            writer.writerow({**pt, **{k: an[k] for k in CSV_COLUMNS[len(POINT_COLUMNS):]}})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="False-positive experiments for the Bloom filter")
    parser.add_argument("--kind", choices=KINDS + ("all",), default="all")
    parser.add_argument("--n", type=int, default=100_000, help="designed number of items")
    parser.add_argument("--trials", type=int, default=200_000, help="unseen keys queried per point")
    parser.add_argument("--fp", type=float, default=0.01, help="target false-positive rate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--outdir", default=os.path.join(ROOT, "results"))
    args = parser.parse_args(argv)

    kinds = KINDS if args.kind == "all" else (args.kind,)
    for kind in kinds:
        print(f"\n=== {kind}: n={args.n:,} trials={args.trials:,} fp={args.fp} seed={args.seed} ===")
        result = run_experiment(
            kind, args.n, args.trials, args.fp, args.seed,
            progress=lambda label, done, total: print(f"  [{done}/{total}] {label}", flush=True),
        )
        print()
        print(format_table(result))
        if result["meta"].get("optimal_k"):
            print(f"\nOptimal k for m={result['meta']['m_bits']:,}, n={args.n:,}: {result['meta']['optimal_k']}")
        path = os.path.join(args.outdir, f"experiment_{kind}.csv")
        write_csv(path, result)
        print(f"Saved {len(result['points'])} point(s) to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
