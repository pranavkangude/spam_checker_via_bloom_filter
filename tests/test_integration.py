"""B10: end-to-end, persistence, concurrency and randomized tests.

Covers BACKEND_SCHEMA section 8 at system level. Each test builds a fresh
storage folder, and "restart" means building a new app on the same folder.
"""
import io
import random
import threading

import pytest

from app import PAGES, create_app
from core.bloom import BloomFilter
from core.counting_bloom import CountingBloomFilter
from db import database
from services import filter_service as fs
from services import job_service


def new_app(tmp_path):
    return create_app(storage_dir=tmp_path, testing=True)


def create(client, ftype="standard", n=1000, p=0.01):
    r = client.post("/api/filter", json={"name": "main", "type": ftype, "n": n, "p": p,
                                         "confirm_replace": True})
    assert r.status_code == 201
    return r.get_json()


def check(client, item, key_type="transaction_id", mode="two_stage"):
    r = client.post("/api/check", json={"item": item, "key_type": key_type, "mode": mode})
    assert r.status_code == 200
    return r.get_json()


def all_entries(client):
    out, page = [], 1
    while True:
        d = client.get(f"/api/blacklist?page={page}&page_size=100").get_json()
        out += d["items"]
        if len(out) >= d["total"]:
            return out
        page += 1


# ---- the whole product, start to finish ---------------------------------------

def test_full_workflow(tmp_path):
    job_service.reset()
    c = new_app(tmp_path).test_client()

    # first run: pages send you to setup, the API says there is no filter
    assert c.get("/").headers["Location"].endswith("/setup")
    assert c.get("/api/filter").status_code == 404
    calc = c.post("/api/filter/calc", json={"n": 5000, "p": 0.01, "type": "counting"}).get_json()
    info = create(c, "counting", 5000, 0.01)
    assert (info["m_bits"], info["k_hashes"]) == (calc["m"], calc["k"])
    assert c.get("/").status_code == 200 and c.get("/setup").status_code == 302

    # slice 1 from the plan: add, then check
    assert c.post("/api/blacklist", json={"item": "fraud_txn_1", "key_type": "transaction_id"}
                  ).status_code == 201
    assert check(c, "fraud_txn_1")["verdict"] == "BLACKLISTED"
    assert check(c, "clean_txn_1")["verdict"] in ("CLEAN", "FALSE_POSITIVE")

    # CSV import and the synthetic generator
    body = b"id,email\n1,A@x.com\n2,a@x.com\n3,\n4,b@x.com\n"
    up = c.post("/api/blacklist/bulk", content_type="multipart/form-data", data={
        "file": (io.BytesIO(body), "mails.csv"), "column": "email", "key_type": "email",
        "label": "spam"}).get_json()
    assert (up["rows_added"], up["rows_duplicate"], up["rows_invalid"]) == (2, 1, 1)
    gen = c.post("/api/blacklist/generate", json={"count": 2000, "prefix": "fraud_txn_"}).get_json()
    assert gen["rows_added"] == 1999 and gen["rows_duplicate"] == 1            # fraud_txn_1 existed
    assert c.get("/api/blacklist").get_json()["total"] == 2002
    assert check(c, "A@X.COM", "email")["label"] == "spam"

    # counters and history
    info = c.get("/api/filter").get_json()
    assert info["counters"]["checks"] == 3 and info["counters"]["blacklisted"] == 2
    assert c.get("/api/history").get_json()["total"] == 3

    # the demo filter and the lab never touch the real one
    c.post("/api/visualizer/insert", json={"item": "demo"})
    lab = c.post("/api/experiments", json={"kind": "overfill", "n": 500, "trials": 2000, "wait": True})
    assert lab.status_code == 200
    assert c.get("/api/filter").get_json()["item_count"] == 2002

    # rebuild into a bigger filter: still no false negatives
    out = c.post("/api/filter/rebuild", json={"n": 20000, "p": 0.001}).get_json()
    assert out["reinserted"] == 2002 and out["filter"]["m_bits"] > info["m_bits"]
    assert all(check(c, f"fraud_txn_{i}")["verdict"] == "BLACKLISTED" for i in range(0, 2000, 97))

    # counting filter: remove makes the item clean again
    assert c.delete("/api/blacklist", json={"item": "fraud_txn_1", "key_type": "transaction_id"}
                    ).status_code == 204
    assert check(c, "fraud_txn_1")["verdict"] in ("CLEAN", "FALSE_POSITIVE")
    assert c.get("/api/filter").get_json()["item_count"] == 2001

    # reset wipes the filter, blacklist, logs and imports, but keeps saved experiments
    assert c.delete("/api/filter", json={"confirm": "RESET"}).status_code == 204
    assert c.get("/api/filter").status_code == 404
    assert c.get("/api/blacklist").status_code == 404
    assert c.get("/api/history").get_json()["total"] == 0
    assert len(c.get("/api/experiments").get_json()) == 1
    assert not (tmp_path / "filter_state.bin").exists()
    c2 = new_app(tmp_path).test_client()                                       # restart after reset
    assert c2.get("/").headers["Location"].endswith("/setup")


# ---- restart: identical state -------------------------------------------------

@pytest.mark.parametrize("ftype", ["standard", "counting"])
def test_restart_keeps_everything_identical(tmp_path, ftype):
    c = new_app(tmp_path).test_client()
    create(c, ftype, n=300)                                    # deliberately overfilled below
    keys = [f"key_{i}" for i in range(500)]
    fs.add_many(keys, "transaction_id", "fraud", "synthetic")
    for k in keys[:20] + ["nothing_here"]:
        check(c, k)
    before = c.get("/api/filter").get_json()
    blob, entries = fs.get_filter().to_bytes(), all_entries(c)
    assert before["over_capacity"] is True and before["item_count"] == 500

    for _ in range(2):                                         # restart twice
        c = new_app(tmp_path).test_client()
        assert not fs.rebuilt_on_startup()                     # snapshot was valid: no rebuild
        assert c.get("/api/filter").get_json() == before       # counters, fill ratio, flags
        assert fs.get_filter().to_bytes() == blob              # same bits (or counters)
        assert all_entries(c) == entries
    assert all(check(c, k)["verdict"] == "BLACKLISTED" for k in keys[::25])    # after: checks add logs


# ---- restart: damaged or stale snapshot -> automatic rebuild ------------------

def _build(tmp_path, ftype):
    """500 keys in SQLite and the snapshot; also returns the snapshot taken after 450 keys."""
    c = new_app(tmp_path).test_client()
    create(c, ftype, n=1000)
    keys = [f"key_{i}" for i in range(500)]
    fs.add_many(keys[:450], "transaction_id", "fraud", "synthetic")
    mid = (tmp_path / "filter_state.bin").read_bytes()
    fs.add_many(keys[450:], "transaction_id", "fraud", "synthetic")
    return keys, mid, (tmp_path / "filter_state.bin").read_bytes()


def _sql(tmp_path, statement, params=()):
    with database.connection() as conn:
        conn.execute(statement, params)


# case -> (damage function, snapshot bytes should equal the original after rebuild)
def _missing(p, mid, full):
    (p / "filter_state.bin").unlink()


def _truncated(p, mid, full):
    (p / "filter_state.bin").write_bytes(full[: len(full) // 2])


def _bit_flip(p, mid, full):
    data = bytearray(full)
    data[len(data) // 2] ^= 0xFF
    (p / "filter_state.bin").write_bytes(bytes(data))


def _garbage(p, mid, full):
    (p / "filter_state.bin").write_bytes(b"garbage")


def _wrong_type(p, mid, full):
    other = CountingBloomFilter if full[5] == 0 else BloomFilter       # header byte 5 = filter type
    m = int.from_bytes(full[7:15], "little")
    k = int.from_bytes(full[15:19], "little")
    (p / "filter_state.bin").write_bytes(other.with_size(m, k).to_bytes())


def _stale(p, mid, full):                      # crash after the SQLite commit, before the snapshot
    (p / "filter_state.bin").write_bytes(mid)


FILE_DAMAGE = {"missing": _missing, "truncated": _truncated, "bit_flip": _bit_flip,
               "garbage": _garbage, "wrong_type": _wrong_type, "stale": _stale}


@pytest.mark.parametrize("ftype", ["standard", "counting"])
@pytest.mark.parametrize("case", sorted(FILE_DAMAGE))
def test_damaged_snapshot_is_rebuilt_exactly(tmp_path, ftype, case):
    keys, mid, full = _build(tmp_path, ftype)
    FILE_DAMAGE[case](tmp_path, mid, full)

    c = new_app(tmp_path).test_client()
    assert fs.rebuilt_on_startup() is True
    assert c.get("/api/filter").get_json()["rebuilt_on_startup"] is True
    assert fs.get_filter().to_bytes() == full                          # identical to the original
    assert all(check(c, k)["verdict"] == "BLACKLISTED" for k in keys[::7] + keys[-50:])
    assert c.get("/api/filter").get_json()["item_count"] == 500

    new_app(tmp_path)                                                  # next restart is clean
    assert fs.rebuilt_on_startup() is False and fs.get_filter().to_bytes() == full


def test_params_mismatch_rebuilds_to_match_the_database(tmp_path):
    keys, _, _ = _build(tmp_path, "standard")
    _sql(tmp_path, "UPDATE filters SET m_bits = m_bits + 8")
    c = new_app(tmp_path).test_client()
    info = c.get("/api/filter").get_json()
    assert fs.rebuilt_on_startup() and fs.get_filter().size == info["m_bits"]
    assert all(check(c, k)["verdict"] == "BLACKLISTED" for k in keys[::9])


@pytest.mark.parametrize("ftype", ["standard", "counting"])
def test_database_ahead_of_snapshot_is_repaired(tmp_path, ftype):
    keys, _, _ = _build(tmp_path, ftype)
    _sql(tmp_path, "INSERT INTO blacklist_entries (filter_id, item_raw, item_key, key_type) "
                   "VALUES (1, 'ghost', 'ghost', 'other')")             # committed, never snapshotted
    _sql(tmp_path, "UPDATE filters SET item_count = 7")                  # and a wrong counter
    c = new_app(tmp_path).test_client()
    assert fs.rebuilt_on_startup() and "ghost" in fs.get_filter()
    assert c.get("/api/filter").get_json()["item_count"] == 501
    assert all(check(c, k)["verdict"] == "BLACKLISTED" for k in keys[::9])


# ---- concurrency --------------------------------------------------------------

def _run(threads):
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
        assert not t.is_alive()


def test_parallel_adds_never_drift(tmp_path):
    app = new_app(tmp_path)
    create(app.test_client(), n=5000)
    statuses, lock = [], threading.Lock()

    def worker(t):
        c = app.test_client()
        for i in range(50):
            r = c.post("/api/blacklist", json={"item": f"t{t}_{i}", "key_type": "other"})
            with lock:
                statuses.append(r.status_code)
        r = c.post("/api/blacklist", json={"item": "shared", "key_type": "other"})
        with lock:
            statuses.append(("shared", r.status_code))

    _run([threading.Thread(target=worker, args=(t,)) for t in range(8)])
    assert statuses.count(("shared", 201)) == 1 and statuses.count(("shared", 409)) == 7
    assert statuses.count(201) == 400 and len(statuses) == 408
    with database.connection() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM blacklist_entries").fetchone()[0]
        counter = conn.execute("SELECT item_count FROM filters").fetchone()[0]
    assert rows == counter == fs.get_filter().count == 401
    assert "shared" in fs.get_filter() and all(f"t3_{i}" in fs.get_filter() for i in range(50))


def test_overlapping_imports_account_for_every_row(tmp_path):
    new_app(tmp_path)
    fs.create_filter("main", "standard", 10_000, 0.01)
    results = []

    def worker(lo, hi):
        results.append(fs.add_many([f"k{i}" for i in range(lo, hi)], "other", "fraud", "synthetic"))

    _run([threading.Thread(target=worker, args=(0, 3000)),
          threading.Thread(target=worker, args=(1500, 4500))])
    assert sum(r["rows_added"] for r in results) == 4500
    assert sum(r["rows_duplicate"] for r in results) == 1500
    assert all(r["rows_read"] == r["rows_added"] + r["rows_duplicate"] + r["rows_invalid"]
               for r in results)
    assert fs.get_info()["item_count"] == 4500 == fs.get_filter().count


def test_checks_stay_correct_during_a_rebuild(tmp_path):
    app = new_app(tmp_path)
    create(app.test_client(), n=20_000)
    keys = [f"key_{i}" for i in range(20_000)]
    fs.add_many(keys, "other", "fraud", "synthetic")

    verdicts, started, stop = [], threading.Event(), threading.Event()

    def checker():
        c, i = app.test_client(), 0
        while not stop.is_set():
            r = c.post("/api/check", json={"item": keys[i % len(keys)], "key_type": "other"})
            verdicts.append((r.status_code, r.get_json().get("verdict")))
            i += 977
            if len(verdicts) == 20:
                started.set()

    t = threading.Thread(target=checker)
    t.start()
    assert started.wait(30)
    before = len(verdicts)
    fs.rebuild(60_000, 0.001)                                    # old filter serves until the swap
    stop.set()
    t.join(30)
    assert len(verdicts) > before                                # checks really ran during the rebuild
    assert set(verdicts) == {(200, "BLACKLISTED")}               # never a miss, never an error


# ---- scale and randomized ------------------------------------------------------

def test_no_false_negatives_and_sane_fp_rate_at_scale(tmp_path):
    c = new_app(tmp_path).test_client()
    create(c, n=20_000, p=0.01)
    gen = c.post("/api/blacklist/generate", json={"count": 20_000, "prefix": "bad_"}).get_json()
    assert gen["rows_added"] == 20_000 and gen["filter"]["over_capacity"] is False
    f = fs.get_filter()
    assert not [i for i in range(20_000) if f"bad_{i}" not in f]            # zero false negatives
    fp = sum(1 for i in range(20_000) if f"good_{i}" in f) / 20_000
    assert 0.004 < fp < 0.02                                                 # target 1%
    seen = [check(c, f"good_{i}", "transaction_id") for i in range(300)]
    assert {s["verdict"] for s in seen} <= {"CLEAN", "FALSE_POSITIVE"}
    assert all((s["verdict"] == "FALSE_POSITIVE") == (s["bloom_result"] == "PROBABLE") for s in seen)


@pytest.mark.parametrize("ftype", ["standard", "counting"])
def test_random_operations_match_a_set_model(tmp_path, ftype):
    rng = random.Random(2026)
    c = new_app(tmp_path).test_client()
    create(c, ftype, n=400)
    universe, model = [f"key{i}" for i in range(300)], set()

    for step in range(300):
        op = rng.choices(["add", "remove", "check", "rebuild", "restart"], [40, 20, 30, 5, 5])[0]
        key = rng.choice(universe)
        body = {"item": key, "key_type": "other"}
        if op == "add":
            r = c.post("/api/blacklist", json=body)
            assert r.status_code == (409 if key in model else 201), (step, op, key)
            model.add(key)
        elif op == "remove":
            r = c.delete("/api/blacklist", json=body)
            expected = 409 if ftype == "standard" else (204 if key in model else 404)
            assert r.status_code == expected, (step, op, key)
            if ftype == "counting":
                model.discard(key)
        elif op == "check":
            verdict = check(c, key, "other")["verdict"]
            if key in model:
                assert verdict == "BLACKLISTED", (step, key)                 # never a false negative
            else:
                assert verdict in ("CLEAN", "FALSE_POSITIVE"), (step, key)   # never invented
        elif op == "rebuild":
            r = c.post("/api/filter/rebuild", json={"n": rng.choice([200, 400, 800]), "p": 0.01})
            assert r.status_code == 200 and r.get_json()["reinserted"] == len(model)
        else:
            c = new_app(tmp_path).test_client()
            assert not fs.rebuilt_on_startup()
        assert c.get("/api/filter").get_json()["item_count"] == len(model), (step, op)

    assert {e["item_key"] for e in all_entries(c)} == model
    assert fs.get_filter().count == len(model)
    assert all(check(c, k, "other")["verdict"] == "BLACKLISTED" for k in model)


# ---- pages ---------------------------------------------------------------------

def test_page_routing_rules(tmp_path):
    c = new_app(tmp_path).test_client()
    for path in PAGES:
        r = c.get(path)
        if path == "/setup":
            assert r.status_code == 200
        else:
            assert r.status_code == 302 and r.headers["Location"].endswith("/setup"), path
    assert c.get("/api/health").status_code == 200
    assert c.get("/static/missing.css").status_code == 404                    # not redirected

    create(c)
    for path in PAGES:
        r = c.get(path)
        if path == "/setup":
            assert r.status_code == 302 and r.headers["Location"].endswith("/")
        else:
            assert r.status_code == 200, path
    assert c.get("/not-a-page").status_code == 404
