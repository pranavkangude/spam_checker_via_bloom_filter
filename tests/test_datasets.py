"""C12: built-in dataset loaders and their API."""
import csv
import io

import pytest

from app import create_app
from db import database
from services import dataset_service as ds

CC_HEADER = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount", "Class"]


def cc_row(time, amount, klass):
    return [time] + ["0.5"] * 28 + [amount, klass]


def write_csv(path, header, rows, encoding="utf-8"):
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    path.write_bytes(buf.getvalue().encode(encoding))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(ds, "DATA_DIR", d)
    return d


@pytest.fixture
def client(tmp_path, data_dir):
    c = create_app(storage_dir=tmp_path / "store", testing=True).test_client()
    assert c.post("/api/filter", json={"name": "main", "type": "standard", "n": 5000, "p": 0.01}
                  ).status_code == 201
    return c


def load(client, **body):
    return client.post("/api/datasets/load", json=body)


def inv(d):
    return d["rows_read"] == d["rows_added"] + d["rows_duplicate"] + d["rows_invalid"]


def err(r, status, code=None, field=None):
    assert r.status_code == status, r.get_data(as_text=True)[:300]
    e = r.get_json()["error"]
    if code:
        assert e["code"] == code
    if field:
        assert e["field"] == field
    return e


# ---- listing ---------------------------------------------------------------

def test_list_reports_availability(client, data_dir):
    rows = {d["name"]: d for d in client.get("/api/datasets").get_json()}
    assert set(rows) == {"creditcard", "spam", "creditcard_sample", "spam_sample"}
    assert not any(d["available"] for d in rows.values())
    assert rows["creditcard"]["path"] == "data/creditcard.csv"
    assert rows["creditcard"]["download_url"].startswith("https://www.kaggle.com/")
    write_csv(data_dir / "creditcard.csv", CC_HEADER, [cc_row("1", "2.0", "1")])
    rows = {d["name"]: d for d in client.get("/api/datasets").get_json()}
    assert rows["creditcard"]["available"] and not rows["spam"]["available"]


def test_list_works_without_a_filter(tmp_path, data_dir):
    c = create_app(storage_dir=tmp_path / "s2", testing=True).test_client()
    assert c.get("/api/datasets").status_code == 200


# ---- credit card -----------------------------------------------------------

def test_creditcard_keys_and_counts(client, data_dir):
    rows = [cc_row("0", "149.62", "0"), cc_row("406", "0.0", "1"), cc_row("7", "12.5", "0"),
            cc_row("541", "1.5", "1"), cc_row("541", "1.5", "1"), cc_row("9", "3", "1.0")]
    write_csv(data_dir / "creditcard.csv", CC_HEADER, rows)
    r = load(client, name="creditcard")
    d = r.get_json()
    assert r.status_code == 200 and inv(d)
    # fraud rows are data rows 1, 3, 4 and 5 (zero based); rows 3 and 4 give different keys (row index differs)
    assert (d["rows_read"], d["rows_added"], d["rows_duplicate"], d["rows_invalid"]) == (4, 4, 0, 0)
    assert d["source"] == "creditcard"
    check = client.post("/api/check", json={"item": "TXN-1-406-0.0", "key_type": "transaction_id"}).get_json()
    assert check["verdict"] == "BLACKLISTED" and check["label"] == "fraud"
    assert client.post("/api/check", json={"item": "TXN-0-0-149.62", "key_type": "transaction_id"}
                       ).get_json()["verdict"] in ("CLEAN", "FALSE_POSITIVE")
    with database.connection() as conn:
        assert conn.execute("SELECT DISTINCT source FROM blacklist_entries").fetchall()[0][0] == "creditcard"
        assert conn.execute("SELECT file_name FROM import_jobs").fetchone()[0] == "creditcard.csv"
    d2 = load(client, name="creditcard").get_json()                    # again: all duplicates
    assert (d2["rows_added"], d2["rows_duplicate"]) == (0, 4)


def test_creditcard_limit_bom_blank_lines_and_short_rows(client, data_dir):
    rows = [cc_row(str(i), "1.0", "1") for i in range(10)]
    body = io.StringIO(newline="")
    w = csv.writer(body)
    w.writerow(CC_HEADER)
    w.writerows(rows[:3])
    body.write("\r\n")                                               # blank line
    w.writerow(["5", "1.0"])                                         # short row
    w.writerows(rows[3:])
    (data_dir / "creditcard.csv").write_bytes(b"\xef\xbb\xbf" + body.getvalue().encode())
    d = load(client, name="creditcard").get_json()
    assert inv(d) and (d["rows_added"], d["rows_invalid"]) == (10, 1)
    # limit stops quietly after that many keys (the short row counts as one)
    d = load(client, name="creditcard", limit=4).get_json()
    assert d["rows_read"] == 4 and inv(d)


def test_creditcard_bad_files(client, data_dir):
    path = data_dir / "creditcard.csv"
    path.write_bytes(b"")
    err(load(client, name="creditcard"), 400, "VALIDATION_ERROR", "name")
    write_csv(path, ["Time", "Amount"], [["1", "2"]])
    e = err(load(client, name="creditcard"), 400, "VALIDATION_ERROR", "name")
    assert "Class" in e["message"]
    assert client.get("/api/filter").get_json()["item_count"] == 0


# ---- spam --------------------------------------------------------------------

def test_spam_two_layouts_and_hashing(client, data_dir):
    write_csv(data_dir / "spam_ham_dataset.csv", ["", "label", "text", "label_num"], [
        ["0", "ham", "Hello  there", "0"],
        ["1", "spam", "Buy NOW  cheap", "1"],
        ["2", "spam", "buy now cheap", "1"],          # same text after normalising: duplicate
        ["3", "spam", "   ", "1"],                    # spam without text: invalid
        ["4", "spam", "Another offer", "1"],
    ])
    d = load(client, name="spam").get_json()
    assert inv(d) and (d["rows_read"], d["rows_added"], d["rows_duplicate"], d["rows_invalid"]) == (4, 2, 1, 1)
    assert d["source"] == "spam"
    with database.connection() as conn:
        keys = [r[0] for r in conn.execute("SELECT item_key FROM blacklist_entries")]
        assert all(k.startswith("SPAM-") and len(k) == 37 for k in keys)
        assert conn.execute("SELECT DISTINCT label FROM blacklist_entries").fetchall()[0][0] == "spam"


def test_spam_sms_layout_with_latin1_bytes(tmp_path, data_dir):
    c = create_app(storage_dir=tmp_path / "s3", testing=True).test_client()
    c.post("/api/filter", json={"name": "m", "type": "standard", "n": 100, "p": 0.01})
    write_csv(data_dir / "spam.csv", ["v1", "v2"], [["ham", "ok café"], ["spam", "WIN £100 now"]],
              encoding="latin-1")
    d = load(c, name="spam").get_json()
    assert d["rows_read"] == 1 and d["rows_added"] == 1


def test_spam_needs_columns(client, data_dir):
    write_csv(data_dir / "spam_ham_dataset.csv", ["a", "b"], [["1", "2"]])
    err(load(client, name="spam"), 400, "VALIDATION_ERROR", "name")


def test_unparseable_file_changes_nothing(client, data_dir):
    huge = "x" * 200_000                                             # over the csv field limit
    write_csv(data_dir / "spam_ham_dataset.csv", ["label", "text"],
              [["spam", "fine one"], ["spam", "fine two"], ["spam", huge], ["spam", "fine three"]])
    err(load(client, name="spam"), 400, "VALIDATION_ERROR", "name")
    assert client.get("/api/filter").get_json()["item_count"] == 0
    with database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0


# ---- request validation ---------------------------------------------------------

def test_missing_file_is_404_with_instructions(client, data_dir):
    e = err(load(client, name="creditcard"), 404, "NOT_FOUND", "name")
    assert "creditcard.csv" in e["message"] and "kaggle" in e["message"].lower()
    e = err(load(client, name="creditcard_sample"), 404)
    assert "sample_creditcard.csv" in e["message"]


@pytest.mark.parametrize("body,status", [
    ({}, 400), ({"name": 5}, 400), ({"name": "nope"}, 400), ({"name": "../secret"}, 400),
    ({"name": "creditcard", "limit": 0}, 400), ({"name": "creditcard", "limit": "5"}, 400),
    ({"name": "creditcard", "limit": True}, 400), ({"name": "creditcard", "limit": 1.5}, 400),
    ({"name": "creditcard", "limit": 200_001}, 413),
])
def test_bad_requests(client, data_dir, body, status):
    write_csv(data_dir / "creditcard.csv", CC_HEADER, [cc_row("1", "1", "1")])
    assert load(client, **body).status_code == status
    assert client.get("/api/filter").get_json()["item_count"] == 0


def test_non_json_body_is_400(client):
    assert client.post("/api/datasets/load", data="x", headers={"Content-Type": "text/plain"}).status_code == 400


def test_more_than_cap_without_limit_is_413_and_rolls_back(client, data_dir, monkeypatch):
    monkeypatch.setattr(ds, "MAX_DATASET_KEYS", 3)
    write_csv(data_dir / "creditcard.csv", CC_HEADER, [cc_row(str(i), "1", "1") for i in range(5)])
    err(load(client, name="creditcard"), 413, "PAYLOAD_TOO_LARGE", "limit")
    assert client.get("/api/filter").get_json()["item_count"] == 0
    assert load(client, name="creditcard", limit=3).get_json()["rows_added"] == 3


def test_no_filter_is_404(tmp_path, data_dir):
    c = create_app(storage_dir=tmp_path / "s4", testing=True).test_client()
    write_csv(data_dir / "creditcard.csv", CC_HEADER, [cc_row("1", "1", "1")])
    assert load(c, name="creditcard").status_code == 404


# ---- the sample files that ship with the project -----------------------------------

@pytest.fixture
def real_data_dir(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(ds, "DATA_DIR", Path(ds.__file__).resolve().parent.parent / "data")


def test_shipped_samples_load(tmp_path, real_data_dir):
    c = create_app(storage_dir=tmp_path / "s5", testing=True).test_client()
    c.post("/api/filter", json={"name": "m", "type": "standard", "n": 5000, "p": 0.01})
    rows = {d["name"]: d for d in c.get("/api/datasets").get_json()}
    assert rows["creditcard_sample"]["available"] and rows["spam_sample"]["available"]

    with open(ds.DATA_DIR / "sample_creditcard.csv", newline="") as f:
        frauds = sum(1 for r in csv.DictReader(f) if r["Class"] == "1")
    d = load(c, name="creditcard_sample").get_json()
    assert inv(d) and d["rows_read"] == frauds > 0 and d["rows_added"] == frauds

    with open(ds.DATA_DIR / "sample_spam.csv", newline="") as f:
        spam = sum(1 for r in csv.DictReader(f) if r["label"] == "spam")
    d = load(c, name="spam_sample").get_json()
    assert inv(d) and d["rows_read"] == spam > 0 and d["rows_added"] == spam
    assert c.get("/api/filter").get_json()["item_count"] == frauds + spam


def test_loaded_keys_survive_restart(tmp_path, real_data_dir):
    store = tmp_path / "s6"
    c = create_app(storage_dir=store, testing=True).test_client()
    c.post("/api/filter", json={"name": "m", "type": "standard", "n": 5000, "p": 0.01})
    load(c, name="creditcard_sample")
    n = c.get("/api/filter").get_json()["item_count"]
    c2 = create_app(storage_dir=store, testing=True).test_client()
    assert c2.get("/api/filter").get_json()["item_count"] == n
    with database.connection() as conn:
        key = conn.execute("SELECT item_key FROM blacklist_entries LIMIT 1").fetchone()[0]
    assert c2.post("/api/check", json={"item": key, "key_type": "transaction_id"}
                   ).get_json()["verdict"] == "BLACKLISTED"
