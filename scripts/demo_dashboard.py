"""Fallback for class: build sample dashboards through the same tool code Claude uses over MCP.

    uv run python scripts/demo_dashboard.py            # COO overview, panel by panel (watch /dynamic)
    uv run python scripts/demo_dashboard.py --all      # also the RefundDesk agent dashboard
    uv run python scripts/demo_dashboard.py --fast     # no pauses

Every step is logged to the activity feed exactly like an MCP call.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthly import tools  # noqa: E402

ANCHOR = "(SELECT MAX(order_date) FROM orders)"


def kpi_from_metric(metric: str, panel_id: str, title: str, fmt: str, insight: str) -> dict:
    sql = tools.get_metric(metric, grain="week", rolling_days=84)["sql"]
    return {"id": panel_id, "type": "kpi", "title": title, "sql": sql,
            "encoding": {"x": "period", "value": metric, "format": fmt}, "insight": insight}


def coo_dashboard(pause: float) -> str:
    step = lambda: time.sleep(pause)  # noqa: E731
    tools.describe_schema()
    step()
    tools.list_metrics()
    step()
    panels = [
        kpi_from_metric("net_revenue", "net-revenue", "Net revenue (weekly)", "currency",
                        "Latest full week vs the week before; 12-week sparkline."),
        {"id": "refund-requests", "type": "kpi", "title": "Refund requests per 100 orders",
         "sql": f"""WITH w AS (
  SELECT date(requested_at, '-' || ((CAST(strftime('%w', requested_at) AS INTEGER) + 6) % 7) || ' days') AS week,
         COUNT(*) AS requests
  FROM refunds GROUP BY week),
o AS (
  SELECT date(order_date, '-' || ((CAST(strftime('%w', order_date) AS INTEGER) + 6) % 7) || ' days') AS week,
         COUNT(*) AS orders
  FROM orders WHERE status != 'cancelled' GROUP BY week)
SELECT o.week, 100.0 * COALESCE(w.requests, 0) / o.orders AS per_100_orders
FROM o LEFT JOIN w USING (week)
WHERE o.week >= date({ANCHOR}, '-84 day')
  AND o.week < date({ANCHOR}, '+1 day', '-' || ((CAST(strftime('%w', date({ANCHOR}, '+1 day')) AS INTEGER) + 6) % 7) || ' days')
ORDER BY o.week""",
         "encoding": {"x": "week", "value": "per_100_orders", "format": "decimal"},
         "insight": "Requests raised in the week per 100 orders placed that week."},
        kpi_from_metric("on_time_delivery_pct", "on-time", "On-time delivery", "percent",
                        "Delivered on or before the promised date, by dispatch week."),
        kpi_from_metric("csat", "csat", "CSAT", "decimal", "Average 1–5 rating on support tickets."),
    ]
    step()
    revenue = tools.get_metric("gross_revenue", grain="week", rolling_days=182)["sql"]
    panels.append({"id": "revenue-trend", "type": "area", "title": "Gross revenue by week", "sql": revenue,
                   "encoding": {"x": "period", "y": "gross_revenue", "format": "currency"},
                   "insight": "Six months of weekly revenue; watch the festive-season lift."})
    panels.append({"id": "refunds-by-category", "type": "horizontal_bar", "title": "Refund rate by category (90 days)",
                   "sql": "SELECT * FROM (\n" + tools.get_metric("refund_rate_by_amount", grain="total",
                                                                 group_by="category")["sql"]
                          + "\n) ORDER BY refund_rate_by_amount DESC", "encoding": {"x": "category", "y": "refund_rate_by_amount", "format": "percent"},
                   "insight": "Refunded amount as a share of revenue, by product category."})
    step()
    ontime = tools.get_metric("on_time_delivery_pct", grain="week", group_by="courier", rolling_days=120)["sql"]
    panels.append({"id": "on-time-by-courier", "type": "line", "title": "On-time delivery by courier", "sql": ontime,
                   "encoding": {"x": "period", "y": "on_time_delivery_pct", "series": "courier", "format": "percent"},
                   "insight": "Weekly on-time rate for each courier partner."})
    panels.append({"id": "late-heatmap", "type": "heatmap", "title": "Late deliveries by region and courier (30 days)",
                   "sql": f"""SELECT c.region AS region, s.courier AS courier,
       AVG(CASE WHEN date(s.delivered_at) > s.promised_date THEN 1.0 ELSE 0.0 END) AS late_rate
FROM shipments s JOIN orders o ON o.id = s.order_id JOIN customers c ON c.id = o.customer_id
WHERE s.delivered_at IS NOT NULL AND date(s.dispatched_at) > date({ANCHOR}, '-30 day')
GROUP BY region, courier ORDER BY region, courier""",
                   "encoding": {"x": "courier", "y": "region", "value": "late_rate", "format": "percent"},
                   "insight": "Darker cells = more late deliveries; compare across couriers."})
    tools.run_query(panels[-1]["sql"])
    step()
    # create with the first few panels, then add the rest one by one so the audience sees them arrive
    first, rest = panels[:5], panels[5:]
    out = tools.create_dashboard({"id": "coo-overview", "title": "COO overview: revenue, refunds & delivery",
                                  "subtitle": "Rolling windows anchored to the latest data · metrics from metrics.yaml",
                                  "panels": first}, replace=True)
    layout = {"refunds-by-category": (0, 6, 5, 4), "on-time-by-courier": (5, 6, 7, 4), "late-heatmap": (0, 10, 12, 4)}
    for p in rest:
        step()
        x, y, w, hgt = layout[p["id"]]
        out = tools.add_panel("coo-overview", p, {"x": x, "y": y, "w": w, "h": hgt})
    step()
    tools.update_dashboard("coo-overview", {"layout": [{"panel_id": "revenue-trend", "x": 0, "y": 2, "w": 12, "h": 4}]})
    return out["url"]


def agent_dashboard(pause: float) -> str:
    time.sleep(pause)
    acc = tools.get_metric("agent_accuracy", grain="week", group_by="prompt_version", rolling_days=120)["sql"]
    panels = [
        kpi_from_metric("agent_accuracy", "accuracy", "Audit accuracy", "percent", "QA-audited decisions judged correct."),
        kpi_from_metric("agent_avg_latency_ms", "latency", "Avg latency", "ms", "End-to-end run time."),
        kpi_from_metric("agent_cost_per_successful_task", "cost-success", "Cost per successful task", "usd",
                        "Total cost / correct, non-escalated runs."),
        kpi_from_metric("agent_auto_resolution_rate", "auto-res", "Auto-resolution", "percent",
                        "Runs completed without a human."),
        {"id": "accuracy-weekly", "type": "line", "title": "Weekly accuracy by prompt version", "sql": acc,
         "encoding": {"x": "period", "y": "agent_accuracy", "series": "prompt_version", "format": "percent"},
         "insight": "Each line is a system-prompt version."},
        {"id": "cost-latency", "type": "scatter", "title": "Cost vs latency per day and model",
         "sql": f"""SELECT date(run_at) AS day, model, AVG(cost_usd) AS avg_cost_usd, AVG(latency_ms) AS avg_latency_ms
FROM agent_runs WHERE date(run_at) > date({ANCHOR}, '-45 day') GROUP BY day, model""",
         "encoding": {"x": "avg_latency_ms", "y": "avg_cost_usd", "series": "model", "label": "day", "format": "usd"},
         "insight": "Each dot is one day of runs, coloured by model."},
        {"id": "decisions", "type": "stacked_bar", "title": "Decisions per week",
         "sql": f"""SELECT date(run_at, '-' || ((CAST(strftime('%w', run_at) AS INTEGER) + 6) % 7) || ' days') AS week,
       decision, COUNT(*) AS runs
FROM agent_runs WHERE date(run_at) >= date({ANCHOR}, '-83 day', '-' || ((CAST(strftime('%w', date({ANCHOR}, '-83 day')) AS INTEGER) + 6) % 7) || ' days', '+7 day')
  AND date(run_at) < date({ANCHOR}, '+1 day', '-' || ((CAST(strftime('%w', date({ANCHOR}, '+1 day')) AS INTEGER) + 6) % 7) || ' days')
GROUP BY week, decision ORDER BY week""",
         "encoding": {"x": "week", "y": "runs", "series": "decision", "format": "number"},
         "insight": "Mix of approve / partial / deny / escalate."},
    ]
    layout = [{"panel_id": "accuracy-weekly", "x": 0, "y": 2, "w": 7, "h": 4},
              {"panel_id": "cost-latency", "x": 7, "y": 2, "w": 5, "h": 4},
              {"panel_id": "decisions", "x": 0, "y": 6, "w": 12, "h": 4}]
    out = tools.create_dashboard({"id": "refunddesk-agent", "title": "RefundDesk AI agent: quality, speed and cost",
                                  "subtitle": "For the head of support · complete weeks, rolling windows",
                                  "panels": panels, "layout": layout}, replace=True)
    return out["url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="also build the RefundDesk agent dashboard")
    parser.add_argument("--fast", action="store_true", help="no pauses between steps")
    args = parser.parse_args()
    pause = 0.0 if args.fast else 1.2
    print("Building the COO overview through the tool layer…")
    print("  ", coo_dashboard(pause))
    if args.all:
        print("Building the RefundDesk agent dashboard…")
        print("  ", agent_dashboard(pause))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
