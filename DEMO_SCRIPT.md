# Demo script: 10 minutes

From static reports to an AI agent that builds the dashboard live. Presenter notes; the exact
dates and numbers of what is planted in the data are in `docs/DEMO_SECRETS.md` (keep that off
the projector).

## Before class (T-30 min)

1. `./run.sh seed` **on the day** so "yesterday" is really yesterday, then open
   `docs/DEMO_SECRETS.md` on your laptop screen only.
2. `./run.sh reset` to clear rehearsal dashboards and the activity feed.
3. `./run.sh web` and open three tabs: `/`, `/static`, `/dynamic`. Browser zoom 100% at 1920×1080
   (125% if the room is large). Choose light or dark (`T`). Projectors usually favour light.
4. Claude Desktop: new chat, Hearthly connector enabled. Warm it up with
   *"Use the hearthly tools to tell me how many orders we had yesterday."* Approve the tools
   ("Allow always") so the live run isn't interrupted by permission prompts. Then `./run.sh reset` again.
5. Arrange the screen: Claude Desktop on the left third, `/dynamic` on the right two-thirds, or
   two displays. Press `P` in `/dynamic` for **Present mode** (bigger type, no sidebar).
6. Have the fallback ready in a terminal: `./run.sh demo` (builds a dashboard panel by panel
   through the same tool code; the feed and the animations look identical).

Timing note: Claude typically spends 30–90 s investigating before it creates a dashboard. Narrate
the feed while it works: that *is* the point of the demo.

---

## 0:00 – 1:30 · The evolution (`/`)

- Walk left to right: **static reports → interactive BI → natural-language query → agentic
  dashboards via MCP**. For each, point at *who builds it* and *time to a new question*
  (illustrative figures: weeks → days → minutes → about a minute).
- Stage 4's limits are the talking points for the end: guardrails, a semantic layer,
  verification, data quality.
- The wiring strip at the bottom: Claude Desktop ⇄ MCP server ⇄ read-only SQLite; the web app
  only renders specs and re-runs their SQL.

## 1:30 – 2:30 · The classic dashboard (`/static`)

- Six fixed panels, one date dropdown. Change the range: it works, and that's all it does.
- Ask the room: *"Refunds feel high this quarter. Why?"* Nothing here can answer that: no
  refunds, delivery, support or agent data, no drill-down.
- Scroll to **Request a new report** → "Average turnaround: **2 weeks**". Click submit for the laugh.

## 2:30 – 10:00 · The live workspace (`/dynamic`)

Empty state: "Waiting for Claude…", suggested prompts on the left (copy buttons), empty feed
on the right. Paste each prompt into Claude Desktop.

### Prompt 1 (≈ 75 s)
> What's going on with refunds in the last 90 days?

**Audience sees:** a burst of `describe_schema`, `get_metric`, `run_query` and `detect_anomalies`
calls in the feed, each with its SQL, row count and milliseconds. Claude answers in chat.
**Expected finding:** refund volume up, with one product and one manufacturing batch standing out
far above baseline, and a dominant reason (DEMO_SECRETS §1). Claude may also point out that
refund *rate* by order cohort reads low for recent weeks: a good moment to talk about metric
definitions.
**Say:** "Nobody wrote a report for this. It went from question to batch-level root cause by
writing SQL against governed definitions, and every query is visible on the right."

### Prompt 2 (≈ 90 s)
> Build me a dashboard for the COO covering revenue, refunds and delivery.

**Audience sees:** `create_dashboard` appears in the feed and the workspace **switches to the new
dashboard**; panels animate in: KPI row first (value, change vs previous week, sparkline), then
trends. Hover a panel → **View SQL** shows the exact query; the header says "Live SQL · refreshes
every 30s".
**Say:** "This isn't a picture of data. Each panel is a SQL query that re-runs every 30 seconds.
It's as live as the database."
If Claude's first spec has a mistake, the feed shows `create_dashboard` **error** with the reason,
then a corrected retry. Point it out: the tools return actionable errors and the agent fixes itself.

### Prompt 3 (≈ 75 s)
> Why did on-time delivery drop? Show me where.

**Audience sees:** `detect_anomalies` on `on_time_delivery_pct` by courier/region, then drill-down
queries combining courier × destination; usually `add_panel` / `update_dashboard` adds a heatmap
or courier trend to the COO dashboard, which flashes as it changes.
**Expected finding:** one courier on one set of states, starting about 40 days ago, with a matching
rise in "where is my order" tickets (DEMO_SECRETS §2).

### Prompt 4 (≈ 75 s)
> Compare the Weekend Flash Sale with normal weekends, including margin.

**Audience sees:** campaign and margin queries (`gross_margin_pct` from metrics.yaml), maybe a new
panel or small dashboard.
**Expected finding:** a clear revenue lift with a real margin cost, and customers who rarely come
back (DEMO_SECRETS §3). **Say:** "A static dashboard shows the revenue spike and calls it a win.
The trade-off only appears when you can ask the next question."

### Prompt 5 (≈ 45 s)
> Add a panel for repeat-purchase rate by campaign to the COO dashboard.

**Audience sees:** `add_panel` in the feed and a single new panel sliding into the existing
dashboard; version badge increments. Uses the `repeat_purchase_rate` metric.
**Say:** "That was the two-week request from the classic dashboard."

### Prompt 6 (≈ 90 s)
> Build a dashboard for the head of support on our RefundDesk AI agent: accuracy, latency, cost
> per successful task, and anything that changed recently.

**Audience sees:** a second dashboard appears in the list and the workspace follows it: KPI row
(accuracy, latency, cost per successful task, auto-resolution) and trends split by
`prompt_version` / `model`.
**Expected finding:** a prompt change three weeks ago that hurt accuracy mainly on edge cases near a
policy boundary, and a model swap ten days ago that cut cost but raised latency (DEMO_SECRETS §5).
**Say:** "AI agents in production need dashboards too. Their traces are just another table."

## Close (≈ 30 s)

Back to stage 4's limits on `/`: read-only access, a semantic layer (metrics.yaml), an audit log
(the feed), and human judgement on the conclusions. Optional: mention the data-quality traps
Claude may have flagged (DEMO_SECRETS §6).

---

## If something goes wrong

| Problem | Do this |
|---|---|
| Claude Desktop can't see the tools | Switch to the fallback: `./run.sh demo` (COO) and `./run.sh demo --all` (adds the agent dashboard). Narrate the feed the same way. |
| Claude is slow or rambling | Say "while it thinks…" and walk through the feed. Or follow up with: "Go ahead and create the dashboard now." |
| A panel shows an error | Click **View SQL**; ask Claude "Fix the failing panel on the COO dashboard." |
| Too many old dashboards | `./run.sh reset`; the dashboard list empties by itself, reload the page to clear the feed. |
| Status says "Live (polling)" | Fine: updates arrive every 2.5 s instead of instantly. |
