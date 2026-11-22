"""Hearthly Live web app: the evolution page, the classic dashboard and the live AI workspace.

    uvicorn hearthly.web.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import config, sqlguard
from ..state import StateStore
from ..validate import run_panel
from . import static_dashboard

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
SSE_POLL_SECONDS = 0.4
SSE_HEARTBEAT_SECONDS = 15

app = FastAPI(title="Hearthly Live", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static-assets", StaticFiles(directory=HERE / "static"), name="assets")


def _store() -> StateStore:
    return StateStore()


def _data_end() -> date:
    res = sqlguard.run_select("SELECT MAX(order_date) FROM orders", limit=1)
    return date.fromisoformat(res.rows[0][0])


# --------------------------------------------------------------------------- pages


def _page(name: str) -> FileResponse:
    return FileResponse(TEMPLATES / name, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def evolution_page() -> FileResponse:
    return _page("index.html")


@app.get("/static", include_in_schema=False)
def static_page() -> FileResponse:
    return _page("static.html")


@app.get("/dynamic", include_in_schema=False)
def dynamic_page() -> FileResponse:
    return _page("dynamic.html")


# --------------------------------------------------------------------------- API


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    first = sqlguard.run_select("SELECT MIN(order_date) FROM orders", limit=1).rows[0][0]
    return {"data_start": first, "data_end": _data_end().isoformat(), "mcp_http": f"http://{config.MCP_HTTP_HOST}:"
            f"{config.MCP_HTTP_PORT}/mcp"}


@app.get("/api/static")
def static_dashboard_data(range: str = "90") -> dict[str, Any]:  # noqa: A002 - query param name
    if range not in static_dashboard.RANGES:
        raise HTTPException(400, f"range must be one of {list(static_dashboard.RANGES)}")
    panels = static_dashboard.panels_for(range, _data_end())
    return {"panels": [p.model_dump() for p in panels], "layout": static_dashboard.LAYOUT,
            "data": {p.id: run_panel(p).as_dict() for p in panels}}


@app.get("/api/dashboards")
def dashboards() -> dict[str, Any]:
    return {"dashboards": _store().list_dashboards()}


@app.get("/api/dashboards/{dashboard_id}")
def dashboard(dashboard_id: str) -> dict[str, Any]:
    spec = _store().get_dashboard(dashboard_id)
    if spec is None:
        raise HTTPException(404, "dashboard not found")
    return spec.model_dump()


@app.get("/api/dashboards/{dashboard_id}/data")
def dashboard_data(dashboard_id: str) -> dict[str, Any]:
    """Re-run every panel's SQL (read-only) and return fresh results."""
    spec = _store().get_dashboard(dashboard_id)
    if spec is None:
        raise HTTPException(404, "dashboard not found")
    return {"id": spec.id, "version": spec.version, "data": {p.id: run_panel(p).as_dict() for p in spec.panels}}


@app.get("/api/dashboards/{dashboard_id}/panels/{panel_id}/data")
def panel_data(dashboard_id: str, panel_id: str) -> dict[str, Any]:
    spec = _store().get_dashboard(dashboard_id)
    panel = next((p for p in spec.panels if p.id == panel_id), None) if spec else None
    if panel is None:
        raise HTTPException(404, "panel not found")
    return run_panel(panel).as_dict()


@app.get("/api/dashboards/{dashboard_id}/history")
def dashboard_history(dashboard_id: str) -> dict[str, Any]:
    return {"history": _store().history(dashboard_id)}


@app.get("/api/activity")
def activity(after: int = 0, limit: int = 60) -> dict[str, Any]:
    return {"activity": _store().activity_since(after, max(1, min(limit, 200)))}


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: `activity` when MCP calls are logged, `dashboards` when a dashboard changes."""

    async def stream() -> AsyncIterator[str]:
        last_act, last_sig = await run_in_threadpool(lambda: _store().change_marker())
        yield f"event: hello\ndata: {json.dumps({'activity_id': last_act})}\n\n"
        idle = 0.0
        while not await request.is_disconnected():
            await asyncio.sleep(SSE_POLL_SECONDS)
            act, sig = await run_in_threadpool(lambda: _store().change_marker())
            if act != last_act:
                yield f"event: activity\ndata: {json.dumps({'activity_id': act})}\n\n"
                last_act, idle = act, 0.0
            if sig != last_sig:
                yield f"event: dashboards\ndata: {json.dumps({'signature': sig})}\n\n"
                last_sig, idle = sig, 0.0
            idle += SSE_POLL_SECONDS
            if idle >= SSE_HEARTBEAT_SECONDS:
                yield ": keep-alive\n\n"
                idle = 0.0

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
