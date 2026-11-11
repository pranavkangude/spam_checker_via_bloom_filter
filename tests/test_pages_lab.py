"""The Lab pages (C8-C10) render and load their scripts; Chart.js is served locally."""
import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(storage_dir=tmp_path, testing=True)
    c = app.test_client()
    r = c.post("/api/filter", json={"name": "main", "type": "standard", "n": 1000, "p": 0.01,
                                    "confirm_replace": True})
    assert r.status_code == 201
    return c


@pytest.mark.parametrize("path,script", [
    ("/benchmark", "js/benchmark.js"),
    ("/experiments", "js/experiments.js"),
    ("/visualizer", "js/visualizer.js"),
])
def test_lab_page_renders(client, path, script):
    r = client.get(path)
    assert r.status_code == 200
    assert script.encode() in r.data
    assert b"not built yet" not in r.data


def test_chart_library_is_served_locally(client):
    r = client.get("/static/vendor/chart.umd.js")
    assert r.status_code == 200
    assert b"Chart.js" in r.data[:200]
    r.close()
    assert b"cdn" not in client.get("/benchmark").data.lower()
