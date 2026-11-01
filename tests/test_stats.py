"""Statistical tests (A10): empirical false-positive rate vs theory.

Rule (PRD section 8, TRD section 9): at n >= 50,000 the empirical rate must be
within +/- 30% (relative) of the theoretical rate, with zero false negatives.
Key sets are seeded, so these tests are deterministic: they either always
pass or always fail for a given implementation.
"""
import math

import pytest

from core.bloom import BloomFilter
from core.counting_bloom import CountingBloomFilter
from core.params import fp_rate as theoretical_fp
from services.benchmark_service import make_key_sets
from services.experiment_service import run_experiment

N = 50_000
TRIALS = 200_000
SEED = 42
TOLERANCE = 0.30


def measure(filter_cls, n, p, trials, seed):
    """Fill a filter with n keys; return (filter, false_positives, false_negatives)."""
    keys, unseen = make_key_sets(n, trials, seed)
    bf = filter_cls(n, p)
    for key in keys:
        bf.add(key)
    false_positives = sum(1 for q in unseen if q in bf)
    false_negatives = sum(1 for key in keys if key not in bf)
    return bf, false_positives, false_negatives


def relative_error(empirical, theoretical):
    return abs(empirical - theoretical) / theoretical


@pytest.fixture(scope="module")
def standard_run():
    return measure(BloomFilter, N, 0.01, TRIALS, SEED)


def test_no_false_negatives_at_50k(standard_run):
    _, _, false_negatives = standard_run
    assert false_negatives == 0


def test_empirical_within_30_percent_of_theory(standard_run):
    bf, hits, _ = standard_run
    empirical = hits / TRIALS
    theoretical = theoretical_fp(bf.size, N, bf.num_hashes)
    assert relative_error(empirical, theoretical) < TOLERANCE


def test_empirical_within_30_percent_of_target(standard_run):
    _, hits, _ = standard_run
    assert relative_error(hits / TRIALS, 0.01) < TOLERANCE


def test_estimated_fp_rate_method_matches_formula(standard_run):
    bf, _, _ = standard_run
    assert bf.estimated_fp_rate() == pytest.approx(theoretical_fp(bf.size, N, bf.num_hashes))
    assert bf.estimated_fp_rate() == pytest.approx(0.01, rel=0.05)


def test_fill_ratio_about_half_at_capacity(standard_run):
    bf, _, _ = standard_run
    assert bf.fill_ratio() == pytest.approx(0.5, abs=0.02)


@pytest.mark.parametrize("seed", [1, 7, 42, 2026])
def test_holds_for_several_seeds(seed):
    bf, hits, fn = measure(BloomFilter, N, 0.01, TRIALS, seed)
    assert fn == 0
    assert relative_error(hits / TRIALS, theoretical_fp(bf.size, N, bf.num_hashes)) < TOLERANCE


@pytest.mark.parametrize("p", [0.05, 0.001])
def test_holds_for_other_target_rates(p):
    bf, hits, fn = measure(BloomFilter, N, p, TRIALS, SEED)
    assert fn == 0
    assert relative_error(hits / TRIALS, theoretical_fp(bf.size, N, bf.num_hashes)) < TOLERANCE


def test_counting_filter_has_same_false_positive_rate(standard_run):
    _, std_hits, _ = standard_run
    cf, cnt_hits, fn = measure(CountingBloomFilter, N, 0.01, TRIALS, SEED)
    assert fn == 0
    assert cnt_hits == std_hits          # same hashing, same positions -> identical answers
    assert relative_error(cnt_hits / TRIALS, theoretical_fp(cf.size, N, cf.num_hashes)) < TOLERANCE


def test_vary_k_points_within_30_percent():
    result = run_experiment("vary_k", N, TRIALS, seed=SEED, ks=[3, 5, 7, 9, 11])
    for pt, an in zip(result["points"], result["analysis"]):
        assert abs(an["rel_diff"]) < TOLERANCE, pt["param_label"]
        assert abs(an["z_score"]) < 4, pt["param_label"]


def test_overfill_points_within_30_percent():
    result = run_experiment("overfill", N, TRIALS, seed=SEED)
    assert [p["n_inserted"] for p in result["points"]] == [50_000, 75_000, 100_000, 150_000]
    for pt, an in zip(result["points"], result["analysis"]):
        assert abs(an["rel_diff"]) < TOLERANCE, pt["param_label"]


def test_standard_error_is_small_enough_to_trust_tolerance():
    # With 200,000 trials at p = 1% the sampling noise is about 2.2% relative,
    # so a 30% tolerance is more than 10 standard errors wide.
    se_relative = math.sqrt(0.01 * 0.99 / TRIALS) / 0.01
    assert se_relative < 0.03
    assert TOLERANCE / se_relative > 10
