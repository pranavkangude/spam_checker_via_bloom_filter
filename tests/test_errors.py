"""B9: every failure must use the standard error JSON and never crash with a 500."""
import io
import sqlite3

import pytest

import app as app_module
from app import create_app
from db import database
from services import filter_service as fs
from services import import_service

J = {"Content-Type": "application/json"}


@pytest.fixture
def client(tmp_path):
    c = create_app(storage_dir=tmp_path, testing=True).test_client()
    assert c.post("/api/filter", json={"name": "main", "type": "counting", "n": 1000, "p": 0.01}
                  ).status_code == 201
    return c


def assert_error(r, status, code=None, field=None):
    assert r.status_code == status, r.get_data(as_text=True)[:200]
    err = r.get_json()["error"]
    assert isinstance(err["code"], str) and isinstance(err["message"], str) and err["message"]
    if code:
        assert err["code"] == code
    if field:
        assert err["field"] == field
    return err


def _upload(client, name, content):
    return client.post("/api/blacklist/bulk", data={"file": (io.BytesIO(content), name)},
                       content_type="multipart/form-data")


# ---- bad input that used to crash --------------------------------------------

@pytest.mark.parametrize("path,body", [
    ("/api/blacklist", '{"item": "\\ud800", "key_type": "other"}'),
    ("/api/blacklist", '{"item": "\\ud800", "key_type": "phone"}'),     # digits-only key, raw text bad
    ("/api/check", '{"item": "\\ud800"}'),
    ("/api/visualizer/insert", '{"item": "\\ud800"}'),
    ("/api/visualizer/query", '{"item": "\\ud800"}'),
])
def test_lone_surrogate_is_400_not_500(client, path, body):
    assert_error(client.post(path, data=body, headers=J), 400, "VALIDATION_ERROR")
    assert client.get("/api/filter").get_json()["item_count"] == 0


def test_lone_surrogate_remove_and_bulk_row(client):
    r = client.delete("/api/blacklist", data='{"item": "\\ud800"}', headers=J)
    assert_error(r, 400, "VALIDATION_ERROR", "item")
    out = fs.add_many(["ok", "bad\ud800", "ok2"], "other", "fraud", "synthetic")   # counted invalid
    assert (out["rows_added"], out["rows_invalid"]) == (2, 1)


def test_nul_character_is_stored_and_found(client):
    assert client.post("/api/blacklist", json={"item": "a\u0000b"}).status_code == 201
    assert client.post("/api/check", json={"item": "a\u0000b"}).get_json()["verdict"] == "BLACKLISTED"


def test_deeply_nested_json_is_400(client):
    for path in ("/api/check", "/api/blacklist", "/api/visualizer/reset", "/api/benchmark"):
        assert_error(client.post(path, data="[" * 100_000, headers=J), 400, "VALIDATION_ERROR")
    assert_error(client.delete("/api/filter", data="[" * 100_000, headers=J), 400)


@pytest.mark.parametrize("path", ["/api/experiments/" + "9" * 30,
                                  "/api/experiments/" + "9" * 30 + "/csv",
                                  "/api/experiments/0", "/api/jobs/" + "9" * 300])
def test_absurd_ids_are_404(client, path):
    assert_error(client.get(path), 404, "NOT_FOUND")


@pytest.mark.parametrize("body", ['{"n": NaN, "p": 0.01}', '{"n": 10, "p": Infinity}',
                                  '{"n": -Infinity, "p": 0.01}', '{"n": ' + "9" * 400 + ', "p": 0.01}',
                                  '{"n": 1e999, "p": 0.01}'])
def test_extreme_numbers_are_400(client, body):
    assert_error(client.post("/api/filter/calc", data=body, headers=J), 400, "VALIDATION_ERROR")


# ---- protocol-level errors ---------------------------------------------------

def test_unknown_path_and_wrong_method(client):
    assert_error(client.get("/api/nope"), 404, "NOT_FOUND")
    assert_error(client.get("/api/filter/"), 404, "NOT_FOUND")                  # no trailing slash
    r = client.delete("/api/health")
    assert_error(r, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in r.headers["Allow"]


def test_body_problems_are_400_with_a_hint(client):
    for r in (client.post("/api/check", data="not json", headers=J),
              client.post("/api/check", data='{"item":"x"}', headers={"Content-Type": "text/plain"}),
              client.post("/api/check", data=b"\xff\xfe", headers=J),            # not UTF-8
              client.post("/api/check", data="[1, 2]", headers=J),
              client.post("/api/check")):
        err = assert_error(r, 400, "VALIDATION_ERROR")
        assert "JSON" in err["message"]


def test_json_body_over_20mb_is_413(client):
    r = client.post("/api/check", data=b" " * (21 * 1024 * 1024) + b"{}", headers=J)
    assert_error(r, 413, "PAYLOAD_TOO_LARGE")


# ---- upload limits -----------------------------------------------------------

def test_upload_over_20mb_is_413_in_standard_json(client):
    assert_error(_upload(client, "big.txt", b"x\n" * (11 * 1024 * 1024)), 413, "PAYLOAD_TOO_LARGE")


def test_row_limit_is_413_and_rolls_back(client, monkeypatch):
    monkeypatch.setattr(import_service, "MAX_IMPORT_ROWS", 5)
    assert_error(_upload(client, "many.txt", b"\n".join(b"k%d" % i for i in range(10))),
                 413, "PAYLOAD_TOO_LARGE", "file")
    assert client.get("/api/filter").get_json()["item_count"] == 0              # nothing kept
    r = _upload(client, "ok.txt", b"\n".join(b"k%d" % i for i in range(5)))
    assert r.status_code == 200 and r.get_json()["rows_added"] == 5             # exactly at the limit


def test_upload_filename_cannot_escape(client):
    d = _upload(client, "../../etc/passwd.txt", b"x\n").get_json()
    with database.connection() as conn:
        name = conn.execute("SELECT file_name FROM import_jobs WHERE id = ?", (d["job_id"],)
                            ).fetchone()[0]
    assert name == "passwd.txt"


def test_upload_type_errors(client):
    assert_error(_upload(client, "x.exe", b"a"), 400, "VALIDATION_ERROR", "file")
    assert_error(_upload(client, "noext", b"a"), 400, "VALIDATION_ERROR", "file")
    assert_error(client.post("/api/blacklist/bulk", data={"column": "x"},
                             content_type="multipart/form-data"), 400, "VALIDATION_ERROR", "file")


# ---- unexpected failures -----------------------------------------------------

def test_unexpected_error_is_500_with_request_id_and_no_leak(client, monkeypatch):
    def boom():
        raise RuntimeError("secret database password")

    monkeypatch.setattr(fs, "get_info", boom)
    r = client.get("/api/filter")
    err = assert_error(r, 500, "INTERNAL_ERROR")
    assert len(err["request_id"]) == 8 and "secret" not in r.get_data(as_text=True)


def test_page_errors_are_plain_text_with_request_id(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("template exploded")

    monkeypatch.setattr(app_module, "render_template", boom)
    r = client.get("/check")
    assert r.status_code == 500 and "Request id:" in r.get_data(as_text=True)
    assert "exploded" not in r.get_data(as_text=True)


def test_database_busy_is_503_other_db_errors_are_500(client, monkeypatch):
    def locked():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(fs, "get_info", locked)
    assert_error(client.get("/api/filter"), 503, "DATABASE_BUSY")

    def broken():
        raise sqlite3.OperationalError("no such table: filters")

    monkeypatch.setattr(fs, "get_info", broken)
    assert_error(client.get("/api/filter"), 500, "INTERNAL_ERROR")


# ---- fuzz: no route may return 500 on garbage --------------------------------

GARBAGE_BODIES = [
    None, b"garbage", b"[]", b"null", b'"text"', b"123", b'{"wait": "x"}',
    b'{"sizes":"x","kind":"x","n":"x","p":"x","item":5,"key_type":5,"label":5,"mode":5,'
    b'"count":"x","m":"x","k":"x","max_tries":"x","seed":"x","confirm":"x","type":5,"name":5}',
]
GARBAGE_QUERIES = ["", "?page=-1", "?page=x&page_size=abc", "?page_size=101", "?q=%00&key_type=zz",
                   "?verdict=NOPE", "?label=%ff"]


def _urls(rule):
    url = rule.rule.replace("<int:exp_id>", "1").replace("<job_id>", "x")
    assert "<" not in url, f"unhandled converter in {rule.rule}"
    return url


def test_no_api_route_returns_500_on_garbage(client):
    client.post("/api/blacklist", json={"item": "keep_me", "key_type": "transaction_id"})
    app = client.application
    rules = [r for r in app.url_map.iter_rules() if r.rule.startswith("/api/")]
    assert len(rules) >= 25                                         # the whole API is covered
    for rule in rules:
        url = _urls(rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            attempts = ([(url + q, None) for q in GARBAGE_QUERIES] if method == "GET"
                        else [(url, body) for body in GARBAGE_BODIES])
            for target, body in attempts:
                kwargs = {"data": body, "headers": J} if body is not None else {}
                r = client.open(target, method=method, **kwargs)
                where = f"{method} {target} body={body!r:.60}"
                assert r.status_code < 500, where
                if r.status_code >= 400:
                    assert_error(r, r.status_code)
    # garbage changed nothing
    assert client.get("/api/filter").get_json()["item_count"] == 1
    v = client.post("/api/check", json={"item": "keep_me", "key_type": "transaction_id"})
    assert v.get_json()["verdict"] == "BLACKLISTED"
