# Hearthly Live — build plan

## Context
A live class on AI for enterprise analytics needs a fully local, projector-ready demo of how
dashboards moved from static to AI-built. We build a fictional Indian D2C brand ("Hearthly")
with a deterministic SQLite DB, a FastAPI web app with a deliberately limited static dashboard
and a live `/dynamic` workspace, plus an MCP server that Claude Desktop / Claude Code use to
explore the data with SQL and create or edit dashboards that appear live in the browser.
Greenfield: new folder `/Users/swapravo/Documents/projects/hearthly-live/` (new git repo).

## Verified facts (read from official docs this session)
- PyPI `mcp` is 2.3.0. FastMCP was renamed `MCPServer` in v2: `from mcp.server import MCPServer`,
  `from mcp.server.mcpserver import Context`. **User chose v2 MCPServer** (README notes it is FastMCP's successor).
- Tools: `@mcp.tool()` (docstring = description, `title=`, `annotations=ToolAnnotations(read_only_hint=...)`),
  typed/Pydantic params, structured output from return annotation; raise `ToolError` for model-visible errors.
- Resources `@mcp.resource("uri", mime_type=...)`; prompts `@mcp.prompt()` returning str or `list[Message]`.
- `mcp.run()` = stdio; `mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)`, path `/mcp`.
  Transport options go to `run()`, not the constructor.
- In-process tests: `async with Client(mcp, raise_exceptions=True) as c: await c.call_tool(...)`
  (exact list_tools/read_resource/get_prompt signatures to be confirmed from the installed package source).
- stdio: never print to stdout; log via `logging` to stderr.
- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`,
  `{"mcpServers": {"hearthly": {"command": "<abs>", "args": [...]}}}`, absolute paths, full quit/restart,
  logs `~/Library/Logs/Claude/mcp*.log`.
- Claude Code: `claude mcp add --transport stdio hearthly -- <cmd> <args>` (`--scope local|project|user`);
  HTTP: `claude mcp add --transport http hearthly http://127.0.0.1:8765/mcp`.
- Pinned versions: mcp 2.3.0, fastapi 0.165.0, uvicorn 0.54.0, pydantic 2.14.4, pyyaml 6.0.4,
  pytest 9.2.0, anyio 4.16.0, httpx 0.28.1, playwright 1.65.2. Python 3.13 via uv (`requires-python >=3.11`).
  Chart.js 4.x UMD vendored into `static/vendor/` once at build time (committed).

## Architecture
```
hearthly-live/
  pyproject.toml, uv.lock, .python-version, run.sh, metrics.yaml
  PLAN.md, README.md, DEMO_SCRIPT.md, docs/DEMO_SECRETS.md, docs/screenshots/
  hearthly/
    config.py        paths (data/hearthly.db, data/state.db), env overrides for tests
    seed/            __main__ (CLI --reset [--as-of DATE]), schema.py, generator.py, secrets.py
    sqlguard.py      read-only connection, authorizer, progress-handler timeout, row cap
    metrics.py       load metrics.yaml → compile metric SQL by grain/date/group_by
    anomalies.py     ratio-to-baseline + z-score ranking
    spec.py          Pydantic DashboardSpec/Panel/Layout/Encoding + auto-layout
    state.py         state.db (WAL): dashboards, dashboard_versions, activity_log
    validate.py      run each panel SQL, ≤5000 rows, encoding columns exist → actionable errors
    tools.py         plain-Python tool implementations + activity logging (shared by MCP, demo script, tests)
    mcp_server.py    MCPServer wiring, resources, prompts; `--http` flag → streamable HTTP 127.0.0.1:8765
    print_config.py  prints Claude Desktop JSON + `claude mcp add` with absolute paths
    web/app.py       FastAPI pages + JSON API + SSE; static/ (css, js, vendor/chart.umd.min.js), templates/
  scripts/demo_dashboard.py, scripts/screenshots.py
  tests/
```
- MCP server and web app are separate processes; both open `state.db` in WAL mode. The web
  app's SSE endpoint polls `max(activity_log.id)` / `max(dashboards.updated_at)` every ~400 ms
  and pushes `activity` and `dashboard` events; frontend falls back to polling if SSE drops.
- Panels store SQL only; `/api/dashboards/{id}/data` re-runs every panel's SQL through sqlguard
  on each render; frontend re-fetches every `refresh_seconds` (default 30).

## Data model & planted stories
- Tables exactly as briefed, FKs + indexes (order_date, customer_id, order_id, product_id,
  batch_code, courier/dispatched_at, run_at, prompt_version).
- Generation (pure stdlib `random.Random(42)`): daily weight curve (trend, weekday/weekend
  rhythm, Oct–Nov festive + January sale uplift). ~40k customers each get a signup date and a
  repeat count; order dates sampled from the weight curve after signup (bisect on cumulative
  weights) → ~120k orders, 40 products in 6 categories. Segment derived from order history.
- End date = yesterday (`--as-of` override for reproducibility; same date ⇒ byte-identical DB).
- Stories (numbers tuned, then measured and written to DEMO_SECRETS.md by `seed/secrets.py`):
  1. AirBrew Electric Kettle batch KT-B17, dispatched days −60…−46: refund rate ≈3× baseline, mostly "defective".
  2. SwiftShip → 8 Northeast states from day −40: ~35% late vs ~6%, plus `where_is_my_order` ticket spike.
  3. "Weekend Flash Sale" campaign (Sat/Sun only, a ~3-month window outside festive season):
     +~40% weekend revenue, −~8 pts gross margin (deeper discounts), deal-seeker customers with low repeat.
  4. Festive Oct–Nov and January-sale uplift; weekday/weekend rhythm.
  5. RefundDesk: prompt v3→v4 at day −21, audit_correct ~93%→~81%, the drop concentrated in
     boundary cases (requests 27–33 days after delivery, around the 30-day return window);
     model swap at day −10 (neutral fictional model names) → lower cost_usd, higher latency_ms.
  6. ~1% shipments with NULL destination_state; a few refunds requested 90+ days after order.
- Nothing about the stories appears in tool output, descriptions, schema text or resources.

## Semantic layer (`metrics.yaml`)
gross_revenue, net_revenue, aov, orders, refund_rate (by orders) + refund_rate_by_amount,
on_time_delivery_pct, avg_first_response_minutes, csat, agent_accuracy,
agent_auto_resolution_rate, agent_cost_per_successful_task. Each: description, formula
(SQL expression), base FROM/joins, time column, unit/format, allowed dimensions → SQL exprs.
`get_metric` returns rows **and the compiled SQL**, so Claude can reuse it verbatim in panels.

## MCP tools (excellent descriptions; read-only annotations where true)
describe_schema(table?), run_query(sql, limit=1000), list_metrics(), get_metric(name, grain,
start, end, group_by?), detect_anomalies(metric, dimension, period), create_dashboard(spec),
update_dashboard(id, patch), add_panel, remove_panel, list_dashboards, get_dashboard.
Resources: `hearthly://schema`, `hearthly://metrics`, `hearthly://dashboard_design_guide`.
Prompts: weekly_ops_review, investigate_metric(metric).
Spec errors raise `ToolError` with a per-panel list ("panel 'x': column 'rev' not in result
columns [day, revenue]; set encoding.y to one of these").

## Safety (sqlguard)
`file:...?mode=ro` URI + `PRAGMA query_only=ON` (set before the authorizer is installed);
authorizer allows only SQLITE_SELECT, SQLITE_READ, SQLITE_FUNCTION (deny load_extension etc.),
SQLITE_RECURSIVE; denies ATTACH/PRAGMA/writes/DDL. Pre-check: strip strings/comments with a
small tokenizer, reject >1 statement and non-SELECT/WITH lead keyword. Progress handler aborts
after 5 s. fetchmany(limit+1) → `truncated`. Data values returned as JSON data; UI renders with
textContent only (never innerHTML of data).

## Web app
`/` evolution timeline (4 stages, "illustrative" time-to-answer labels, CTA buttons);
`/static` 6 fixed panels with hard-coded SQL + date-range dropdown + fake "Request a new report"
form ("Average turnaround: 2 weeks"); `/dynamic` 3-column workspace (dashboard list / suggested
prompts when empty; 12-col grid renderer; "What Claude just did" feed) with Present mode and
light/dark theme. Panel types kpi (value + Δ vs previous period + sparkline), line, area, bar,
stacked_bar, horizontal_bar, donut, table, scatter, heatmap (CSS grid). Each panel: title,
insight, View SQL toggle, refresh. New panels animate in. System font stack, restrained palette
(dataviz skill guidance for chart colours), tuned for 1920×1080.

## Phases (tests + checks + `git commit` after each)
0. Scaffold: git init, uv project with pinned deps, run.sh, PLAN.md, vendored Chart.js.
1. Schema + seed + secrets doc; tests: determinism, all six stories via SQL assertions.
2. sqlguard + metrics + anomalies; guard tests (INSERT/UPDATE/DROP/ATTACH/PRAGMA/multi-stmt/comment tricks, timeout).
3. spec + state + validate + tools + MCP server + print_config; spec validation tests, in-process
   MCP client test calling every tool/resource/prompt, plus a stdio subprocess smoke test.
4. Web app (pages, API, SSE, renderer, themes, present mode).
5. demo_dashboard.py + Playwright screenshots of `/`, `/static`, `/dynamic`; inspect images, fix visual issues, re-shoot.
6. README (quick start, print_config output, claude mcp add, troubleshooting, assumptions),
   DEMO_SCRIPT.md (6 prompts + expected audience view), fresh-clone verification of README steps.

## Risks
- v2 SDK details beyond the docs → read installed `mcp` source before coding; stdio subprocess test.
- Claude Desktop protocol compatibility with mcp 2.3 → confirm supported protocol versions in source.
- Seed speed (pure Python, ~250k rows) → executemany, single transaction; target <30 s.
- Story signal vs noise → tune and assert in tests; DEMO_SECRETS numbers are measured, not hoped.
- I will not edit the user's real Claude Desktop config; I verify via stdio client + `claude mcp` CLI only if harmless (local scope, then remove).

## Verification
`./run.sh setup && ./run.sh seed && ./run.sh test` (pytest incl. Playwright); `./run.sh web`
then `scripts/demo_dashboard.py` and watch `/dynamic` update live; `python -m hearthly.mcp_server`
over stdio via an MCP client subprocess calling every tool; `--http` mode hit with the client;
review docs/screenshots/*.png by eye; re-run README quick start in a fresh clone.
