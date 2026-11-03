"""Scalable vs fixed-size Bloom filter on the overfill experiment (F-15, A15).

Both filters start sized for n items at the same target rate and receive the
same keys, up to a multiple of n (default 1x ... 10x). At every step we
measure the false-positive rate on unseen keys and the memory used.

A third column, "oracle", is the memory a plain filter would need if n had
been known in advance (sized for the number of items inserted so far). It
shows what the scalable filter pays for not knowing n.

No Flask or database code; the script scripts/run_scalable_comparison.py
prints and saves the result.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from core.bloom import BloomFilter
from core.params import fp_rate as theoretical_fp
from core.params import optimal_m, validate_n_p
from core.scalable_bloom import ScalableBloomFilter
from services.benchmark_service import make_key_sets

DEFAULT_FACTORS = (1.0, 1.5, 2.0, 3.0, 5.0, 10.0)

POINT_COLUMNS = (
    "factor", "n_inserted", "trials",
    "fixed_fp", "fixed_theoretical_fp", "fixed_bytes",
    "scalable_fp", "scalable_estimated_fp", "scalable_bytes", "stages",
    "oracle_bytes",
)


def _hits(structure, unseen: list[str]) -> int:
    found = 0
    for key in unseen:
        if key in structure:
            found += 1
    return found


def compare_overfill(
    n_items: int = 100_000,
    trials: int = 200_000,
    fp: float = 0.01,
    seed: int = 42,
    factors: Optional[Sequence[float]] = None,
    growth: float = 2,
    tightening: float = 0.8,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """Fill a fixed and a scalable filter step by step; return one point per factor."""
    validate_n_p(n_items, fp)
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError("trials must be an integer >= 1")
    factors = sorted(DEFAULT_FACTORS if factors is None else factors)
    if not factors or any(f <= 0 for f in factors):
        raise ValueError("factors must be a non-empty list of numbers > 0")

    keys, unseen = make_key_sets(max(int(round(factors[-1] * n_items)), 1), trials, seed)
    fixed = BloomFilter(n_items, fp)
    scalable = ScalableBloomFilter(n_items, fp, growth, tightening)

    points, inserted = [], 0
    for index, factor in enumerate(factors, start=1):
        target = int(round(factor * n_items))
        for key in keys[inserted:target]:
            fixed.add(key)
            scalable.add(key)
        inserted = target
        points.append({
            "factor": factor,
            "n_inserted": inserted,
            "trials": trials,
            "fixed_fp": _hits(fixed, unseen) / trials,
            "fixed_theoretical_fp": theoretical_fp(fixed.size, inserted, fixed.num_hashes),
            "fixed_bytes": fixed.memory_bytes(),
            "scalable_fp": _hits(scalable, unseen) / trials,
            "scalable_estimated_fp": scalable.estimated_fp_rate(),
            "scalable_bytes": scalable.memory_bytes(),
            "stages": scalable.num_filters,
            "oracle_bytes": (optimal_m(max(inserted, 1), fp) + 7) // 8,
        })
        if progress:
            progress(f"{factor:g}x n", index, len(factors))

    return {
        "n_items": n_items, "trials": trials, "seed": seed, "fp_target": fp,
        "growth": growth, "tightening": tightening,
        "scalable_bound": scalable.fp_bound(), "points": points,
        "stage_info": scalable.stage_info(),
    }
