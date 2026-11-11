"""C13: batch check service and API."""
import csv
import io
import time

import pytest

from app import create_app
from services import batch_service as bs
from services import check_service

J = {"Content-Type": "application/json"}


@pytest.fixture
def client(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.post("/api/filter", json={"name": "main", "type": "standard", "n": 2000, "p": 0.01}
                  ).status_code == 201
    for i in range(50):
        assert c.post("/api/blacklist", json={"item": f"bad_{i}", "key_type": "transaction_id",
                                              "label": "spam" if i % 2 else "fraud"}).status_code == 201
    return c


def batch(client, items, query="", **extra):
    return client.post("/api/check/batch" + query,
                       json={"items": items, "key_type": "transaction_id", **extra})


def upload(client, name, content, query="", **form):
    return client.post("/api/check/batch" + query, data={"file": (io.BytesIO(content), name), **form},
                       content_type="multipart/form-data")


def err(r, status, code=None, field=None):
    assert r.status_code == status, r.get_data(as_text=True)[:300]
    e = r.get_json()["error"]
    if code:
        assert e["code"] == code
    if field:
        assert e["field"] == field
    return e


def total_ok(s):
    return s["total"] == (s["clean"] + s["blacklisted"] + s["false_positive"]
                          + s["possibly_blacklisted"] + s["invalid"])


# ---- JSON batches -----------------------------------------------------------------

def test_mixed_batch_summary_and_order(client):
    r = batch(client, ["bad_1", "never_seen_zz", "", "bad_2", "   "])
    d = r.get_json()
    assert r.status_code == 200 and d["mode"] == "two_stage"
    assert total_ok(d["summary"]) and d["summary"]["total"] == 5
    assert d["summary"]["blacklisted"] == 2 and d["summary"]["invalid"] == 2
    assert [x["row"] for x in d["results"]] == [1, 2, 3, 4, 5]
    assert [x["item"] for x in d["results"]] == ["bad_1", "never_seen_zz", "", "bad_2", "   "]
    first, bad = d["results"][0], d["results"][2]
    assert first["verdict"] == "BLACKLISTED" and first["label"] == "spam" and first["exact_result"] == "FOUND"
    assert bad["verdict"] == "INVALID" and bad["item_key"] is None and bad["note"]
    assert d["results"][1]["verdict"] in ("CLEAN", "FALSE_POSITIVE")
    assert isinstance(d["duration_s"], float)


def test_no_false_negatives_and_matches_single_check(client):
    items = [f"bad_{i}" for i in range(50)] + [f"clean_{i}" for i in range(300)]
    d = batch(client, items).get_json()
    assert total_ok(d["summary"]) and d["summary"]["blacklisted"] == 50
    for row in d["results"]:
        single = check_service.check_item(row["item"], "transaction_id", log_it=False)
        assert row["verdict"] == single["verdict"] and row["item_key"] == single["item_key"]
        if row["item"].startswith("bad_"):
            assert row["verdict"] == "BLACKLISTED"


def test_false_positives_are_reported_not_blacklisted(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    c.post("/api/filter", json={"name": "tiny", "type": "standard", "n": 50, "p": 0.5})
    c.post("/api/blacklist/generate", json={"count": 200, "prefix": "b_"})        # over capacity
    d = batch(c, [f"unseen_{i}" for i in range(500)]).get_json()
    assert d["summary"]["false_positive"] > 0 and d["summary"]["blacklisted"] == 0
    assert total_ok(d["summary"])
    fp = next(x for x in d["results"] if x["verdict"] == "FALSE_POSITIVE")
    assert fp["bloom_result"] == "PROBABLE" and fp["exact_result"] == "NOT_FOUND" and fp["label"] is None


def test_bloom_only_mode(client):
    d = batch(client, ["bad_1", "never_seen_zz"], mode="bloom_only").get_json()
    assert d["results"][0]["verdict"] == "POSSIBLY_BLACKLISTED" and d["results"][0]["exact_result"] is None
    assert d["summary"]["possibly_blacklisted"] >= 1 and total_ok(d["summary"])


def test_batch_is_not_logged_but_single_checks_are(client):
    batch(client, ["bad_1", "x1", "x2"])
    assert client.get("/api/history").get_json()["total"] == 0
    assert client.get("/api/filter").get_json()["counters"]["checks"] == 0


def test_key_types_are_normalised(client):
    client.post("/api/blacklist", json={"item": "Spam@Mail.COM", "key_type": "email", "label": "spam"})
    d = client.post("/api/check/batch", json={"items": ["  spam@mail.com ", "SPAM@MAIL.COM"],
                                              "key_type": "email"}).get_json()
    assert d["summary"]["blacklisted"] == 2 and d["results"][0]["item_key"] == "spam@mail.com"


# ---- request validation -------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {}, {"items": "bad_1"}, {"items": []}, {"items": [1, 2]}, {"items": ["ok", None]},
    {"items": {"a": 1}}, {"items": ["a"], "key_type": "nope"}, {"items": ["a"], "key_type": 5},
    {"items": ["a"], "mode": "nope"}, {"items": ["a"], "mode": ["two_stage"]},
])
def test_bad_json_bodies_are_400(client, body):
    err(client.post("/api/check/batch", json=body), 400, "VALIDATION_ERROR")


def test_non_json_and_bad_format(client):
    assert client.post("/api/check/batch", data="x", headers={"Content-Type": "text/plain"}).status_code == 400
    assert client.post("/api/check/batch").status_code == 400
    err(batch(client, ["a"], query="?format=xml"), 400, "VALIDATION_ERROR", "format")


def test_over_the_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(bs, "MAX_BATCH", 5)
    err(batch(client, [f"i{i}" for i in range(6)]), 413, "PAYLOAD_TOO_LARGE", "items")
    assert batch(client, [f"i{i}" for i in range(5)]).status_code == 200            # exactly at the limit
    err(upload(client, "big.txt", b"\n".join(b"i%d" % i for i in range(6))), 413, "PAYLOAD_TOO_LARGE")


def test_no_filter_is_404(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.post("/api/check/batch", json={"items": ["a"]}).status_code == 404


def test_get_is_405(client):
    assert client.get("/api/check/batch").status_code == 405


# ---- file uploads -----------------------------------------------------------------------

def test_txt_upload(client):
    d = upload(client, "list.txt", b"bad_3\n\nnever_zz\nbad_4\n", key_type="transaction_id").get_json()
    assert d["summary"]["total"] == 3 and d["summary"]["blacklisted"] == 2 and total_ok(d["summary"])


def test_csv_upload_with_column_and_short_rows(client):
    body = b"id,txn\n1,bad_5\n2,never_zz\n3\n4,bad_6\n"
    d = upload(client, "t.csv", body, column="txn", key_type="transaction_id", mode="two_stage").get_json()
    s = d["summary"]
    assert s["total"] == 4 and s["blacklisted"] == 2 and s["invalid"] == 1 and total_ok(s)
    d = upload(client, "t.csv", b"id,txn\nbad_1,x\n", key_type="transaction_id").get_json()   # default: first column
    assert d["summary"]["blacklisted"] == 1


def test_bad_uploads(client):
    err(upload(client, "x.exe", b"a"), 400, "VALIDATION_ERROR", "file")
    err(upload(client, "x.txt", b""), 400, "VALIDATION_ERROR", "file")
    err(upload(client, "x.csv", b"id,txn\n"), 400, "VALIDATION_ERROR", "file")        # header only
    err(upload(client, "x.csv", b"id,txn\n1,a\n", column="phone"), 400, "VALIDATION_ERROR", "column")
    err(upload(client, "x.txt", b"a", key_type="bad"), 400, "VALIDATION_ERROR", "key_type")
    err(client.post("/api/check/batch", data={"key_type": "other"}, content_type="multipart/form-data"),
        400, "VALIDATION_ERROR", "file")


# ---- CSV download --------------------------------------------------------------------------

def test_csv_download(client):
    r = batch(client, ["bad_1", "never_seen_zz", ""], query="?format=csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"] and ".csv" in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == bs.CSV_COLUMNS and len(rows) == 4
    assert rows[1][:5] == ["1", "bad_1", "bad_1", "BLACKLISTED", "spam"]
    assert rows[3][3] == "INVALID" and rows[3][7]
    d = batch(client, ["bad_1", "never_seen_zz", ""]).get_json()          # same data as the JSON answer
    assert [r_[3] for r_ in rows[1:]] == [x["verdict"] for x in d["results"]]


def test_csv_cannot_carry_a_formula(client):
    evil = ["=HYPERLINK(\"http://x\")", "+1+1", "-2", "@SUM(A1)"]
    r = client.post("/api/check/batch?format=csv", json={"items": evil, "key_type": "other"})
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    for line, original in zip(rows[1:], evil):
        assert line[1] == "'" + original and line[2].startswith("'")
    assert bs.results_to_csv([{"row": 1, "item": "ok", "item_key": "ok", "verdict": "CLEAN", "label": None,
                               "bloom_result": "ABSENT", "exact_result": None, "note": None}]).count("'") == 0


# ---- size and speed ------------------------------------------------------------------------------

def test_twenty_thousand_items_quickly(client):
    items = [f"bad_{i % 50}" if i % 10 == 0 else f"clean_{i}" for i in range(20_000)]
    started = time.perf_counter()
    d = batch(client, items).get_json()
    assert time.perf_counter() - started < 20
    assert d["summary"]["total"] == 20_000 and total_ok(d["summary"])
    assert d["summary"]["blacklisted"] == 2_000                     # none of them may be missed
