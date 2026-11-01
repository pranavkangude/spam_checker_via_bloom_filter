import csv
import math

import pytest

from core.params import optimal_k, optimal_m
from scripts.run_experiments import CSV_COLUMNS, main
from services.experiment_service import (
    POINT_COLUMNS, WEB_MAX_N, WEB_MAX_TRIALS, analyze, run_experiment,
)

N, TRIALS = 5000, 20_000


def close_enough(point):
    """Empirical within 5 standard errors (+10% model slack) of theoretical."""
    se = math.sqrt(point["theoretical_fp"] * (1 - point["theoretical_fp"]) / point["trials"])
    return abs(point["empirical_fp"] - point["theoretical_fp"]) <= 5 * se + 0.1 * point["theoretical_fp"]


@pytest.fixture(scope="module")
def vary_k():
    return run_experiment("vary_k", N, TRIALS)


@pytest.fixture(scope="module")
def vary_ratio():
    return run_experiment("vary_ratio", N, TRIALS)


@pytest.fixture(scope="module")
def overfill():
    return run_experiment("overfill", N, TRIALS)


def test_vary_k_points(vary_k):
    pts = vary_k["points"]
    assert [p["param_label"] for p in pts] == [f"k={k}" for k in range(1, 15)]
    assert all(tuple(p) == POINT_COLUMNS for p in pts)
    assert {p["m_bits"] for p in pts} == {optimal_m(N, 0.01)}      # m fixed
    assert all(p["n_inserted"] == N and p["trials"] == TRIALS for p in pts)
    assert vary_k["meta"]["optimal_k"] == 7


def test_vary_k_u_shape(vary_k):
    theo = [p["theoretical_fp"] for p in vary_k["points"]]
    emp = [p["empirical_fp"] for p in vary_k["points"]]
    assert theo.index(min(theo)) + 1 == vary_k["meta"]["optimal_k"]   # theory: minimum at optimal k
    assert emp[0] > 5 * emp[6]       # k=1 much worse than k=7
    assert emp[13] > emp[6]          # k=14 worse than k=7
    assert 5 <= emp.index(min(emp)) + 1 <= 9  # empirical minimum near the optimum


def test_vary_k_empirical_matches_theory(vary_k):
    assert all(close_enough(p) for p in vary_k["points"])


def test_vary_ratio(vary_ratio):
    pts = vary_ratio["points"]
    assert [p["param_label"] for p in pts] == ["m/n=4", "m/n=6", "m/n=8", "m/n=10", "m/n=12", "m/n=16"]
    assert [p["m_bits"] for p in pts] == [4 * N, 6 * N, 8 * N, 10 * N, 12 * N, 16 * N]
    assert [p["k_hashes"] for p in pts] == [optimal_k(p["m_bits"], N) for p in pts]
    theo = [p["theoretical_fp"] for p in pts]
    assert theo == sorted(theo, reverse=True)                     # more bits per item -> fewer FPs
    emp = [p["empirical_fp"] for p in pts]
    assert emp[0] > emp[2] > emp[5]
    assert all(close_enough(p) for p in pts)


def test_overfill(overfill):
    pts = overfill["points"]
    assert [p["param_label"] for p in pts] == ["1x n", "1.5x n", "2x n", "3x n"]
    assert [p["n_inserted"] for p in pts] == [N, int(1.5 * N), 2 * N, 3 * N]
    assert len({p["m_bits"] for p in pts}) == 1 and len({p["k_hashes"] for p in pts}) == 1
    emp = [p["empirical_fp"] for p in pts]
    assert emp == sorted(emp)                                     # climbs as it overfills
    assert emp[0] == pytest.approx(0.01, abs=0.004)               # designed point is near target
    assert emp[3] > 0.3                                           # 3x capacity: FP explodes
    assert all(close_enough(p) for p in pts)


def test_false_positive_counts_consistent(vary_k):
    for p in vary_k["points"]:
        assert p["empirical_fp"] == p["false_positives"] / p["trials"]


def test_analysis_values(vary_k):
    an = vary_k["analysis"]
    assert len(an) == len(vary_k["points"])
    for pt, a in zip(vary_k["points"], an):
        assert a["param_label"] == pt["param_label"]
        assert a["abs_diff"] == pytest.approx(pt["empirical_fp"] - pt["theoretical_fp"])
        assert a["rel_diff"] == pytest.approx(a["abs_diff"] / pt["theoretical_fp"])
    assert analyze(vary_k["points"]) == an


def test_reproducible_with_same_seed_and_different_with_other():
    a = run_experiment("vary_k", 2000, 5000, ks=[3, 7], seed=1)
    b = run_experiment("vary_k", 2000, 5000, ks=[3, 7], seed=1)
    c = run_experiment("vary_k", 2000, 5000, ks=[3, 7], seed=2)
    assert a["points"] == b["points"]
    assert [p["false_positives"] for p in a["points"]] != [p["false_positives"] for p in c["points"]]


def test_custom_parameters():
    r = run_experiment("vary_ratio", 1000, 2000, ratios=[5, 7.5])
    assert [p["param_label"] for p in r["points"]] == ["m/n=5", "m/n=7.5"]
    r = run_experiment("overfill", 1000, 2000, factors=[2, 0.5])
    assert [p["param_label"] for p in r["points"]] == ["0.5x n", "2x n"]  # sorted ascending
    assert [p["n_inserted"] for p in r["points"]] == [500, 2000]


def test_progress_callback():
    calls = []
    run_experiment("vary_k", 1000, 1000, ks=[1, 2, 3], progress=lambda l, d, t: calls.append((l, d, t)))
    assert calls == [("k=1", 1, 3), ("k=2", 2, 3), ("k=3", 3, 3)]


def test_web_limits():
    with pytest.raises(ValueError, match="run_experiments.py"):
        run_experiment("vary_k", WEB_MAX_N + 1, 100, max_n=WEB_MAX_N)
    with pytest.raises(ValueError, match="run_experiments.py"):
        run_experiment("vary_k", 100, WEB_MAX_TRIALS + 1, max_trials=WEB_MAX_TRIALS)
    run_experiment("vary_k", 100, 100, ks=[2], max_n=WEB_MAX_N, max_trials=WEB_MAX_TRIALS)


@pytest.mark.parametrize("kwargs", [
    dict(kind="bogus"), dict(kind="vary_k", n_items=0), dict(kind="vary_k", fp=1.5),
    dict(kind="vary_k", trials=0), dict(kind="vary_k", ks=[]), dict(kind="vary_k", ks=[0]),
    dict(kind="vary_ratio", ratios=[0]), dict(kind="overfill", factors=[]),
    dict(kind="overfill", factors=[-1]), dict(kind="vary_k", seed="x"),
])
def test_invalid_inputs(kwargs):
    kwargs.setdefault("n_items", 100)
    kwargs.setdefault("trials", 100)
    with pytest.raises(ValueError):
        run_experiment(**kwargs)


def test_cli_all_kinds_write_csv(tmp_path, capsys):
    code = main(["--kind", "all", "--n", "2000", "--trials", "4000", "--outdir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Optimal k" in out
    for kind, rows in (("vary_k", 14), ("vary_ratio", 6), ("overfill", 4)):
        with open(tmp_path / f"experiment_{kind}.csv", newline="", encoding="utf-8") as f:
            data = list(csv.DictReader(f))
        assert len(data) == rows
        assert tuple(data[0]) == CSV_COLUMNS
