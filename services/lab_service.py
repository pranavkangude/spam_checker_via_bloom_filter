"""Benchmark and experiment endpoints' logic (B7).

A's benchmark_service and experiment_service do the measuring and have no
database code. This module adds what the web layer needs:
  * input validation with the web limits (413 above them)
  * running the work as a background job (see job_service)
  * saving results into SQLite and reading them back
Neither feature touches the active filter.
"""
from __future__ import annotations

import csv
import io

from core.params import optimal_k
from db import database
from services import job_service
from services.benchmark_service import BENCHMARK_COLUMNS, WEB_MAX_ITEMS, run_benchmark
from services.errors import NotFoundError, PayloadTooLargeError, ValidationError
from services.experiment_service import (
    KINDS, POINT_COLUMNS, WEB_MAX_N, WEB_MAX_TRIALS, analyze, run_experiment,
)
from services.filter_service import P_MAX, P_MIN

WEB_MAX_SIZES = 6
WEB_MAX_QUERIES = 500_000
MAX_REPEATS = 5
MAX_SEED = 2 ** 63 - 1
RUN_GROUP_LIMIT = 50
EXPERIMENT_LIMIT = 100
EXPERIMENT_FP = 0.01          # BACKEND_SCHEMA 4.7: experiments use a 1% target


# ---- validation --------------------------------------------------------------

def _int(value, name: str, lo: int = 1, hi: int = None) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise ValidationError(f"{name} must be an integer >= {lo}", field=name)
    if hi is not None and value > hi:
        raise ValidationError(f"{name} must be at most {hi}", field=name)
    return value


def _wait_flag(d: dict) -> bool:
    wait = d.get("wait", False)
    if not isinstance(wait, bool):
        raise ValidationError("wait must be true or false", field="wait")
    return wait


# ---- benchmark ---------------------------------------------------------------

def start_benchmark(d: dict) -> tuple[dict, bool]:
    """Validate, then start the benchmark job. Returns (job snapshot, wait flag)."""
    wait = _wait_flag(d)
    sizes = d.get("sizes", [10_000, 100_000])
    if not isinstance(sizes, list) or not sizes:
        raise ValidationError("sizes must be a non-empty list of integers", field="sizes")
    if len(sizes) > WEB_MAX_SIZES:
        raise ValidationError(f"at most {WEB_MAX_SIZES} sizes per run", field="sizes")
    sizes = [_int(s, "sizes") for s in sizes]
    if max(sizes) > WEB_MAX_ITEMS:
        raise PayloadTooLargeError(
            f"sizes are limited to {WEB_MAX_ITEMS:,} items on the web; "
            "use scripts/run_benchmark.py for larger runs", field="sizes")
    queries = _int(d.get("queries", 200_000), "queries")
    if queries > WEB_MAX_QUERIES:
        raise PayloadTooLargeError(
            f"queries are limited to {WEB_MAX_QUERIES:,} on the web; "
            "use scripts/run_benchmark.py for larger runs", field="queries")
    fp = d.get("fp", 0.01)
    if isinstance(fp, bool) or not isinstance(fp, (int, float)) or not (P_MIN <= fp <= P_MAX):
        raise ValidationError(f"fp must be between {P_MIN} and {P_MAX}", field="fp")
    include_counting = d.get("include_counting", False)
    if not isinstance(include_counting, bool):
        raise ValidationError("include_counting must be true or false", field="include_counting")
    seed = _int(d.get("seed", 42), "seed", lo=0, hi=MAX_SEED)
    repeats = _int(d.get("repeats", MAX_REPEATS), "repeats", lo=1, hi=MAX_REPEATS)

    def work(progress):
        result = run_benchmark(sizes, queries, float(fp), include_counting, seed, repeats, 1,
                               max_items=WEB_MAX_ITEMS, progress=progress)
        _save_benchmark(result["rows"])
        return result

    return job_service.start("benchmark", work, wait=wait), wait


def _save_benchmark(rows: list[dict]) -> None:
    cols = ", ".join(BENCHMARK_COLUMNS)
    marks = ", ".join("?" for _ in BENCHMARK_COLUMNS)
    with database.connection() as conn:
        conn.executemany(
            f"INSERT INTO benchmark_runs ({cols}) VALUES ({marks})",   # fixed column names
            [tuple(row[c] for c in BENCHMARK_COLUMNS) for row in rows],
        )


def list_benchmark_runs() -> list[dict]:
    """Saved benchmark rows grouped by run_group, newest group first."""
    rows = database.query_all(
        "SELECT * FROM benchmark_runs WHERE run_group IN ("
        "  SELECT run_group FROM benchmark_runs GROUP BY run_group "
        "  ORDER BY MAX(id) DESC LIMIT ?) ORDER BY id",
        (RUN_GROUP_LIMIT,),
    )
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["run_group"], {
            "run_group": r["run_group"], "created_at": r["created_at"], "rows": []})
        g["rows"].append(dict(r))
    return list(reversed(list(groups.values())))


# ---- experiments -------------------------------------------------------------

def start_experiment(d: dict) -> tuple[dict, bool]:
    wait = _wait_flag(d)
    kind = d.get("kind")
    if kind not in KINDS:
        raise ValidationError(f"kind must be one of {', '.join(KINDS)}", field="kind")
    n = _int(d.get("n", 100_000), "n")
    if n > WEB_MAX_N:
        raise PayloadTooLargeError(
            f"n is limited to {WEB_MAX_N:,} on the web; use scripts/run_experiments.py",
            field="n")
    trials = _int(d.get("trials", 200_000), "trials")
    if trials > WEB_MAX_TRIALS:
        raise PayloadTooLargeError(
            f"trials are limited to {WEB_MAX_TRIALS:,} on the web; "
            "use scripts/run_experiments.py", field="trials")
    seed = _int(d.get("seed", 42), "seed", lo=0, hi=MAX_SEED)

    def work(progress):
        res = run_experiment(kind, n, trials, EXPERIMENT_FP, seed, max_n=WEB_MAX_N,
                             max_trials=WEB_MAX_TRIALS, progress=progress)
        res["experiment_id"] = _save_experiment(res)
        return res

    return job_service.start("experiment", work, wait=wait), wait


def _save_experiment(res: dict) -> int:
    cols = ", ".join(POINT_COLUMNS)
    marks = ", ".join("?" for _ in range(len(POINT_COLUMNS) + 1))
    with database.connection() as conn:
        cur = conn.execute(
            "INSERT INTO fp_experiments (kind, n_items, trials, seed) VALUES (?, ?, ?, ?)",
            (res["kind"], res["n_items"], res["trials"], res["seed"]),
        )
        exp_id = cur.lastrowid
        conn.executemany(
            f"INSERT INTO fp_experiment_points (experiment_id, {cols}) VALUES ({marks})",
            [(exp_id, *[p[c] for c in POINT_COLUMNS]) for p in res["points"]],
        )
    return exp_id


def list_experiments() -> list[dict]:
    rows = database.query_all(
        "SELECT e.id AS experiment_id, e.kind, e.n_items, e.trials, e.seed, e.created_at, "
        "(SELECT COUNT(*) FROM fp_experiment_points p WHERE p.experiment_id = e.id) AS points "
        "FROM fp_experiments e ORDER BY e.id DESC LIMIT ?",
        (EXPERIMENT_LIMIT,),
    )
    return [dict(r) for r in rows]


def get_experiment(exp_id: int) -> dict:
    """One saved experiment with its points. analysis and meta are recomputed."""
    exp = database.query_one("SELECT * FROM fp_experiments WHERE id = ?", (exp_id,))
    if exp is None:
        raise NotFoundError("Experiment not found")
    rows = database.query_all(
        f"SELECT {', '.join(POINT_COLUMNS)} FROM fp_experiment_points "
        "WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    )
    points = [dict(r) for r in rows]
    meta: dict = {}
    if exp["kind"] in ("vary_k", "overfill") and points:
        m = points[0]["m_bits"]
        meta = {"m_bits": m, "optimal_k": optimal_k(m, exp["n_items"])}
    return {
        "experiment_id": exp["id"], "kind": exp["kind"], "n_items": exp["n_items"],
        "trials": exp["trials"], "seed": exp["seed"], "created_at": exp["created_at"],
        "points": points, "analysis": analyze(points), "meta": meta,
    }


def experiment_csv(exp_id: int) -> tuple[str, str]:
    """(csv text, file name) for one experiment, including rel_diff and z_score."""
    exp = get_experiment(exp_id)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(list(POINT_COLUMNS) + ["rel_diff", "z_score"])
    for pt, an in zip(exp["points"], exp["analysis"]):
        writer.writerow([pt[c] for c in POINT_COLUMNS] + [an["rel_diff"], an["z_score"]])
    return out.getvalue(), f"experiment_{exp_id}_{exp['kind']}.csv"
