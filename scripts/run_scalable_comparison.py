"""Scalable Bloom filter vs a fixed-size filter on the overfill experiment (F-15).

Examples (run from the project root):
    python scripts/run_scalable_comparison.py
    python scripts/run_scalable_comparison.py --n 50000 --trials 100000 --chart
    python scripts/run_scalable_comparison.py --growth 4 --tightening 0.9 --csv results/scalable.csv

--chart also draws results/charts/chart5_scalable_vs_fixed.png (needs matplotlib).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:  # lets "python scripts/run_scalable_comparison.py" find core/ and services/
    sys.path.insert(0, ROOT)

from services.scalable_service import POINT_COLUMNS, compare_overfill  # noqa: E402


def _kb(num_bytes: float) -> str:
    return f"{num_bytes / 1024:,.0f} KB"


def format_table(result: dict) -> str:
    header = (
        f"{'inserted':>10}{'x n':>6}{'fixed FP':>10}{'scalable FP':>13}{'stages':>8}"
        f"{'fixed mem':>11}{'scalable mem':>14}{'oracle mem':>12}"
    )
    lines = [header, "-" * len(header)]
    for p in result["points"]:
        lines.append(
            f"{p['n_inserted']:>10,}{p['factor']:>6g}{p['fixed_fp']:>10.3%}{p['scalable_fp']:>13.3%}"
            f"{p['stages']:>8}{_kb(p['fixed_bytes']):>11}{_kb(p['scalable_bytes']):>14}{_kb(p['oracle_bytes']):>12}"
        )
    return "\n".join(lines)


def write_csv(path: str, result: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POINT_COLUMNS)
        writer.writeheader()
        writer.writerows(result["points"])


def draw_chart(result: dict, path: str) -> str:
    """Two panels: false-positive rate and memory against the load factor."""
    from scripts.make_report_charts import BLUE, GRAY, GREEN, ORANGE, _percent, make_caption, plt

    pts = result["points"]
    xs = [p["factor"] for p in pts]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 5.2))

    left.plot(xs, [p["fixed_fp"] for p in pts], "-o", color=ORANGE, lw=2, label="Fixed-size filter")
    left.plot(xs, [p["scalable_fp"] for p in pts], "-o", color=BLUE, lw=2, label="Scalable filter")
    left.axhline(result["fp_target"], color=GRAY, ls="--", lw=1.2)
    left.annotate(f"target {result['fp_target']:.0%}", (xs[-1], result["fp_target"]), xytext=(-4, 5),
                  textcoords="offset points", ha="right", color=GRAY, fontsize=9)
    left.set_yscale("log")
    left.yaxis.set_major_formatter(plt.FuncFormatter(_percent))
    left.set_xlabel("Keys inserted as a multiple of the initial capacity n")
    left.set_ylabel("False-positive rate (log scale)")
    left.set_title("False-positive rate", fontweight="bold")
    left.legend(loc="center right")

    mb = 2 ** 20
    right.plot(xs, [p["fixed_bytes"] / mb for p in pts], "-o", color=ORANGE, lw=2, label="Fixed-size filter")
    right.plot(xs, [p["scalable_bytes"] / mb for p in pts], "-o", color=BLUE, lw=2, label="Scalable filter")
    right.plot(xs, [p["oracle_bytes"] / mb for p in pts], "--", color=GREEN, lw=1.6,
               label="Plain filter sized for the final count")
    right.set_xlabel("Keys inserted as a multiple of the initial capacity n")
    right.set_ylabel("Memory (MB)")
    right.set_title("Memory", fontweight="bold")
    right.legend(loc="upper left")
    for ax in (left, right):
        ax.grid(True, which="both", alpha=0.25)

    fig.tight_layout(rect=(0, 0.07, 1, 1))
    caption = make_caption(
        result["seed"], result["n_items"], result["trials"], result["fp_target"],
        f"Scalable filter: growth x{result['growth']:g}, tightening {result['tightening']:g}.")
    fig.text(0.01, 0.012, caption, fontsize=8, color="#444444", ha="left", va="bottom")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scalable vs fixed-size Bloom filter (overfill)")
    parser.add_argument("--n", type=int, default=100_000, help="initial capacity / designed items")
    parser.add_argument("--trials", type=int, default=200_000, help="unseen keys queried per point")
    parser.add_argument("--fp", type=float, default=0.01, help="overall false-positive target")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--growth", type=float, default=2, help="capacity multiplier per stage")
    parser.add_argument("--tightening", type=float, default=0.8, help="error ratio r between stages")
    parser.add_argument("--csv", default=os.path.join(ROOT, "results", "scalable_comparison.csv"))
    parser.add_argument("--chart", nargs="?", const=os.path.join(ROOT, "results", "charts", "chart5_scalable_vs_fixed.png"),
                        default=None, help="also draw the comparison chart (optionally give the file path)")
    args = parser.parse_args(argv)

    print(f"Scalable vs fixed: n={args.n:,} trials={args.trials:,} fp={args.fp} seed={args.seed} "
          f"growth={args.growth:g} tightening={args.tightening:g}")
    result = compare_overfill(
        args.n, args.trials, args.fp, args.seed, growth=args.growth, tightening=args.tightening,
        progress=lambda label, done, total: print(f"  [{done}/{total}] {label}", flush=True))
    print()
    print(format_table(result))
    print(f"\nGuaranteed bound for the scalable chain: {result['scalable_bound']:.3%} "
          f"(target {args.fp:.3%}). 'oracle' = plain filter sized for the final count.")
    write_csv(args.csv, result)
    print(f"Saved {len(result['points'])} row(s) to {args.csv}")
    if args.chart:
        print(f"Saved chart to {draw_chart(result, args.chart)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
