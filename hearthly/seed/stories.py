"""Presenter-only measurements of the planted stories.

Used to write docs/DEMO_SECRETS.md and by the test-suite. Never imported by the MCP server
or the web app, so none of this text reaches Claude.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .catalog import NORTHEAST_STATES
from .timeline import (
    COURIER_DELAY_START_AGO,
    KETTLE_BATCH_DAYS,
    KETTLE_BATCH_START_AGO,
    MODEL_SWAP_AGO,
    PROMPT_V4_AGO,
    Timeline,
)

NE_LIST = ",".join(f"'{s}'" for s in NORTHEAST_STATES)


@dataclass
class StoryNumbers:
    values: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


def _one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def measure(conn: sqlite3.Connection, tl: Timeline) -> StoryNumbers:
    v: dict[str, Any] = {"as_of": tl.as_of, "start": tl.start, "end": tl.end}

    # 1. Kettle batch -----------------------------------------------------------------
    b17_start = tl.ago(KETTLE_BATCH_START_AGO)
    v["kettle_b17_start"] = b17_start
    v["kettle_b17_end"] = b17_start + timedelta(days=KETTLE_BATCH_DAYS - 1)
    item_rate = """
        SELECT COUNT(DISTINCT r.order_item_id) * 1.0 / COUNT(DISTINCT oi.id)
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.status != 'cancelled'
        LEFT JOIN refunds r ON r.order_item_id = oi.id
        WHERE {cond}"""
    v["kettle_b17_items"] = _one(conn, "SELECT COUNT(*) FROM order_items WHERE batch_code='KT-B17'")
    v["kettle_b17_refund_rate"] = _one(conn, item_rate.format(cond="oi.batch_code = 'KT-B17'"))
    v["kettle_other_refund_rate"] = _one(conn, item_rate.format(
        cond="oi.batch_code LIKE 'KT-%' AND oi.batch_code != 'KT-B17'"))
    v["baseline_item_refund_rate"] = _one(conn, item_rate.format(cond="oi.batch_code != 'KT-B17'"))
    v["kettle_b17_defective_share"] = _one(conn, """
        SELECT AVG(r.reason = 'defective') FROM refunds r JOIN order_items oi ON oi.id = r.order_item_id
        WHERE oi.batch_code = 'KT-B17'""")
    v["baseline_defective_share"] = _one(conn, """
        SELECT AVG(r.reason = 'defective') FROM refunds r JOIN order_items oi ON oi.id = r.order_item_id
        WHERE oi.batch_code != 'KT-B17'""")

    # 2. Courier delay ----------------------------------------------------------------
    delay_start = tl.ago(COURIER_DELAY_START_AGO)
    v["courier_delay_start"] = delay_start
    late_sql = f"""
        SELECT AVG(date(delivered_at) > promised_date), COUNT(*) FROM shipments
        WHERE delivered_at IS NOT NULL AND {{cond}}"""
    story = f"courier = 'SwiftShip' AND destination_state IN ({NE_LIST}) AND date(dispatched_at) >= '{delay_start}'"
    v["swiftship_ne_late_pct"], v["swiftship_ne_shipments"] = conn.execute(late_sql.format(cond=story)).fetchone()
    v["baseline_late_pct"] = conn.execute(late_sql.format(cond=f"NOT ({story})")).fetchone()[0]
    v["other_couriers_ne_recent_late_pct"] = conn.execute(late_sql.format(
        cond=f"courier != 'SwiftShip' AND destination_state IN ({NE_LIST}) AND date(dispatched_at) >= '{delay_start}'"
    )).fetchone()[0]
    wismo = f"""
        SELECT COUNT(*) * 1.0 / ? FROM support_tickets t JOIN customers c ON c.id = t.customer_id
        WHERE t.category = 'where_is_my_order' AND c.region = 'Northeast'
          AND date(t.created_at) BETWEEN ? AND ?"""
    recent_days = (tl.end - delay_start).days + 1
    v["ne_wismo_per_day_recent"] = _one(conn, wismo, (recent_days, str(delay_start), str(tl.end)))
    prior_start = delay_start - timedelta(days=90)
    v["ne_wismo_per_day_prior"] = _one(conn, wismo, (90, str(prior_start), str(delay_start - timedelta(days=1))))

    # 3. Weekend Flash Sale -------------------------------------------------------------
    fs, fe = tl.flash_window()
    v["flash_start"], v["flash_end"] = fs, fe
    day_stats = """
        WITH day AS (
            SELECT o.order_date AS d,
                   SUM(oi.quantity * oi.unit_price) AS gross,
                   SUM(oi.quantity * p.unit_cost) AS cogs
            FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
            WHERE o.status != 'cancelled' GROUP BY o.order_date),
        disc AS (SELECT order_date AS d, SUM(discount_amount) AS discount FROM orders
                 WHERE status != 'cancelled' GROUP BY order_date)
        SELECT AVG(gross), (SUM(gross) - SUM(discount) - SUM(cogs)) / SUM(gross)
        FROM day JOIN disc USING (d)
        WHERE strftime('%w', d) IN ('0', '6') AND {cond}"""
    flash_cond = f"d BETWEEN '{fs}' AND '{fe}'"
    normal_cond = (f"NOT ({flash_cond}) AND CAST(strftime('%m', d) AS INT) NOT IN (1, 10, 11)")
    v["flash_weekend_avg_revenue"], v["flash_weekend_margin"] = conn.execute(day_stats.format(cond=flash_cond)).fetchone()
    v["normal_weekend_avg_revenue"], v["normal_weekend_margin"] = conn.execute(day_stats.format(cond=normal_cond)).fetchone()
    # nearby comparison: non-flash, non-festive weekends within 13 weeks either side of the window
    near_cond = (f"NOT ({flash_cond}) AND d BETWEEN '{fs - timedelta(days=91)}' AND '{fe + timedelta(days=91)}' "
                 "AND CAST(strftime('%m', d) AS INT) NOT IN (1, 10, 11)")
    v["nearby_weekend_avg_revenue"], v["nearby_weekend_margin"] = conn.execute(day_stats.format(cond=near_cond)).fetchone()
    v["flash_revenue_lift"] = v["flash_weekend_avg_revenue"] / v["nearby_weekend_avg_revenue"] - 1
    v["flash_margin_delta_pts"] = (v["flash_weekend_margin"] - v["nearby_weekend_margin"]) * 100
    repeat = """
        WITH firsts AS (
            SELECT o.customer_id, o.campaign_id, o.order_date,
                   ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_date, o.id) AS rn
            FROM orders o JOIN customers c ON c.id = o.customer_id
            WHERE c.signup_date >= ? ),
        n AS (SELECT customer_id, COUNT(*) AS orders FROM orders GROUP BY customer_id)
        SELECT AVG(n.orders >= 2), COUNT(*) FROM firsts f JOIN n USING (customer_id)
        WHERE f.rn = 1 AND f.order_date BETWEEN ? AND ? AND {cond}"""
    flash_id = _one(conn, "SELECT id FROM campaigns WHERE name = 'Weekend Flash Sale'")
    args = (str(tl.start), str(fs), str(fe))
    v["flash_repeat_rate"], v["flash_new_customers"] = conn.execute(
        repeat.format(cond=f"f.campaign_id = {flash_id}"), args).fetchone()
    v["other_repeat_rate"], _ = conn.execute(
        repeat.format(cond=f"(f.campaign_id IS NULL OR f.campaign_id != {flash_id})"), args).fetchone()

    # 4. Seasonality ---------------------------------------------------------------------
    rev_by = """
        SELECT AVG(rev) FROM (SELECT o.order_date AS d, SUM(oi.quantity * oi.unit_price) AS rev
            FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE o.status != 'cancelled'
            GROUP BY o.order_date) WHERE {cond}"""
    v["festive_avg_daily_revenue"] = _one(conn, rev_by.format(cond="CAST(strftime('%m', d) AS INT) IN (10, 11)"))
    v["january_avg_daily_revenue"] = _one(conn, rev_by.format(cond="CAST(strftime('%m', d) AS INT) = 1"))
    v["other_avg_daily_revenue"] = _one(conn, rev_by.format(
        cond=f"CAST(strftime('%m', d) AS INT) NOT IN (1, 10, 11) AND NOT (d BETWEEN '{fs}' AND '{fe}')"))
    v["weekend_avg_daily_revenue"] = _one(conn, rev_by.format(cond="strftime('%w', d) IN ('0','6')"))
    v["weekday_avg_daily_revenue"] = _one(conn, rev_by.format(cond="strftime('%w', d) NOT IN ('0','6')"))

    # 5. RefundDesk drift -----------------------------------------------------------------
    v4_start, swap = tl.ago(PROMPT_V4_AGO), tl.ago(MODEL_SWAP_AGO)
    v["prompt_v4_start"], v["model_swap"] = v4_start, swap
    acc = """
        SELECT AVG(ar.audit_correct), COUNT(*) FROM agent_runs ar
        JOIN refunds r ON r.id = ar.refund_id
        JOIN shipments s ON s.order_id = r.order_id
        WHERE ar.audit_correct IS NOT NULL AND {cond}"""
    bnd = "(julianday(date(r.requested_at)) - julianday(date(s.delivered_at))) BETWEEN 27 AND 33"
    v3_window = f"ar.prompt_version = 'v3' AND date(ar.run_at) >= '{v4_start - timedelta(days=60)}'"
    v["acc_v3"], v["runs_v3"] = conn.execute(acc.format(cond=v3_window)).fetchone()
    v["acc_v4"], v["runs_v4"] = conn.execute(acc.format(cond="ar.prompt_version = 'v4'")).fetchone()
    v["acc_v3_boundary"], v["runs_v3_boundary"] = conn.execute(acc.format(cond=f"{v3_window} AND {bnd}")).fetchone()
    v["acc_v4_boundary"], v["runs_v4_boundary"] = conn.execute(acc.format(cond=f"ar.prompt_version = 'v4' AND {bnd}")).fetchone()
    v["acc_v3_normal"] = conn.execute(acc.format(cond=f"{v3_window} AND NOT {bnd}")).fetchone()[0]
    v["acc_v4_normal"] = conn.execute(acc.format(cond=f"ar.prompt_version = 'v4' AND NOT {bnd}")).fetchone()[0]
    model_sql = "SELECT AVG(cost_usd), AVG(latency_ms), COUNT(*) FROM agent_runs WHERE model = ?"
    v["cost_pro"], v["latency_pro"], _ = conn.execute(model_sql, ("hx-pro-2026-03",)).fetchone()
    v["cost_lite"], v["latency_lite"], v["runs_lite"] = conn.execute(model_sql, ("hx-lite-2026-10",)).fetchone()

    # 6. Data quality -----------------------------------------------------------------------
    v["null_state_pct"] = _one(conn, "SELECT AVG(destination_state IS NULL) FROM shipments")
    v["null_state_orders"] = _one(conn, "SELECT COUNT(*) FROM shipments WHERE destination_state IS NULL")
    v["late_arriving_refunds"] = _one(conn, """
        SELECT COUNT(*) FROM refunds r JOIN orders o ON o.id = r.order_id
        WHERE julianday(date(r.requested_at)) - julianday(o.order_date) > 90""")
    v["pending_refunds"] = _one(conn, "SELECT COUNT(*) FROM refunds WHERE resolution = 'pending'")

    # Totals
    for t in ("orders", "customers", "products", "order_items", "refunds", "support_tickets", "agent_runs"):
        v[f"n_{t}"] = _one(conn, f"SELECT COUNT(*) FROM {t}")
    return StoryNumbers(v)


def as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))
