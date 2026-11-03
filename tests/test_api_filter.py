import pytest

from app import create_app
from services import filter_service as fs
from services.errors import ConflictError, NotFoundError


@pytest.fixture
def client(tmp_path):
    return create_app(storage_dir=tmp_path, testing=True).test_client()


def _make(tmp_path, ftype="standard", n=1000):
    create_app(storage_dir=tmp_path, testing=True)
    fs.create_filter("main", ftype, n, 0.01, confirm_replace=True)


def test_health_and_no_filter(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}
    r = client.get("/api/filter")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/").headers["Location"].endswith("/setup")


def test_calc_known_values(client):
    r = client.post("/api/filter/calc", json={"n": 1_000_000, "p": 0.01})
    d = r.get_json()
    assert d["m"] == 9_585_059 and d["k"] == 7 and d["bloom_bytes"] == 1_198_133


def test_calc_validation(client):
    assert client.post("/api/filter/calc", json={"n": 0, "p": 0.01}).status_code == 400
    assert client.post("/api/filter/calc", json={"n": 10, "p": 0.9}).status_code == 400
    assert client.post("/api/filter/calc", data="x").status_code == 400


def test_create_get_and_replace_needs_confirm(client):
    r = client.post("/api/filter", json={"name": "main", "type": "standard", "n": 1000, "p": 0.01})
    assert r.status_code == 201 and r.get_json()["item_count"] == 0
    assert client.get("/api/filter").status_code == 200
    r = client.post("/api/filter", json={"n": 1000, "p": 0.01})
    assert r.status_code == 409
    r = client.post("/api/filter", json={"n": 1000, "p": 0.01, "confirm_replace": True})
    assert r.status_code == 201


def test_duplicate_add_and_restart(tmp_path):
    _make(tmp_path)
    fs.add_item("  Bad@Mail.COM ", "email", "spam")
    with pytest.raises(ConflictError):
        fs.add_item("bad@mail.com", "email")
    assert fs.get_info()["item_count"] == 1
    create_app(storage_dir=tmp_path, testing=True)          # simulated restart
    assert "bad@mail.com" in fs.get_filter()
    assert not fs.rebuilt_on_startup()


def test_corrupt_file_triggers_rebuild(tmp_path):
    _make(tmp_path)
    fs.add_item("txn_1", "transaction_id")
    (tmp_path / "filter_state.bin").write_bytes(b"garbage")
    create_app(storage_dir=tmp_path, testing=True)
    assert fs.rebuilt_on_startup()
    assert "txn_1" in fs.get_filter()


def test_add_many_invariant(tmp_path):
    _make(tmp_path)
    s = fs.add_many(["a", "b", "a", "   ", "c"], "other", "fraud", "synthetic")
    assert (s["rows_read"], s["rows_added"], s["rows_duplicate"], s["rows_invalid"]) == (5, 3, 1, 1)
    assert s["rows_read"] == s["rows_added"] + s["rows_duplicate"] + s["rows_invalid"]
    assert fs.get_info()["item_count"] == 3


def test_remove_rules(tmp_path):
    _make(tmp_path, "standard")
    fs.add_item("x", "other")
    with pytest.raises(ConflictError):
        fs.remove_item("x", "other")
    _make(tmp_path, "counting")
    fs.add_item("txn1", "transaction_id")
    fs.remove_item("txn1", "transaction_id")
    assert "txn1" not in fs.get_filter() and fs.get_info()["item_count"] == 0
    with pytest.raises(NotFoundError):
        fs.remove_item("txn1", "transaction_id")


def test_rebuild_keeps_items_and_reset(tmp_path):
    _make(tmp_path, n=100)
    keys = [f"k{i}" for i in range(50)]
    fs.add_many(keys, "other", "fraud", "synthetic")
    out = fs.rebuild(5000, 0.01)
    assert out["reinserted"] == 50 and out["filter"]["n_capacity"] == 5000
    assert all(k in fs.get_filter() for k in keys)
    fs.reset_all()
    assert not fs.has_filter()
