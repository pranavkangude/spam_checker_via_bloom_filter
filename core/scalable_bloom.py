"""Scalable Bloom filter (F-15, A15): a filter that grows as items arrive.

Almeida, Baquero, Preguica and Hutchison (2007), "Scalable Bloom Filters".

A plain Bloom filter must be sized for an expected number of items; beyond
that its false-positive rate climbs fast (see the overfill experiment). A
scalable filter is a CHAIN of ordinary filters:

  * insertions always go to the newest filter;
  * when it holds as many items as it was sized for, a new, larger one is
    appended (capacity grows by `growth`, default x2);
  * lookups ask every filter and say "present" if any does.

Each new filter gets a TIGHTER error rate, p_i = p0 * r^i with r < 1
(`tightening`, default 0.8). The false-positive rates then form a geometric
series, so the whole chain stays below the target:

    P  <=  sum_i p_i  =  p0 / (1 - r)         choose  p0 = target * (1 - r)

Costs (be honest in the report): the first stage is tighter than a plain
filter at the same target, so it uses more bits per item; every lookup must
test every stage (O(k * stages)); and the memory of the newest stage is
allocated in full as soon as the stage is opened.
"""
from __future__ import annotations

import math

from core.bloom import BloomFilter
from core.params import validate_n_p


class ScalableBloomFilter:
    """Chain of BloomFilter stages with growing capacity and tightening error.

    Attributes:
        fp_rate (float): overall false-positive target for the whole chain.
        count (int): number of add() calls (the caller avoids duplicates).
        filters (list[BloomFilter]): the stages, oldest first.
    """

    def __init__(
        self,
        initial_capacity: int = 1000,
        fp_rate: float = 0.01,
        growth: float = 2,
        tightening: float = 0.8,
    ):
        validate_n_p(initial_capacity, fp_rate)
        if isinstance(growth, bool) or not isinstance(growth, (int, float)) or not growth > 1:
            raise ValueError("growth must be a number greater than 1")
        if isinstance(tightening, bool) or not isinstance(tightening, (int, float)) or not (0 < tightening < 1):
            raise ValueError("tightening must satisfy 0 < tightening < 1")
        self.initial_capacity = initial_capacity
        self.fp_rate = fp_rate
        self.growth = growth
        self.tightening = tightening
        self.first_stage_fp = fp_rate * (1 - tightening)   # p0
        self.count = 0
        self.filters: list[BloomFilter] = []
        self.capacities: list[int] = []
        self.stage_fp_targets: list[float] = []
        self._open_stage()

    # ---- growth ------------------------------------------------------------

    def _open_stage(self) -> None:
        i = len(self.filters)
        capacity = math.ceil(self.initial_capacity * self.growth ** i)
        stage_fp = self.first_stage_fp * self.tightening ** i
        self.filters.append(BloomFilter(capacity, stage_fp))
        self.capacities.append(capacity)
        self.stage_fp_targets.append(stage_fp)

    @property
    def num_filters(self) -> int:
        return len(self.filters)

    # ---- operations --------------------------------------------------------

    def add(self, key: str) -> None:
        """Insert into the newest stage, opening a new one when it is full. O(k)."""
        if self.filters[-1].count >= self.capacities[-1]:
            self._open_stage()
        self.filters[-1].add(key)
        self.count += 1

    def __contains__(self, key: str) -> bool:
        """Present if any stage says so. O(k * stages)."""
        return any(key in stage for stage in self.filters)

    # ---- statistics --------------------------------------------------------

    def estimated_fp_rate(self) -> float:
        """Chance that a never-inserted key passes at least one stage, using real counts."""
        pass_none = 1.0
        for stage in self.filters:
            pass_none *= 1.0 - stage.estimated_fp_rate()
        return 1.0 - pass_none

    def fp_bound(self) -> float:
        """Upper bound promised by the construction: sum of the stage targets (<= fp_rate)."""
        return sum(self.stage_fp_targets)

    def memory_bytes(self) -> int:
        """Bytes of all stage bit arrays (the newest stage is fully allocated)."""
        return sum(stage.memory_bytes() for stage in self.filters)

    def stage_info(self) -> list[dict]:
        return [
            {
                "stage": i,
                "capacity": self.capacities[i],
                "fp_target": self.stage_fp_targets[i],
                "m_bits": stage.size,
                "k_hashes": stage.num_hashes,
                "count": stage.count,
                "fill_ratio": stage.fill_ratio(),
                "memory_bytes": stage.memory_bytes(),
            }
            for i, stage in enumerate(self.filters)
        ]
