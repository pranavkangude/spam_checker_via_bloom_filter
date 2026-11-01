"""False-positive experiment lab (F-09, TRD section 8).

Three controlled experiments compare the EMPIRICAL false-positive rate of the
real BloomFilter class with the THEORETICAL rate (1 - e^(-k n / m))^k:

  vary_k      fixed m (sized for n at the target rate), k = 1 .. 14.
              Shows the U-shaped curve; optimum near k = (m/n) ln 2.
  vary_ratio  bits per item m/n in {4, 6, 8, 10, 12, 16}, k optimal for each.
  overfill    filter designed for n, then filled to {1.0, 1.5, 2.0, 3.0} x n.

Method: seeded key sets, blacklist and unseen keys disjoint (every hit on an
unseen key is a true false positive), `trials` unseen queries per point
(default 200,000, about 2,000 expected hits at p = 1%).

Each experiment builds its own temporary filters and never touches the
active filter. This module has no Flask or database code: run_experiment()
returns points whose keys are the fp_experiment_points columns
(BACKEND_SCHEMA 2.6); the caller (B's API layer) saves them.
"""
from __future__ import annotations

import math
from typing import Callable, Optional, Sequence

from core.bloom import BloomFilter
from core.params import fp_rate as theoretical_fp_rate
from core.params import optimal_k, optimal_m, validate_n_p
from services.benchmark_service import make_key_sets

KINDS = ("vary_k", "vary_ratio", "overfill")
DEFAULT_KS = tuple(range(1, 15))
DEFAULT_RATIOS = (4, 6, 8, 10, 12, 16)
DEFAULT_FACTORS = (1.0, 1.5, 2.0, 3.0)
WEB_MAX_N = 200_000
WEB_MAX_TRIALS = 500_000

POINT_COLUMNS = (
    "param_label", "m_bits", "k_hashes", "n_inserted",
    "theoretical_fp", "empirical_fp", "false_positives", "trials",
)


def _count_hits(bf: BloomFilter, unseen: list[str]) -> int:
    hits = 0
    for key in unseen:
        if key in bf:
            hits += 1
    return hits


def _point(label: str, bf: BloomFilter, n_inserted: int, unseen: list[str]) -> dict:
    hits = _count_hits(bf, unseen)
    return {
        "param_label": label,
        "m_bits": bf.size,
        "k_hashes": bf.num_hashes,
        "n_inserted": n_inserted,
        "theoretical_fp": theoretical_fp_rate(bf.size, n_inserted, bf.num_hashes),
        "empirical_fp": hits / len(unseen),
        "false_positives": hits,
        "trials": len(unseen),
    }


def analyze(points: list[dict]) -> list[dict]:
    """Empirical vs theoretical for each point.

    abs_diff = empirical - theoretical, rel_diff = abs_diff / theoretical,
    std_error = sqrt(p (1 - p) / trials) with p the theoretical rate, and
    z_score = abs_diff / std_error (how many standard errors apart).
    """
    out = []
    for pt in points:
        theo, emp, trials = pt["theoretical_fp"], pt["empirical_fp"], pt["trials"]
        abs_diff = emp - theo
        std_error = math.sqrt(max(theo * (1 - theo), 0.0) / trials)
        out.append({
            "param_label": pt["param_label"],
            "abs_diff": abs_diff,
            "rel_diff": abs_diff / theo if theo > 0 else 0.0,
            "std_error": std_error,
            "z_score": abs_diff / std_error if std_error > 0 else 0.0,
        })
    return out


# ---- the three experiments --------------------------------------------------

def _vary_k(n, fp, ks, keys, unseen, report) -> tuple[list[dict], dict]:
    m = optimal_m(n, fp)
    points = []
    for k in ks:
        bf = BloomFilter.with_size(m, k)
        for key in keys[:n]:
            bf.add(key)
        points.append(_point(f"k={k}", bf, n, unseen))
        report(points[-1]["param_label"], len(points))
    return points, {"m_bits": m, "optimal_k": optimal_k(m, n)}


def _vary_ratio(n, ratios, keys, unseen, report) -> tuple[list[dict], dict]:
    points = []
    for ratio in ratios:
        m = math.ceil(ratio * n)
        bf = BloomFilter.with_size(m, optimal_k(m, n))
        for key in keys[:n]:
            bf.add(key)
        points.append(_point(f"m/n={ratio:g}", bf, n, unseen))
        report(points[-1]["param_label"], len(points))
    return points, {}


def _overfill(n, fp, factors, keys, unseen, report) -> tuple[list[dict], dict]:
    m = optimal_m(n, fp)
    k = optimal_k(m, n)
    bf = BloomFilter.with_size(m, k)
    inserted, points = 0, []
    for factor in sorted(factors):  # one filter, filled step by step
        target = int(round(factor * n))
        for key in keys[inserted:target]:
            bf.add(key)
        inserted = target
        points.append(_point(f"{factor:g}x n", bf, inserted, unseen))
        report(points[-1]["param_label"], len(points))
    return points, {"m_bits": m, "optimal_k": k}


# ---- public entry point -----------------------------------------------------

def run_experiment(
    kind: str,
    n_items: int = 100_000,
    trials: int = 200_000,
    fp: float = 0.01,
    seed: int = 42,
    ks: Optional[Sequence[int]] = None,
    ratios: Optional[Sequence[float]] = None,
    factors: Optional[Sequence[float]] = None,
    max_n: Optional[int] = None,
    max_trials: Optional[int] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """Run one experiment.

    Returns {"kind", "n_items", "trials", "seed", "fp_target", "points",
    "analysis", "meta"}. Every point has exactly the POINT_COLUMNS keys;
    "analysis" is aligned with "points" (see analyze()); "meta" holds m_bits
    and optimal_k where that applies (vary_k, overfill).

    From the web API pass max_n=WEB_MAX_N and max_trials=WEB_MAX_TRIALS;
    bigger runs go through scripts/run_experiments.py.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    validate_n_p(n_items, fp)
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError("trials must be an integer >= 1")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if max_n is not None and n_items > max_n:
        raise ValueError(f"n {n_items} exceeds the limit of {max_n}; use scripts/run_experiments.py")
    if max_trials is not None and trials > max_trials:
        raise ValueError(f"trials {trials} exceeds the limit of {max_trials}; use scripts/run_experiments.py")

    ks = list(DEFAULT_KS if ks is None else ks)
    ratios = list(DEFAULT_RATIOS if ratios is None else ratios)
    factors = list(DEFAULT_FACTORS if factors is None else factors)
    if kind == "vary_k" and (not ks or any(not isinstance(k, int) or k < 1 for k in ks)):
        raise ValueError("ks must be a non-empty list of integers >= 1")
    if kind == "vary_ratio" and (not ratios or any(r <= 0 for r in ratios)):
        raise ValueError("ratios must be a non-empty list of numbers > 0")
    if kind == "overfill" and (not factors or any(f <= 0 for f in factors)):
        raise ValueError("factors must be a non-empty list of numbers > 0")

    total = {"vary_k": len(ks), "vary_ratio": len(ratios), "overfill": len(factors)}[kind]

    def report(label: str, done: int) -> None:
        if progress:
            progress(label, done, total)

    need = n_items if kind != "overfill" else int(round(max(factors) * n_items))
    keys, unseen = make_key_sets(max(need, 1), trials, seed)

    if kind == "vary_k":
        points, meta = _vary_k(n_items, fp, ks, keys, unseen, report)
    elif kind == "vary_ratio":
        points, meta = _vary_ratio(n_items, ratios, keys, unseen, report)
    else:
        points, meta = _overfill(n_items, fp, factors, keys, unseen, report)

    return {
        "kind": kind, "n_items": n_items, "trials": trials, "seed": seed,
        "fp_target": fp, "points": points, "analysis": analyze(points), "meta": meta,
    }
