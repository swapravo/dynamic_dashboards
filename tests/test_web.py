"""Web app API: pages, static dashboard, live dashboard data, activity and SSE."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hearthly import tools
from hearthly.web.app import app

from .helpers import sample_spec

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture()
def client(state_db: Path) -> TestClient:
    return TestClient(app)


def test_pages_render(client: TestClient) -> None:
    for path, marker in (("/", "The evolution of dashboards"), ("/static", "Average turnaround"),
                         ("/dynamic", "What Claude just did")):
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text
    assert client.get("/static-assets/vendor/chart.umd.min.js").status_code == 200


def test_no_external_urls_in_pages(client: TestClient) -> None:
    for path in ("/", "/static", "/dynamic"):
        html = client.get(path).text
        assert "https://" not in html and "http://" not in html.replace("http://www.w3.org", "")


@pytest.mark.parametrize("rng", ["30", "90", "180", "365"])
def test_static_dashboard(client: TestClient, rng: str) -> None:
    r = client.get(f"/api/static?range={rng}").json()
    assert len(r["panels"]) == 6
    assert all(d["error"] is None and d["row_count"] > 0 for d in r["data"].values())
    assert client.get("/api/static?range=7").status_code == 400


def test_dashboard_endpoints(client: TestClient) -> None:
    assert client.get("/api/dashboards").json() == {"dashboards": []}
    tools.create_dashboard(sample_spec("web-dash"))
    listed = client.get("/api/dashboards").json()["dashboards"]
    assert listed[0]["id"] == "web-dash"
    spec = client.get("/api/dashboards/web-dash").json()
    assert spec["version"] == 1 and len(spec["layout"]) == 3
    data = client.get("/api/dashboards/web-dash/data").json()["data"]
    assert set(data) == {"rev-kpi", "rev-trend", "refund-reasons"}
    assert all(d["rows"] and d["error"] is None for d in data.values())
    one = client.get("/api/dashboards/web-dash/panels/rev-trend/data").json()
    assert one["columns"] == ["week", "revenue"]
    assert client.get("/api/dashboards/nope").status_code == 404
    assert client.get("/api/dashboards/web-dash/panels/nope/data").status_code == 404
    assert client.get("/api/dashboards/web-dash/history").json()["history"][0]["version"] == 1


def test_activity_feed(client: TestClient) -> None:
    tools.run_query("SELECT 1 AS one")
    tools.run_query("SELECT 2 AS two")
    acts = client.get("/api/activity").json()["activity"]
    assert [a["tool"] for a in acts] == ["run_query", "run_query"]
    after = client.get(f"/api/activity?after={acts[0]['id']}").json()["activity"]
    assert [a["sql"] for a in after] == ["SELECT 2 AS two"]


def test_sse_pushes_activity_and_dashboard_events(state_db: Path) -> None:
    import screenshots  # type: ignore[import-not-found]

    with screenshots.web_server(dict(os.environ)) as url:
        events: list[str] = []
        with httpx.stream("GET", f"{url}/api/events", timeout=10) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = r.iter_lines()
            for line in lines:
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                    break
            tools.create_dashboard(sample_spec("sse-dash"))
            deadline = time.time() + 8
            for line in lines:
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                if {"activity", "dashboards"} <= set(events) or time.time() > deadline:
                    break
    assert events[0] == "hello"
    assert {"activity", "dashboards"} <= set(events)


def test_panel_errors_are_reported_not_raised(client: TestClient) -> None:
    """If data changes so a stored panel's SQL fails, the API returns the error for that panel only."""
    from hearthly.state import StateStore
    spec = tools.create_dashboard(sample_spec("err-dash"))
    stored = StateStore().get_dashboard("err-dash")
    broken = stored.model_copy(update={"panels": [stored.panels[0].model_copy(update={"sql": "SELECT nope FROM orders"}),
                                                   *stored.panels[1:]]})
    StateStore().save_dashboard(broken, "test")
    data = client.get("/api/dashboards/err-dash/data").json()["data"]
    assert "describe_schema" in data["rev-kpi"]["error"]
    assert data["rev-trend"]["error"] is None
    assert spec["id"] == "err-dash"
    json.dumps(data)
