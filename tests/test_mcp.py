"""MCP server tests: an in-process client calls every tool, resource and prompt; then the real
stdio entry point is spawned as a subprocess, the way Claude Desktop runs it."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, StdioServerParameters

from hearthly.mcp_server import mcp
from hearthly.state import StateStore

from .helpers import REFUNDS_BY_REASON_SQL, sample_spec

EXPECTED_TOOLS = {
    "describe_schema", "run_query", "list_metrics", "get_metric", "detect_anomalies", "create_dashboard",
    "update_dashboard", "add_panel", "remove_panel", "list_dashboards", "get_dashboard",
}


async def _call(c: Client, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    r = await c.call_tool(name, args or {})
    assert not r.is_error, f"{name} failed: {r.content[0].text if r.content else r}"
    text = json.loads(r.content[0].text)
    assert text == r.structured_content
    return r.structured_content


def test_every_tool_resource_and_prompt(state_db: Path) -> None:
    async def scenario() -> None:
        async with Client(mcp, raise_exceptions=True) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert set(tools) == EXPECTED_TOOLS
            for t in tools.values():
                assert t.description and len(t.description) > 60, f"{t.name} needs a real description"
            assert tools["run_query"].annotations.read_only_hint is True
            assert tools["create_dashboard"].annotations.read_only_hint is False

            schema = await _call(c, "describe_schema")
            assert len(schema["tables"]) == 9
            one = await _call(c, "describe_schema", {"table": "agent_runs"})
            assert one["row_count"] > 0 and one["sample_rows"]["rows"]
            q = await _call(c, "run_query", {"sql": "SELECT COUNT(*) AS n FROM orders", "limit": 5})
            assert q["rows"][0][0] > 100_000
            ms = await _call(c, "list_metrics")
            assert any(m["name"] == "agent_cost_per_successful_task" for m in ms["metrics"])
            gm = await _call(c, "get_metric", {"name": "on_time_delivery_pct", "grain": "week", "group_by": "courier"})
            assert gm["columns"] == ["period", "courier", "on_time_delivery_pct"] and gm["sql"]
            an = await _call(c, "detect_anomalies", {"metric": "tickets", "dimension": "category",
                                                     "period": "last_30_days"})
            assert an["anomalies"]

            created = await _call(c, "create_dashboard", {"spec": sample_spec("mcp-dash")})
            assert created["version"] == 1
            upd = await _call(c, "update_dashboard", {"id": "mcp-dash", "patch": {"subtitle": "Updated live"}})
            assert upd["version"] == 2
            added = await _call(c, "add_panel", {"dashboard_id": "mcp-dash", "panel": {
                "id": "reasons-bar", "type": "horizontal_bar", "title": "Refunds by reason",
                "sql": REFUNDS_BY_REASON_SQL, "encoding": {"x": "reason", "y": "requests"},
                "insight": "Reasons ranked."}})
            assert added["version"] == 3
            removed = await _call(c, "remove_panel", {"dashboard_id": "mcp-dash", "panel_id": "reasons-bar"})
            assert removed["version"] == 4
            listed = await _call(c, "list_dashboards")
            assert [d["id"] for d in listed["dashboards"]] == ["mcp-dash"]
            got = await _call(c, "get_dashboard", {"id": "mcp-dash"})
            assert got["spec"]["subtitle"] == "Updated live" and len(got["history"]) == 4

            # errors come back as tool errors Claude can read and fix
            bad = await c.call_tool("run_query", {"sql": "SELECT 1; DROP TABLE orders"})
            assert bad.is_error and "one statement" in bad.content[0].text
            bad = await c.call_tool("create_dashboard", {"spec": {**sample_spec("bad"), "panels": [
                {"id": "p", "type": "line", "title": "t", "sql": "SELECT 1 AS a", "encoding": {"x": "a", "y": "b"}}]}})
            assert bad.is_error and "Result columns: a" in bad.content[0].text

            uris = {str(r.uri) for r in (await c.list_resources()).resources}
            assert uris == {"hearthly://schema", "hearthly://metrics", "hearthly://dashboard_design_guide"}
            for uri in uris:
                res = await c.read_resource(uri)
                assert res.contents[0].text.strip()
            guide = (await c.read_resource("hearthly://dashboard_design_guide")).contents[0].text
            assert "KPI row first" in guide and "At most 8 panels" in guide

            prompts = {p.name for p in (await c.list_prompts()).prompts}
            assert prompts == {"weekly_ops_review", "investigate_metric"}
            p = await c.get_prompt("investigate_metric", {"metric": "refund_rate"})
            assert "refund_rate" in p.messages[0].content.text
            p = await c.get_prompt("weekly_ops_review")
            assert "weekly" in p.messages[0].content.text.lower()

    anyio.run(scenario)
    tools_logged = {r["tool"] for r in StateStore().activity_since(0, limit=500)}
    assert EXPECTED_TOOLS <= tools_logged


def test_stdio_subprocess(state_db: Path, business_db: Path) -> None:
    """Spawn `python -m hearthly.mcp_server` over stdio with the initialize handshake Claude Desktop uses."""
    env = {**os.environ, "HEARTHLY_DB": str(business_db), "HEARTHLY_STATE_DB": str(state_db)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "hearthly.mcp_server"], env=env)

    async def scenario(mode: str) -> None:
        with anyio.fail_after(60):
            await _stdio_checks(mode)

    async def _stdio_checks(mode: str) -> None:
        async with Client(params, mode=mode) as c:  # type: ignore[arg-type]
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == EXPECTED_TOOLS
            r = await c.call_tool("run_query", {"sql": "SELECT COUNT(*) FROM products"})
            assert not r.is_error and json.loads(r.content[0].text)["rows"] == [[40]]

    for mode in ("legacy", "auto"):
        anyio.run(scenario, mode)


def test_no_story_leaks_in_server_text(business_db: Path) -> None:
    """Nothing the server exposes may hint at the planted stories."""
    async def collect() -> str:
        async with Client(mcp) as c:
            parts = [t.model_dump_json() for t in (await c.list_tools()).tools]
            for uri in ("hearthly://metrics", "hearthly://dashboard_design_guide"):
                parts.append((await c.read_resource(uri)).contents[0].text)
            parts += [p.model_dump_json() for p in (await c.list_prompts()).prompts]
            for name, args in (("weekly_ops_review", {}), ("investigate_metric", {"metric": "x"})):
                parts.append((await c.get_prompt(name, args)).messages[0].content.text)
            parts.append(mcp.instructions or "")
            return "\n".join(parts).lower()

    text = anyio.run(collect)
    from hearthly.schema_docs import COLUMN_NOTES, CONVENTIONS, TABLE_NOTES
    text += json.dumps([COLUMN_NOTES, CONVENTIONS, TABLE_NOTES]).lower()
    for leak in ("kt-b17", "b17", "kettle", "airbrew", "swiftship", "northeast", "flash", "v4", "prompt drift",
                 "hx-lite", "boundary", "defective", "late deliver", "bad batch"):
        assert leak not in text, f"server text leaks '{leak}'"


def test_public_docs_do_not_reveal_stories() -> None:
    """README is audience-safe; only docs/DEMO_SECRETS.md (and DEMO_SCRIPT, qualitatively) may know."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "README.md").read_text(encoding="utf-8").lower()
    for leak in ("kt-b17", "kettle", "airbrew", "swiftship", "northeast", "weekend flash", "prompt_version changes",
                 "v3 to v4", "boundary"):
        assert leak not in text, f"README leaks '{leak}'"
