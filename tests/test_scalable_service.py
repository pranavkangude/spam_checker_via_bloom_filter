import csv

import pytest

from scripts.run_scalable_comparison import main
from services.scalable_service import POINT_COLUMNS, compare_overfill

N, TRIALS = 2000, 8000


@pytest.fixture(scope="module")
def result():
    return compare_overfill(N, TRIALS, factors=[1, 2, 5, 10])


def test_point_structure(result):
    pts = result["points"]
    assert [p["factor"] for p in pts] == [1, 2, 5, 10]
    assert all(tuple(p) == POINT_COLUMNS for p in pts)
    assert [p["n_inserted"] for p in pts] == [N, 2 * N, 5 * N, 10 * N]
    assert all(p["trials"] == TRIALS for p in pts)


def test_fixed_filter_degrades_scalable_does_not(result):
    pts = result["points"]
    fixed = [p["fixed_fp"] for p in pts]
    scalable = [p["scalable_fp"] for p in pts]
    assert fixed == sorted(fixed) and fixed[-1] > 0.9           # fixed filter is nearly useless at 10x
    assert max(scalable) < 0.015                                 # scalable stays under the 1% target (+ noise)
    assert all(p["scalable_estimated_fp"] < 0.01 for p in pts)


def test_stages_and_memory_grow(result):
    pts = result["points"]
    assert [p["stages"] for p in pts] == sorted(p["stages"] for p in pts)
    assert pts[0]["stages"] == 1 and pts[-1]["stages"] >= 4
    assert len({p["fixed_bytes"] for p in pts}) == 1             # fixed filter never grows
    assert pts[-1]["scalable_bytes"] > pts[0]["scalable_bytes"]


def test_oracle_is_cheaper_than_scalable(result):
    for p in result["points"]:
        assert p["oracle_bytes"] <= p["scalable_bytes"]          # not knowing n in advance has a cost


def test_theoretical_fixed_rate_matches(result):
    for p in result["points"][:2]:
        assert p["fixed_fp"] == pytest.approx(p["fixed_theoretical_fp"], rel=0.25, abs=0.003)


def test_reproducible_with_seed():
    a = compare_overfill(500, 2000, factors=[1, 3], seed=9)
    b = compare_overfill(500, 2000, factors=[1, 3], seed=9)
    assert a["points"] == b["points"]


def test_stage_info_and_bound(result):
    assert result["scalable_bound"] < 0.01
    assert len(result["stage_info"]) == result["points"][-1]["stages"]


def test_progress_callback():
    calls = []
    compare_overfill(300, 500, factors=[1, 2], progress=lambda l, d, t: calls.append((l, d, t)))
    assert calls == [("1x n", 1, 2), ("2x n", 2, 2)]


@pytest.mark.parametrize("kwargs", [
    dict(n_items=0), dict(fp=1.5), dict(trials=0), dict(factors=[]), dict(factors=[-1]),
    dict(growth=1), dict(tightening=2),
])
def test_invalid_inputs(kwargs):
    kwargs.setdefault("n_items", 100)
    kwargs.setdefault("trials", 100)
    with pytest.raises(ValueError):
        compare_overfill(**kwargs)


def test_cli_writes_csv(tmp_path, capsys):
    out = tmp_path / "s.csv"
    code = main(["--n", "500", "--trials", "1000", "--csv", str(out)])
    assert code == 0
    assert "Guaranteed bound" in capsys.readouterr().out
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 6 and tuple(rows[0]) == POINT_COLUMNS


def test_cli_chart(tmp_path):
    pytest.importorskip("matplotlib")
    chart = tmp_path / "c.png"
    assert main(["--n", "500", "--trials", "1000", "--csv", str(tmp_path / "s.csv"), "--chart", str(chart)]) == 0
    assert chart.read_bytes().startswith(b"\x89PNG")
