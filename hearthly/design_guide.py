"""The dashboard design guide served to Claude as an MCP resource."""

from __future__ import annotations

from .spec import DEFAULT_SIZE, ENCODING_HELP


def design_guide() -> str:
    encodings = "\n".join(f"| `{t}` | {DEFAULT_SIZE[t][0]}×{DEFAULT_SIZE[t][1]} | {help_} |"
                          for t, help_ in ENCODING_HELP.items())
    return f"""# Hearthly dashboard design guide

Dashboards appear live in the Hearthly workspace (http://127.0.0.1:8000/dynamic) the moment you
create or update them. Every panel stores SQL, not data: its SQL re-runs on every refresh (30 s).

## Principles
1. **One story per dashboard.** The title names the audience or question ("COO weekly: revenue,
   refunds, delivery"). The subtitle states the period and any definitions.
2. **KPI row first.** Start with 3–4 `kpi` panels (w=3, h=2) on row 0, then the charts that explain them.
3. **At most 8 panels.** Cut anything that does not support the story.
4. **One-line insight per panel.** Say what to notice, with a number, e.g. "App orders overtook web
   orders in the last four weeks (52% vs 41%)." Only claim what the panel's data shows.
5. **Use the metric definitions.** Call `get_metric` and reuse the `sql` it returns (or its formula),
   so numbers match the official definitions in metrics.yaml. Say which metric a KPI uses.
6. **Choose the chart by data shape:**
   - trend over time → `line` (or `area` for volumes); many series → keep ≤ 5 lines
   - compare categories → `bar`; long labels or ranked lists → `horizontal_bar`
   - composition over time → `stacked_bar`; share of a whole with ≤ 6 parts → `donut`
   - relationship between two measures → `scatter`
   - two categorical dimensions (e.g. weekday × hour, channel × category) → `heatmap`
   - exact values / drill-down lists → `table`
   - a single headline number → `kpi`

## SQL that stays live
- Anchor dates to the data, not to a fixed day: `WHERE order_date > date((SELECT MAX(order_date) FROM orders), '-90 day')`.
- Aggregate in SQL (GROUP BY). A panel may return at most 5,000 rows; aim for < 200.
- Alias columns with readable names; they become axis labels, legends and table headers.
- Return ratios as fractions 0–1 and set `encoding.format = "percent"`.
- Order time series ascending (ORDER BY period).
- KPI panels: return one row per period ordered ascending (columns e.g. `week`, `value`) and set
  `encoding.x = "week"`, `encoding.value = "value"`. The last row is the headline, the previous row
  is the comparison, all rows draw the sparkline. A single-row result also works (no sparkline).

## Encodings by panel type
| type | default w×h | encoding |
|---|---|---|
{encodings}

Formats: `number`, `decimal`, `currency` (₹, compact), `usd`, `percent` (0–1 fractions), `minutes`, `ms`.

## Layout
12-column grid; one row unit ≈ 80 px. KPI w=3 h=2; standard chart w=6 h=4; wide trend w=12 h=4.
You may omit `layout`: panels are auto-placed left to right in panel order.

## Working loop
- Explore with `describe_schema` and `run_query` first; confirm a pattern before charting it.
- `create_dashboard` validates everything: each SQL runs, row limits, encoding columns exist and are
  numeric where needed. If it returns errors, fix exactly those and call it again.
- To change an existing dashboard use `update_dashboard` or `add_panel` / `remove_panel` (the
  audience sees it change in place). Do not recreate it under a new id.
- Tell the user the dashboard URL when you are done.
"""
