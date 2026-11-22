"""Reusable sample specs for tests."""

from __future__ import annotations

from typing import Any

WEEKLY_REVENUE_SQL = """
SELECT strftime('%Y-%W', o.order_date) AS week, SUM(oi.quantity * oi.unit_price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status != 'cancelled' AND o.order_date > date((SELECT MAX(order_date) FROM orders), '-84 day')
GROUP BY week ORDER BY week
"""

REFUNDS_BY_REASON_SQL = """
SELECT reason, COUNT(*) AS requests FROM refunds
WHERE requested_at > date((SELECT MAX(order_date) FROM orders), '-90 day')
GROUP BY reason ORDER BY requests DESC
"""


def sample_spec(dashboard_id: str = "test-dash") -> dict[str, Any]:
    return {
        "id": dashboard_id,
        "title": "Test dashboard",
        "subtitle": "Last 12 weeks",
        "panels": [
            {"id": "rev-kpi", "type": "kpi", "title": "Weekly revenue", "sql": WEEKLY_REVENUE_SQL,
             "encoding": {"x": "week", "value": "revenue", "format": "currency"},
             "insight": "Revenue for the latest week."},
            {"id": "rev-trend", "type": "line", "title": "Revenue trend", "sql": WEEKLY_REVENUE_SQL,
             "encoding": {"x": "week", "y": "revenue", "format": "currency"}, "insight": "Steady."},
            {"id": "refund-reasons", "type": "donut", "title": "Refund reasons", "sql": REFUNDS_BY_REASON_SQL,
             "encoding": {"label": "reason", "value": "requests"}, "insight": "Mix of reasons."},
        ],
    }
