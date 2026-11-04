import io

import pytest

from app import create_app
from db import database
from services import filter_service as fs


@pytest.fixture
def client(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    r = c.post("/api/filter", json={"name": "main", "type": "standard", "n": 5000, "p": 0.01})
    assert r.status_code == 201
    return c


def _upload(client, name, content, **form):
    data = {"file": (io.BytesIO(content), name), **form}
    return client.post("/api/blacklist/bulk", data=data, content_type="multipart/form-data")


def _inv(d):
    return d["rows_read"] == d["rows_added"] + d["rows_duplicate"] + d["rows_invalid"]


def _check(client, item, key_type="other"):
    return client.post("/api/check", json={"item": item, "key_type": key_type}).get_json()


# ---- CSV / TXT upload --------------------------------------------------------

def test_csv_column_counts_and_invariant(client):
    body = b"id,email\n1,A@x.com\n2,a@x.com\n3,\n4,b@x.com\n"
    r = _upload(client, "mails.csv", body, column="email", key_type="email", label="spam")
    d = r.get_json()
    assert r.status_code == 200 and _inv(d)
    assert (d["rows_read"], d["rows_added"], d["rows_duplicate"], d["rows_invalid"]) == (4, 2, 1, 1)
    assert d["source"] == "csv" and d["filter"]["item_count"] == 2 and d["job_id"] >= 1
    assert _check(client, "A@X.COM", "email")["verdict"] == "BLACKLISTED"
    assert client.get("/api/filter").get_json()["item_count"] == 2


def test_csv_default_first_column_bom_and_short_rows(client):
    body = b"\xef\xbb\xbfid,note\n10,a\n11\n12,c\n"          # BOM, row 2 has no second column
    d = _upload(client, "x.csv", body).get_json()
    assert d["rows_added"] == 3 and _inv(d)
    d = _upload(client, "y.csv", b"id,note\n1,a\n2\n", column="note").get_json()
    assert (d["rows_added"], d["rows_invalid"]) == (1, 1)     # short row -> invalid


def test_csv_unknown_column_is_400(client):
    r = _upload(client, "x.csv", b"id,email\n1,a\n", column="phone")
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "column"


def test_txt_skips_blank_lines_and_counts_duplicates(client):
    d = _upload(client, "list.txt", b"a\n\nb\na\n   \nc\n").get_json()
    assert (d["rows_read"], d["rows_added"], d["rows_duplicate"], d["rows_invalid"]) == (4, 3, 1, 0)


def test_latin1_fallback(client):
    d = _upload(client, "latin.txt", "café\n".encode("latin-1")).get_json()
    assert d["rows_added"] == 1
    assert _check(client, "café")["verdict"] == "BLACKLISTED"


def test_bad_uploads(client):
    assert client.post("/api/blacklist/bulk", data={}).status_code == 400          # no file
    assert _upload(client, "x.exe", b"a").status_code == 400                       # extension
    assert _upload(client, "x.csv", b"").status_code == 400                        # empty
    assert _upload(client, "x.csv", b"   \n").status_code == 400
    assert _upload(client, "x.txt", b"a", key_type="bad").status_code == 400
    assert _upload(client, "x.txt", b"a", label="bad").status_code == 400


def test_upload_over_20mb_is_413(client):
    r = _upload(client, "big.txt", b"x\n" * (11 * 1024 * 1024))
    assert r.status_code == 413
    assert r.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_parse_failure_rolls_back_everything(client):
    huge = b"x" * 200_000                                       # over the csv field limit
    r = _upload(client, "bad.csv", b"id\nok1\nok2\n" + huge + b"\nok3\n")
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "file"
    assert client.get("/api/filter").get_json()["item_count"] == 0
    assert _check(client, "ok1")["bloom_result"] == "ABSENT"
    with database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM blacklist_entries").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 0


def test_import_job_row_and_restart(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    c.post("/api/filter", json={"name": "main", "type": "standard", "n": 1000, "p": 0.01})
    d = _upload(c, "one.txt", b"k1\nk2\nk2\n").get_json()
    with database.connection() as conn:
        row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (d["job_id"],)).fetchone()
    assert (row["source"], row["file_name"], row["rows_read"], row["rows_added"],
            row["rows_duplicate"]) == ("csv", "one.txt", 3, 2, 1)
    c2 = create_app(storage_dir=tmp_path, testing=True).test_client()      # restart
    assert not fs.rebuilt_on_startup()                                     # snapshot saved once, valid
    assert _check(c2, "k2")["verdict"] == "BLACKLISTED"


# ---- synthetic generator -----------------------------------------------------

def test_generate_then_again_is_all_duplicates(client):
    r = client.post("/api/blacklist/generate", json={"count": 2000, "prefix": "fraud_txn_"})
    d = r.get_json()
    assert r.status_code == 200 and d["rows_added"] == 2000 and d["source"] == "synthetic" and _inv(d)
    assert all(f"fraud_txn_{i}" in fs.get_filter() for i in range(2000))     # 0 false negatives
    assert _check(client, "fraud_txn_5", "transaction_id")["verdict"] == "BLACKLISTED"
    d2 = client.post("/api/blacklist/generate", json={"count": 2000, "prefix": "fraud_txn_"}).get_json()
    assert (d2["rows_added"], d2["rows_duplicate"]) == (0, 2000)
    assert client.get("/api/filter").get_json()["item_count"] == 2000
    d3 = client.post("/api/blacklist/generate", json={"count": 10, "start": 1995}).get_json()
    assert (d3["rows_added"], d3["rows_duplicate"]) == (5, 5)


def test_generate_over_capacity_flag(client):
    d = client.post("/api/blacklist/generate", json={"count": 6000, "prefix": "o_"}).get_json()
    assert d["filter"]["over_capacity"] is True
    assert client.get("/api/filter").get_json()["over_capacity"] is True


@pytest.mark.parametrize("body,status", [
    ({"count": 0}, 400), ({"count": "5"}, 400), ({"count": True}, 400), ({}, 400),
    ({"count": 500_001}, 413), ({"count": 5, "label": "bad"}, 400),
    ({"count": 5, "prefix": "p" * 51}, 400), ({"count": 5, "prefix": 7}, 400),
    ({"count": 5, "start": -1}, 400), ({"count": 5, "key_type": "bad"}, 400),
])
def test_generate_validation(client, body, status):
    assert client.post("/api/blacklist/generate", json=body).status_code == status
    assert client.get("/api/filter").get_json()["item_count"] == 0


def test_import_without_filter_is_404(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.post("/api/blacklist/generate", json={"count": 5}).status_code == 404
    assert _upload(c, "x.txt", b"a").status_code == 404
