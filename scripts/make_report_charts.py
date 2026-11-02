"""Report charts as PNG files (F-16, A12).

Runs the experiments and memory measurements itself (everything is seeded, so
the same arguments always give the same charts) and saves four PNGs:

    chart1_fp_vs_k.png            empirical vs theoretical FP rate against k
    chart2_fp_vs_overfill.png     FP rate as the filter is filled past capacity
    chart3_memory_vs_n.png        memory of Bloom / counting filter vs a Python set
    chart4_fp_vs_bits_per_item.png  FP rate against bits per item (m / n)

Every caption states n, trials and seed. Needs matplotlib:  pip install matplotlib

Examples (run from the project root):
    python scripts/make_report_charts.py
    python scripts/make_report_charts.py --n 100000 --trials 200000 --seed 42
    python scripts/make_report_charts.py --n 20000 --trials 50000 --outdir results/quick
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:  # lets "python scripts/make_report_charts.py" find core/ and services/
    sys.path.insert(0, ROOT)

try:
    import matplotlib
    matplotlib.use("Agg")  # draw to files only; works without a display
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover
    raise ImportError("matplotlib is required for the charts: pip install matplotlib") from exc

from core.estimates import set_memory_estimate  # noqa: E402
from core.params import fp_rate as theoretical_fp  # noqa: E402
from core.params import optimal_m  # noqa: E402
from services.benchmark_service import make_key_sets  # noqa: E402
from services.experiment_service import run_experiment  # noqa: E402

DEFAULT_SIZES = (10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)
BLUE, ORANGE, GREEN, GRAY = "#0072B2", "#D55E00", "#009E73", "#777777"
FILES = {
    "fp_vs_k": "chart1_fp_vs_k.png",
    "fp_vs_overfill": "chart2_fp_vs_overfill.png",
    "memory_vs_n": "chart3_memory_vs_n.png",
    "fp_vs_bits_per_item": "chart4_fp_vs_bits_per_item.png",
}


# ---- helpers ----------------------------------------------------------------

def make_caption(seed: int, n: Optional[int] = None, trials: Optional[int] = None,
                 fp: Optional[float] = None, note: str = "") -> str:
    """Caption text stating n, trials and seed (plus the target rate)."""
    parts = []
    parts.append(f"n = {n:,}" if n is not None else "n = see x-axis")
    parts.append(f"trials = {trials:,} unseen keys" if trials is not None else "trials: none (memory is measured exactly)")
    parts.append(f"seed = {seed}")
    if fp is not None:
        parts.append(f"target p = {fp:.0%}")
    return ", ".join(parts) + (f". {note}" if note else "")


def _percent(value: float, _pos=None) -> str:
    pct = value * 100
    return f"{pct:.0f}%" if pct >= 10 else f"{pct:.2g}%"


_PERCENT_TICKS = (0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)
_MEMORY_TICKS = (2 ** 10, 10 * 2 ** 10, 100 * 2 ** 10, 2 ** 20, 10 * 2 ** 20, 100 * 2 ** 20, 2 ** 30)  # 1 KB .. 1 GB


def _log_axis_ticks(ax, candidates, formatter) -> None:
    """Label a log y-axis only at round values inside the visible range (no crowded minor labels)."""
    low, high = ax.get_ylim()
    ticks = [t for t in candidates if low <= t <= high]
    ax.set_yticks(ticks)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(formatter))
    ax.yaxis.set_minor_formatter(plt.NullFormatter())
    ax.set_ylim(low, high)


def _mb(value: float, _pos=None) -> str:
    mb = value / 2 ** 20
    if mb >= 1024:
        return f"{mb / 1024:.3g} GB"
    return f"{mb:.3g} MB" if mb >= 0.1 else f"{value / 1024:.3g} KB"


def _finish(fig, ax, path: str, title: str, caption: str) -> str:
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.text(0.01, 0.012, caption, fontsize=8, color="#444444", ha="left", va="bottom", wrap=True)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _error_bars(result: dict) -> list[float]:
    return [1.96 * a["std_error"] for a in result["analysis"]]  # 95% interval


# ---- the charts -------------------------------------------------------------

def chart_fp_vs_k(result: dict, path: str, caption: str) -> str:
    pts = result["points"]
    ks = [p["k_hashes"] for p in pts]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.plot(ks, [p["theoretical_fp"] for p in pts], "-", color=ORANGE, lw=2, label="Theoretical (1 - e^(-kn/m))^k")
    ax.errorbar(ks, [p["empirical_fp"] for p in pts], yerr=_error_bars(result), fmt="o", color=BLUE,
                capsize=3, ms=5, label="Empirical (95% interval)")
    opt = result["meta"].get("optimal_k")
    if opt:
        ax.axvline(opt, color=GRAY, ls="--", lw=1.2)
        ax.annotate(f"optimal k = {opt}", (opt, ax.get_ylim()[1]), xytext=(6, -16),
                    textcoords="offset points", color=GRAY, fontsize=9)
    ax.set_yscale("log")
    _log_axis_ticks(ax, _PERCENT_TICKS, _percent)
    ax.set_xticks(ks)
    ax.set_xlabel("Number of hash functions k (m fixed)")
    ax.set_ylabel("False-positive rate (log scale)")
    ax.legend()
    return _finish(fig, ax, path, "False-positive rate vs number of hash functions", caption)


def chart_fp_vs_overfill(result: dict, path: str, caption: str) -> str:
    pts, n = result["points"], result["n_items"]
    m, k = result["meta"]["m_bits"], result["meta"]["optimal_k"]
    xs = [p["n_inserted"] / n for p in pts]
    lo, hi = min(xs + [0.5]) * 0.9, max(xs) * 1.08
    curve_x = [lo + i * (hi - lo) / 100 for i in range(101)]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.plot(curve_x, [theoretical_fp(m, int(x * n), k) for x in curve_x], "-", color=ORANGE, lw=2, label="Theoretical")
    ax.errorbar(xs, [p["empirical_fp"] for p in pts], yerr=_error_bars(result), fmt="o", color=BLUE,
                capsize=3, ms=6, label="Empirical (95% interval)")
    ax.axhline(result["fp_target"], color=GRAY, ls="--", lw=1.2)
    ax.annotate(f"target {result['fp_target']:.0%}", (hi, result["fp_target"]), xytext=(-4, 4),
                textcoords="offset points", ha="right", color=GRAY, fontsize=9)
    ax.axvline(1.0, color=GRAY, ls=":", lw=1.2)
    ax.annotate("designed capacity", (1.0, ax.get_ylim()[1]), xytext=(5, -14),
                textcoords="offset points", color=GRAY, fontsize=9)
    for x, p in zip(xs, pts):
        offset = (-30, 8) if p["empirical_fp"] < 0.03 else (6, -12)  # keep labels inside the axes
        ax.annotate(_percent(p["empirical_fp"]), (x, p["empirical_fp"]), xytext=offset,
                    textcoords="offset points", fontsize=8, color=BLUE)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_percent))
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Items inserted as a multiple of designed capacity n")
    ax.set_ylabel("False-positive rate")
    ax.legend(loc="center right", bbox_to_anchor=(0.99, 0.2))
    return _finish(fig, ax, path, "False-positive rate when the filter is over-filled", caption)


def chart_fp_vs_bits_per_item(result: dict, path: str, caption: str) -> str:
    pts = result["points"]
    ratios = [p["m_bits"] / p["n_inserted"] for p in pts]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.plot(ratios, [p["theoretical_fp"] for p in pts], "-", color=ORANGE, lw=2, label="Theoretical (optimal k each)")
    ax.errorbar(ratios, [p["empirical_fp"] for p in pts], yerr=_error_bars(result), fmt="o", color=BLUE,
                capsize=3, ms=5, label="Empirical (95% interval)")
    for r, p in zip(ratios, pts):
        ax.annotate(f"k={p['k_hashes']}", (r, p["empirical_fp"]), xytext=(6, 5),
                    textcoords="offset points", fontsize=8, color=GRAY)
    ax.set_yscale("log")
    _log_axis_ticks(ax, _PERCENT_TICKS, _percent)
    ax.set_xticks(ratios)
    ax.set_xlabel("Bits per item (m / n)")
    ax.set_ylabel("False-positive rate (log scale)")
    ax.legend()
    return _finish(fig, ax, path, "False-positive rate vs bits per item", caption)


def measure_memory(sizes, fp: float = 0.01, seed: int = 42) -> list[dict]:
    """Exact filter bytes and measured / estimated Python-set bytes for each n."""
    import sys as _sys
    from statistics import mean

    biggest = max(sizes)
    keys, _ = make_key_sets(biggest, 1, seed)
    rows = []
    for n in sorted(sizes):
        subset = keys[:n]
        py_set = set(subset)
        m = optimal_m(n, fp)
        rows.append({
            "n": n,
            "bloom_bytes": (m + 7) // 8,
            "counting_bytes": m,
            "set_bytes": _sys.getsizeof(py_set) + sum(_sys.getsizeof(k) for k in subset),
            "set_estimate_bytes": set_memory_estimate(n, mean(len(k) for k in subset)),
        })
    return rows


def chart_memory_vs_n(rows: list[dict], path: str, caption: str) -> str:
    ns = [r["n"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.plot(ns, [r["set_bytes"] for r in rows], "-o", color=ORANGE, lw=2.5, ms=6, label="Python set (measured)")
    ax.plot(ns, [r["set_estimate_bytes"] for r in rows], "--", color="#222222", lw=1.3, zorder=5,
            label="Python set (estimate from core.estimates)")
    ax.plot(ns, [r["counting_bytes"] for r in rows], "-s", color=GREEN, lw=2, ms=5, label="Counting Bloom filter")
    ax.plot(ns, [r["bloom_bytes"] for r in rows], "-o", color=BLUE, lw=2, ms=5, label="Bloom filter")
    last = rows[-1]
    ax.text(0.97, 0.06,
            f"At n = {last['n']:,}:\n"
            f"set is {last['set_bytes'] / last['bloom_bytes']:.0f}x larger than the Bloom filter\n"
            f"counting filter is {last['counting_bytes'] / last['bloom_bytes']:.0f}x larger than the Bloom filter",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="#333333",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#cccccc"))
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(top=max(r["set_bytes"] for r in rows) * 12)  # head-room so the legend never covers data
    _log_axis_ticks(ax, _MEMORY_TICKS, _mb)
    ax.set_xticks(ns)
    ax.set_xticklabels([f"{n:,}" for n in ns], rotation=30, ha="right")
    ax.set_xlabel("Number of items n")
    ax.set_ylabel("Memory (log scale)")
    ax.legend(loc="upper left")
    return _finish(fig, ax, path, "Memory: Bloom filter vs Python set", caption)


# ---- driver -----------------------------------------------------------------

def generate_all(
    outdir: str,
    n: int = 100_000,
    trials: int = 200_000,
    fp: float = 0.01,
    seed: int = 42,
    sizes=DEFAULT_SIZES,
    progress: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """Create all four charts in outdir; returns {chart name: file path}."""
    say = progress or (lambda msg: None)
    paths = {}

    say("running vary_k experiment")
    res = run_experiment("vary_k", n, trials, fp, seed)
    paths["fp_vs_k"] = chart_fp_vs_k(res, os.path.join(outdir, FILES["fp_vs_k"]),
                                     make_caption(seed, n, trials, fp, "m fixed at the optimum for n and p."))

    say("running overfill experiment")
    res = run_experiment("overfill", n, trials, fp, seed)
    paths["fp_vs_overfill"] = chart_fp_vs_overfill(
        res, os.path.join(outdir, FILES["fp_vs_overfill"]),
        make_caption(seed, n, trials, fp, "Filter designed for n items; k optimal."))

    say("running vary_ratio experiment")
    res = run_experiment("vary_ratio", n, trials, fp, seed)
    paths["fp_vs_bits_per_item"] = chart_fp_vs_bits_per_item(
        res, os.path.join(outdir, FILES["fp_vs_bits_per_item"]),
        make_caption(seed, n, trials, None, "k optimal for each ratio."))

    say("measuring memory")
    rows = measure_memory(sizes, fp, seed)
    paths["memory_vs_n"] = chart_memory_vs_n(
        rows, os.path.join(outdir, FILES["memory_vs_n"]),
        make_caption(seed, None, None, fp, "Keys are strings of 15-21 characters; set memory = getsizeof(set) + sum of getsizeof(key)."))
    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the report charts (PNG)")
    parser.add_argument("--n", type=int, default=100_000, help="designed items for the experiments")
    parser.add_argument("--trials", type=int, default=200_000, help="unseen keys per point")
    parser.add_argument("--fp", type=float, default=0.01, help="target false-positive rate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES), help="n values for the memory chart")
    parser.add_argument("--outdir", default=os.path.join(ROOT, "results", "charts"))
    args = parser.parse_args(argv)

    print(f"Charts: n={args.n:,} trials={args.trials:,} fp={args.fp} seed={args.seed}")
    paths = generate_all(args.outdir, args.n, args.trials, args.fp, args.seed, args.sizes,
                         progress=lambda msg: print(f"  {msg} ...", flush=True))
    print("\nSaved:")
    for path in paths.values():
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
