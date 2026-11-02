import sqlite3

import pytest

from app import create_app
from db import database
from services import check_service, filter_service as fs


@pytest.fixture
def client(tmp_path):
    return create_app(storage_dir=tmp_path, testing=True).test_client()


def _new(client, ftype="standard", n=1000, p=0.01):
    r = client.post("/api/filter", json={"name": "main", "type": ftype, "n": n, "p": p,
                                         "confirm_replace": True})
    assert r.status_code == 201
    return r.get_json()


def _add(client, item, key_type="transaction_id", label="fraud"):
    return client.post("/api/blacklist", json={"item": item, "key_type": key_type, "label": label})


def _check(client, item, key_type="transaction_id", mode="two_stage"):
    return client.post("/api/check", json={"item": item, "key_type": key_type, "mode": mode})


# ---- B4: blacklist -----------------------------------------------------------

def test_add_then_check_is_blacklisted(client):
    _new(client)
    r = _add(client, "txn_88231", label="fraud")
    assert r.status_code == 201 and r.get_json() == {"item_key": "txn_88231", "added": True}
    d = _check(client, "txn_88231").get_json()
    assert d["verdict"] == "BLACKLISTED" and d["bloom_result"] == "PROBABLE"
    assert d["exact_result"] == "FOUND" and d["label"] == "fraud"
    assert d["bits_set"] == d["k"] == len(d["indexes"]) and isinstance(d["latency_us"], int)


def test_duplicate_add_returns_409_and_count_unchanged(client):
    _new(client)
    assert _add(client, "a").status_code == 201
    r = _add(client, "a")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "DUPLICATE"
    assert client.get("/api/filter").get_json()["item_count"] == 1


def test_add_validation(client):
    _new(client)
    assert client.post("/api/blacklist", json={"item": "   "}).status_code == 400
    assert client.post("/api/blacklist", json={"item": 5}).status_code == 400
    assert client.post("/api/blacklist", json={"item": "x" * 2049}).status_code == 400
    assert client.post("/api/blacklist", json={"item": "x", "key_type": "nope"}).status_code == 400
    assert client.post("/api/blacklist", json={"item": "x", "label": "nope"}).status_code == 400
    assert client.post("/api/blacklist", data="not json").status_code == 400


def test_normalization_is_shared_by_add_and_check(client):
    _new(client)
    _add(client, "  Spammer@Mail.COM ", "email", "spam")
    d = _check(client, "SPAMMER@mail.com", "email").get_json()
    assert d["verdict"] == "BLACKLISTED" and d["item_key"] == "spammer@mail.com"
    assert d["label"] == "spam"


def test_list_paging_and_filters(client):
    _new(client)
    for i in range(5):
        _add(client, f"txn_{i}", "transaction_id", "fraud")
    _add(client, "a@b.com", "email", "spam")
    _add(client, "http://Bad.Site/Login/", "url", "phishing")
    d = client.get("/api/blacklist?page_size=3").get_json()
    assert d["total"] == 7 and d["page"] == 1 and len(d["items"]) == 3
    assert d["items"][0]["item_key"] == "http://bad.site/Login"          # newest first; path case kept
    assert len(client.get("/api/blacklist?page_size=3&page=3").get_json()["items"]) == 1
    assert client.get("/api/blacklist?key_type=email").get_json()["total"] == 1
    assert client.get("/api/blacklist?label=fraud").get_json()["total"] == 5
    assert client.get("/api/blacklist?q=TXN_3").get_json()["total"] == 1
    assert client.get("/api/blacklist?q=zzz").get_json()["total"] == 0
    assert client.get("/api/blacklist?q=%25").get_json()["total"] == 0   # '%' is literal


@pytest.mark.parametrize("query", ["page_size=101", "page_size=0", "page=0", "page=x",
                                   "key_type=bad", "label=bad"])
def test_list_validation(client, query):
    _new(client)
    assert client.get(f"/api/blacklist?{query}").status_code == 400


def test_remove_rules(client):
    _new(client, "standard")
    _add(client, "x")
    r = client.delete("/api/blacklist", json={"item": "x", "key_type": "transaction_id"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "CONFLICT"

    _new(client, "counting")
    _add(client, "x")
    assert _check(client, "x").get_json()["verdict"] == "BLACKLISTED"
    r = client.delete("/api/blacklist", json={"item": "x", "key_type": "transaction_id"})
    assert r.status_code == 204
    assert _check(client, "x").get_json()["verdict"] == "CLEAN"
    assert client.get("/api/filter").get_json()["item_count"] == 0
    r = client.delete("/api/blacklist", json={"item": "x", "key_type": "transaction_id"})
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "NOT_FOUND"


# ---- B5: check ---------------------------------------------------------------

def test_never_added_is_never_blacklisted(client):
    _new(client, n=1000)
    for i in range(100):
        _add(client, f"fraud_{i}")
    seen = set()
    for i in range(300):
        v = _check(client, f"clean_{i}").get_json()["verdict"]
        seen.add(v)
    assert seen <= {"CLEAN", "FALSE_POSITIVE"} and "CLEAN" in seen


def test_false_positive_verdict_and_log(client):
    _new(client, n=10, p=0.5)                   # tiny filter, overfilled below
    fs.add_many([f"k{i}" for i in range(500)], "transaction_id", "fraud", "synthetic")
    d = _check(client, "never_added").get_json()
    assert d["bloom_result"] == "PROBABLE" and d["exact_result"] == "NOT_FOUND"
    assert d["verdict"] == "FALSE_POSITIVE" and d["label"] is None
    assert client.get("/api/filter").get_json()["counters"]["false_positives"] == 1


def test_bloom_only_mode(client):
    _new(client)
    _add(client, "x")
    d = _check(client, "x", mode="bloom_only").get_json()
    assert d["verdict"] == "POSSIBLY_BLACKLISTED" and d["exact_result"] is None
    d = _check(client, "definitely_other", mode="bloom_only").get_json()
    assert d["verdict"] in ("CLEAN", "POSSIBLY_BLACKLISTED")


def test_check_agrees_with_filter_contains(client):
    _new(client, "counting")
    _add(client, "a")
    for item in ("a", "b", "c"):
        d = _check(client, item, mode="bloom_only").get_json()
        assert (d["bloom_result"] == "PROBABLE") == (item in fs.get_filter())


def test_check_validation_and_no_filter(client):
    assert _check(client, "x").status_code == 404                     # no filter yet
    _new(client)
    assert _check(client, "x", mode="bad").status_code == 400
    assert _check(client, "x", key_type="bad").status_code == 400
    assert _check(client, "  ").status_code == 400
    assert client.post("/api/check", json={"key_type": "other"}).status_code == 400
    assert client.post("/api/check", data="x").status_code == 400


def test_restart_keeps_results(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    _new(c)
    _add(c, "persist_me")
    c2 = create_app(storage_dir=tmp_path, testing=True).test_client()    # restart
    assert _check(c2, "persist_me").get_json()["verdict"] == "BLACKLISTED"


def test_rebuild_larger_n_keeps_items_detectable(client):
    _new(client, n=100)
    keys = [f"k{i}" for i in range(80)]
    fs.add_many(keys, "transaction_id", "fraud", "synthetic")
    assert client.post("/api/filter/rebuild", json={"n": 5000, "p": 0.01}).status_code == 200
    assert all(_check(client, k).get_json()["verdict"] == "BLACKLISTED" for k in keys)


# ---- B5: history, counters, logging -----------------------------------------

def test_history_and_counters(client):
    _new(client)
    _add(client, "bad")
    _check(client, "bad")
    _check(client, "good1")
    _check(client, "good2")
    h = client.get("/api/history").get_json()
    assert h["total"] == 3 and h["items"][0]["item_key"] == "good2"      # newest first
    assert set(h["items"][0]) >= {"id", "verdict", "latency_us", "checked_at", "mode"}
    assert client.get("/api/history?verdict=BLACKLISTED").get_json()["total"] == 1
    assert client.get("/api/history?page_size=2").get_json()["items"].__len__() == 2
    assert client.get("/api/history?verdict=NOPE").status_code == 400
    assert client.get("/api/history?page_size=101").status_code == 400
    c = client.get("/api/filter").get_json()["counters"]
    assert c["checks"] == 3 and c["blacklisted"] == 1 and c["clean"] + c["false_positives"] == 2
    assert client.delete("/api/history").status_code == 204
    assert client.get("/api/history").get_json()["total"] == 0
    assert client.get("/api/filter").get_json()["counters"]["checks"] == 0


def test_log_table_is_capped(client, monkeypatch):
    _new(client)
    monkeypatch.setattr(database, "MAX_LOG_ROWS", 5)
    for i in range(12):
        _check(client, f"x{i}")
    h = client.get("/api/history?page_size=100").get_json()
    assert h["total"] == 5 and h["items"][0]["item_key"] == "x11"


def test_prune_helper_caps_at_10000(tmp_path):
    create_app(storage_dir=tmp_path, testing=True)
    with database.connection() as conn:
        conn.executemany(
            "INSERT INTO check_logs (item_key, key_type, mode, bloom_result, verdict, latency_us) "
            "VALUES (?, 'other', 'two_stage', 'ABSENT', 'CLEAN', 1)",
            [(f"k{i}",) for i in range(10_050)],
        )
        database.prune_check_logs(conn)
        assert conn.execute("SELECT COUNT(*) FROM check_logs").fetchone()[0] == 10_000


def test_log_failure_does_not_fail_check(client, monkeypatch):
    _new(client)
    _add(client, "x")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(check_service, "_write_log", boom)
    r = _check(client, "x")
    assert r.status_code == 200 and r.get_json()["verdict"] == "BLACKLISTED"
