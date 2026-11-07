import threading

import pytest

from app import create_app
from core.hashing import hash_indexes
from core.visualizer import MAX_WORDS


@pytest.fixture
def client(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.post("/api/visualizer/reset", json={"m": 128, "k": 3}).status_code == 200
    return c


def _post(client, path, **body):
    return client.post(f"/api/visualizer/{path}", json=body)


# ---- state and reset ---------------------------------------------------------

def test_state_and_reset(client):
    d = client.get("/api/visualizer/state").get_json()
    assert d == {"m": 128, "k": 3, "bits": "0" * 128, "words": []}
    r = _post(client, "reset", m=64, k=2)
    assert r.status_code == 200 and r.get_json() == {"m": 64, "k": 2, "bits": "0" * 64}
    _post(client, "insert", item="hello")
    assert client.get("/api/visualizer/state").get_json()["words"] == ["hello"]
    _post(client, "reset", m=64, k=2)
    assert client.get("/api/visualizer/state").get_json()["words"] == []


def test_reset_without_body_uses_defaults(client):
    _post(client, "reset", m=32, k=5)
    r = client.post("/api/visualizer/reset")
    assert r.status_code == 200 and r.get_json()["m"] == 128 and r.get_json()["k"] == 3


@pytest.mark.parametrize("body,field", [
    ({"m": 8, "k": 3}, "m"), ({"m": 513, "k": 3}, "m"), ({"m": "a", "k": 3}, "m"),
    ({"m": True, "k": 3}, "m"), ({"m": 128.5, "k": 3}, "m"),
    ({"m": 128, "k": 0}, "k"), ({"m": 128, "k": 9}, "k"), ({"m": 128, "k": None}, "k"),
])
def test_reset_validation_names_the_field(client, body, field):
    r = client.post("/api/visualizer/reset", json=body)
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "VALIDATION_ERROR" and err["field"] == field
    assert client.get("/api/visualizer/state").get_json()["m"] == 128      # old filter kept


def test_reset_rejects_non_object_body(client):
    assert client.post("/api/visualizer/reset", data="nope").status_code == 400


# ---- insert and query --------------------------------------------------------

def test_insert_uses_real_hashing(client):
    d = _post(client, "insert", item=" hello ").get_json()
    assert d["item"] == "hello" and d["duplicate"] is False
    assert d["indexes"] == hash_indexes("hello", 128, 3)
    ones = {i for i, c in enumerate(d["bits"]) if c == "1"}
    assert ones == set(d["indexes"]) and len(d["bits"]) == 128
    again = _post(client, "insert", item="hello").get_json()
    assert again["duplicate"] is True and again["bits"] == d["bits"]


def test_query_inserted_and_absent(client):
    _post(client, "insert", item="hello")
    q = _post(client, "query", item="hello").get_json()
    assert q["result"] == "PROBABLE" and q["bit_values"] == [1, 1, 1]
    assert q["truly_inserted"] is True and q["false_positive"] is False
    assert set(q["explained_by"].values()) == {"hello"}
    assert len(q["bits"]) == 128 and "PROBABLY PRESENT" in q["message"]

    q = _post(client, "query", item="never").get_json()
    assert q["result"] == "ABSENT" and 0 in q["bit_values"] and q["false_positive"] is False
    assert "DEFINITELY NOT PRESENT" in q["message"]


def test_query_on_empty_filter_is_absent(client):
    q = _post(client, "query", item="anything").get_json()
    assert q["result"] == "ABSENT" and q["bit_values"] == [0, 0, 0]


@pytest.mark.parametrize("body", [{}, {"item": ""}, {"item": "   "}, {"item": 5},
                                  {"item": "x" * 2049}])
def test_item_validation(client, body):
    for path in ("insert", "query"):
        r = client.post(f"/api/visualizer/{path}", json=body)
        assert r.status_code == 400 and r.get_json()["error"]["field"] == "item"
    assert client.post("/api/visualizer/insert", data="x").status_code == 400


def test_word_limit_returns_409(client):
    for i in range(MAX_WORDS):
        assert _post(client, "insert", item=f"w{i}").status_code == 200
    r = _post(client, "insert", item="one_too_many")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "VISUALIZER_FULL"
    assert _post(client, "insert", item="w5").status_code == 200           # duplicate still fine
    _post(client, "reset", m=128, k=3)
    assert _post(client, "insert", item="one_too_many").status_code == 200


# ---- find false positive -----------------------------------------------------

def test_find_false_positive_found_and_explained(client):
    _post(client, "reset", m=64, k=2)
    words = [f"word{i}" for i in range(30)]
    for w in words:
        _post(client, "insert", item=w)
    d = _post(client, "find-false-positive", max_tries=200_000, seed=1).get_json()
    assert d["found"] is True and d["item"] not in words and d["tries"] >= 1
    assert set(d["explained_by"].values()) <= set(words) and len(d["explained_by"]) >= 1
    assert d["indexes"] == hash_indexes(d["item"], 64, 2)
    q = _post(client, "query", item=d["item"]).get_json()
    assert q["false_positive"] is True and q["result"] == "PROBABLE"
    assert _post(client, "find-false-positive", max_tries=200_000, seed=1).get_json() == d


def test_find_false_positive_on_empty_or_hopeless_filter(client):
    d = client.post("/api/visualizer/find-false-positive").get_json()      # no body at all
    assert d["found"] is False and d["item"] is None and "Insert some words" in d["message"]
    _post(client, "reset", m=512, k=8)
    _post(client, "insert", item="solo")
    r = _post(client, "find-false-positive", max_tries=50, seed=3)
    d = r.get_json()
    assert r.status_code == 200 and d["found"] is False and d["tries"] == 50


@pytest.mark.parametrize("body,field", [
    ({"max_tries": 0}, "max_tries"), ({"max_tries": 1_000_001}, "max_tries"),
    ({"max_tries": "x"}, "max_tries"), ({"max_tries": True}, "max_tries"),
    ({"seed": "x"}, "seed"), ({"seed": True}, "seed"), ({"seed": 1.5}, "seed"),
])
def test_find_false_positive_validation(client, body, field):
    r = client.post("/api/visualizer/find-false-positive", json=body)
    assert r.status_code == 400 and r.get_json()["error"]["field"] == field


# ---- isolation and threads ---------------------------------------------------

def test_works_without_a_main_filter_and_never_touches_it(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.get("/api/filter").status_code == 404                          # no main filter yet
    assert _post(c, "insert", item="hello").status_code == 200              # still works

    c.post("/api/filter", json={"name": "main", "type": "standard", "n": 1000, "p": 0.01})
    c.post("/api/blacklist", json={"item": "real_bad", "key_type": "other"})
    before = c.get("/api/filter").get_json()
    _post(c, "insert", item="demo_word")
    _post(c, "find-false-positive", max_tries=100, seed=1)
    _post(c, "reset", m=64, k=2)
    after = c.get("/api/filter").get_json()
    assert (after["item_count"], after["fill_ratio"]) == (before["item_count"], before["fill_ratio"])
    verdict = c.post("/api/check", json={"item": "demo_word", "key_type": "other"}).get_json()
    assert verdict["verdict"] == "CLEAN"                                    # demo words never leak
    assert c.get("/api/blacklist").get_json()["total"] == 1


def test_parallel_inserts_are_all_kept(tmp_path):
    app = create_app(storage_dir=tmp_path, testing=True)
    app.test_client().post("/api/visualizer/reset", json={"m": 512, "k": 3})
    errors = []

    def worker(t):
        c = app.test_client()
        for i in range(25):
            r = c.post("/api/visualizer/insert", json={"item": f"t{t}_{i}"})
            if r.status_code != 200:
                errors.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    state = app.test_client().get("/api/visualizer/state").get_json()
    assert not errors and len(state["words"]) == 200 == len(set(state["words"]))
    for w in state["words"]:
        assert all(state["bits"][i] == "1" for i in hash_indexes(w, 512, 3))   # no lost bits
