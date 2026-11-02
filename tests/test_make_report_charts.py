import os

import pytest

pytest.importorskip("matplotlib")  # charts need matplotlib; skip cleanly if it is not installed

from core.params import optimal_m  # noqa: E402
from scripts.make_report_charts import (  # noqa: E402
    FILES, generate_all, main, make_caption, measure_memory,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_caption_states_n_trials_seed():
    cap = make_caption(seed=42, n=100_000, trials=200_000, fp=0.01, note="extra note")
    assert "n = 100,000" in cap and "trials = 200,000" in cap and "seed = 42" in cap
    assert "target p = 1%" in cap and cap.endswith("extra note")


def test_memory_caption_says_no_trials():
    cap = make_caption(seed=7, fp=0.01)
    assert "seed = 7" in cap and "trials: none" in cap and "n = see x-axis" in cap


def test_measure_memory_rows():
    rows = measure_memory([1000, 4000], fp=0.01, seed=42)
    assert [r["n"] for r in rows] == [1000, 4000]
    for r in rows:
        m = optimal_m(r["n"], 0.01)
        assert r["bloom_bytes"] == (m + 7) // 8
        assert r["counting_bytes"] == m
        assert r["set_bytes"] > 5 * r["bloom_bytes"]
        assert r["set_estimate_bytes"] == pytest.approx(r["set_bytes"], rel=0.05)  # A7 matches reality


def test_measure_memory_sorts_sizes():
    assert [r["n"] for r in measure_memory([3000, 1000])] == [1000, 3000]


def test_generate_all_creates_four_png_files(tmp_path):
    messages = []
    paths = generate_all(str(tmp_path), n=2000, trials=4000, sizes=(1000, 2000), progress=messages.append)
    assert set(paths) == set(FILES)
    for name, path in paths.items():
        assert os.path.basename(path) == FILES[name]
        with open(path, "rb") as f:
            data = f.read()
        assert data.startswith(PNG_MAGIC)
        assert len(data) > 10_000, name   # a real drawn chart, not an empty canvas
    assert len(messages) == 4


def test_cli_writes_charts(tmp_path, capsys):
    code = main(["--n", "2000", "--trials", "4000", "--sizes", "1000", "2000", "--outdir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Saved:" in out and "chart1_fp_vs_k.png" in out
    assert sorted(os.listdir(tmp_path)) == sorted(FILES.values())
