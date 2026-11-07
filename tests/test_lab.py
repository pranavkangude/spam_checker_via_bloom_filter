import csv
import io
import threading
import time

import pytest

from app import create_app
from services import job_service
from services.benchmark_service import BENCHMARK_COLUMNS
from services.errors import ValidationError
from services.experiment_service import POINT_COLUMNS


@pytest.fixture
def client(tmp_path):
    job_service.reset()
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    yield c
    job_service.join_all()


def _bench(client, **over):
    body = {"sizes": [200, 500], "queries": 1000, "repeats": 1, "wait": True, **over}
    return client.post("/api/benchmark", json=body)


def _exp(client, kind="vary_k", **over):
    body = {"kind": kind, "n": 2000, "trials": 5000, "wait": True, **over}
    return client.post("/api/experiments", json=body)


def _poll(client, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


# ---- benchmark ---------------------------------------------------------------

def test_benchmark_wait_rows_and_persistence(client):
    r = _bench(client, include_counting=True)
    d = r.get_json()
    assert r.status_code == 200 and len(d["rows"]) == 4 and len(d["details"]) == 4
    assert {row["filter_type"] for row in d["rows"]} == {"standard", "counting"}
    for row in d["rows"]:
        assert set(row) == set(BENCHMARK_COLUMNS)          # jsonify sorts keys; compare as sets
        assert row["false_negatives"] == 0 and row["run_group"] == d["run_group"]
        assert row["bloom_mem_bytes"] > 0 and row["memory_ratio"] > 0

    runs = client.get("/api/benchmark/runs").get_json()
    assert len(runs) == 1 and runs[0]["run_group"] == d["run_group"] and len(runs[0]["rows"]) == 4
    assert [x["n_items"] for x in runs[0]["rows"]] == [200, 200, 500, 500]    # insertion order

    d2 = _bench(client).get_json()
    runs = client.get("/api/benchmark/runs").get_json()
    assert [g["run_group"] for g in runs] == [d2["run_group"], d["run_group"]]  # newest first


def test_benchmark_async_job_with_progress(client):
    r = client.post("/api/benchmark",
                    json={"sizes": [200, 400], "queries": 500, "repeats": 1})
    job = r.get_json()
    assert r.status_code == 202 and job["status"] in ("running", "done") and job["job_id"]
    done = _poll(client, job["job_id"])
    assert done["status"] == "done" and done["error"] is None
    assert done["progress"]["done"] == done["progress"]["total"] == 2
    assert len(done["result"]["rows"]) == 2 and done["finished_at"]
    assert len(client.get("/api/benchmark/runs").get_json()) == 1


@pytest.mark.parametrize("over,status", [
    ({"sizes": []}, 400), ({"sizes": "x"}, 400), ({"sizes": [0]}, 400),
    ({"sizes": [10, True]}, 400), ({"sizes": [10] * 7}, 400),
    ({"sizes": [200_001]}, 413), ({"queries": 500_001}, 413), ({"queries": 0}, 400),
    ({"fp": 0.9}, 400), ({"fp": "a"}, 400), ({"fp": True}, 400),
    ({"include_counting": "yes"}, 400), ({"seed": 1.5}, 400), ({"seed": -1}, 400),
    ({"repeats": 0}, 400), ({"repeats": 6}, 400), ({"wait": "yes"}, 400),
])
def test_benchmark_validation(client, over, status):
    r = _bench(client, **over)
    assert r.status_code == status
    assert r.get_json()["error"]["code"] == ("PAYLOAD_TOO_LARGE" if status == 413
                                             else "VALIDATION_ERROR")
    assert client.get("/api/benchmark/runs").get_json() == []                 # nothing saved


def test_benchmark_body_must_be_json(client):
    assert client.post("/api/benchmark", data="x").status_code == 400


# ---- experiments -------------------------------------------------------------

def test_vary_k_points_analysis_and_persistence(client):
    r = _exp(client, "vary_k")
    d = r.get_json()
    assert r.status_code == 200 and d["experiment_id"] >= 1 and d["kind"] == "vary_k"
    assert [p["param_label"] for p in d["points"]] == [f"k={k}" for k in range(1, 15)]
    assert all(set(p) == set(POINT_COLUMNS) for p in d["points"])
    assert len(d["analysis"]) == 14 and "rel_diff" in d["analysis"][0] and "z_score" in d["analysis"][0]
    assert d["meta"]["optimal_k"] >= 1 and d["meta"]["m_bits"] > 0

    lst = client.get("/api/experiments").get_json()
    assert lst[0]["experiment_id"] == d["experiment_id"] and lst[0]["points"] == 14
    assert (lst[0]["kind"], lst[0]["n_items"], lst[0]["trials"], lst[0]["seed"]) == ("vary_k", 2000, 5000, 42)

    saved = client.get(f"/api/experiments/{d['experiment_id']}").get_json()
    assert saved["points"] == d["points"] and saved["analysis"] == d["analysis"]
    assert saved["meta"] == d["meta"] and saved["created_at"]


def test_vary_ratio_and_overfill(client):
    d = _exp(client, "vary_ratio").get_json()
    assert [p["param_label"] for p in d["points"]] == [f"m/n={r}" for r in (4, 6, 8, 10, 12, 16)]
    assert client.get(f"/api/experiments/{d['experiment_id']}").get_json()["meta"] == {}

    d = _exp(client, "overfill").get_json()
    assert [p["n_inserted"] for p in d["points"]] == [2000, 3000, 4000, 6000]
    assert [p["param_label"] for p in d["points"]] == ["1x n", "1.5x n", "2x n", "3x n"]
    rates = [p["empirical_fp"] for p in d["points"]]
    assert rates == sorted(rates)                                              # FP rises when overfilled
    assert client.get(f"/api/experiments/{d['experiment_id']}").get_json()["meta"] == d["meta"]


def test_same_seed_is_reproducible(client):
    a = _exp(client, "vary_k", seed=7).get_json()["points"]
    b = _exp(client, "vary_k", seed=7).get_json()["points"]
    c = _exp(client, "vary_k", seed=8).get_json()["points"]
    assert a == b and a != c


def test_experiment_csv(client):
    d = _exp(client, "vary_ratio").get_json()
    r = client.get(f"/api/experiments/{d['experiment_id']}/csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert f"experiment_{d['experiment_id']}_vary_ratio.csv" in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == list(POINT_COLUMNS) + ["rel_diff", "z_score"] and len(rows) == 7
    assert float(rows[1][5]) == d["points"][0]["empirical_fp"]
    assert float(rows[1][8]) == d["analysis"][0]["rel_diff"]


@pytest.mark.parametrize("over,status", [
    ({"kind": "nope"}, 400), ({"kind": None}, 400), ({"n": 0}, 400), ({"n": "5"}, 400),
    ({"n": True}, 400), ({"n": 200_001}, 413), ({"trials": 0}, 400),
    ({"trials": 500_001}, 413), ({"seed": 1.5}, 400), ({"seed": True}, 400),
])
def test_experiment_validation(client, over, status):
    assert _exp(client, **over).status_code == status
    assert client.get("/api/experiments").get_json() == []


def test_missing_experiment_and_job_are_404(client):
    for url in ("/api/experiments/999", "/api/experiments/999/csv", "/api/jobs/nope"):
        r = client.get(url)
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "NOT_FOUND"


def test_experiments_do_not_touch_the_active_filter(client):
    client.post("/api/filter", json={"name": "main", "type": "standard", "n": 1000, "p": 0.01})
    client.post("/api/blacklist", json={"item": "keep_me", "key_type": "transaction_id"})
    before = client.get("/api/filter").get_json()
    _exp(client, "overfill")
    _bench(client)
    after = client.get("/api/filter").get_json()
    assert after["item_count"] == before["item_count"] == 1
    assert after["fill_ratio"] == before["fill_ratio"]
    chk = client.post("/api/check", json={"item": "keep_me", "key_type": "transaction_id"})
    assert chk.get_json()["verdict"] == "BLACKLISTED"


# ---- job rules ---------------------------------------------------------------

def test_only_one_job_at_a_time(client):
    gate = threading.Event()
    job_service.start("test", lambda progress: gate.wait(30) or {"ok": True})
    try:
        for r in (_exp(client), _bench(client)):
            assert r.status_code == 409 and r.get_json()["error"]["code"] == "JOB_RUNNING"
    finally:
        gate.set()
        job_service.join_all()
    assert _exp(client).status_code == 200                                    # free again


def test_failed_jobs_report_errors(client):
    def boom(progress):
        raise RuntimeError("secret internals")

    def bad_input(progress):
        raise ValueError("n is wrong")

    j = job_service.start("t", boom)
    done = _poll(client, j["job_id"])
    assert done["status"] == "error" and done["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in done["error"]["message"] and done["result"] is None

    j = job_service.start("t", bad_input)
    done = _poll(client, j["job_id"])
    assert done["error"] == {"code": "VALIDATION_ERROR", "message": "n is wrong"}

    with pytest.raises(ValidationError):                                      # wait=True re-raises
        job_service.start("t", lambda p: (_ for _ in ()).throw(ValidationError("bad")), wait=True)


def test_old_jobs_are_forgotten():
    job_service.reset()
    for _ in range(job_service.MAX_JOBS + 5):
        job_service.start("t", lambda progress: {}, wait=True)
    assert len(job_service._jobs) <= job_service.MAX_JOBS
    job_service.reset()
