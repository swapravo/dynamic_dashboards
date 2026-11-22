"""The classic, hard-coded dashboard for /static: six fixed panels, one date-range dropdown.

Deliberately limited: the SQL is fixed in code, nothing can be added or drilled into.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..spec import Panel

RANGES: dict[str, int] = {"30": 30, "90": 90, "180": 180, "365": 365}

# {start} is replaced with a validated ISO date. Fixed SQL, written once by the BI team.
_PANELS: list[dict[str, Any]] = [
    {"id": "kpi-revenue", "type": "kpi", "title": "Gross revenue",
     "sql": """SELECT SUM(oi.quantity * oi.unit_price) AS value
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status != 'cancelled' AND o.order_date >= '{start}'""",
     "encoding": {"value": "value", "format": "currency"}},
    {"id": "kpi-orders", "type": "kpi", "title": "Orders",
     "sql": "SELECT COUNT(*) AS value FROM orders WHERE status != 'cancelled' AND order_date >= '{start}'",
     "encoding": {"value": "value", "format": "number"}},
    {"id": "kpi-aov", "type": "kpi", "title": "Average order value",
     "sql": """SELECT SUM(oi.quantity * oi.unit_price) * 1.0 / COUNT(DISTINCT o.id) AS value
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status != 'cancelled' AND o.order_date >= '{start}'""",
     "encoding": {"value": "value", "format": "currency"}},
    {"id": "revenue-by-month", "type": "bar", "title": "Revenue by month",
     "sql": """SELECT strftime('%Y-%m', o.order_date) AS month, SUM(oi.quantity * oi.unit_price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status != 'cancelled' AND o.order_date >= '{start}'
GROUP BY month ORDER BY month""",
     "encoding": {"x": "month", "y": "revenue", "format": "currency"}},
    {"id": "orders-by-channel", "type": "donut", "title": "Orders by sales channel",
     "sql": """SELECT channel, COUNT(*) AS orders FROM orders
WHERE status != 'cancelled' AND order_date >= '{start}' GROUP BY channel ORDER BY orders DESC""",
     "encoding": {"label": "channel", "value": "orders", "format": "number"}},
    {"id": "top-products", "type": "table", "title": "Top 10 products by revenue",
     "sql": """SELECT p.name AS product, p.category, SUM(oi.quantity) AS units,
       SUM(oi.quantity * oi.unit_price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
WHERE o.status != 'cancelled' AND o.order_date >= '{start}'
GROUP BY p.id ORDER BY revenue DESC LIMIT 10""",
     "encoding": {"value": "revenue", "format": "currency"}},
]

LAYOUT = [
    {"panel_id": "kpi-revenue", "x": 0, "y": 0, "w": 4, "h": 2},
    {"panel_id": "kpi-orders", "x": 4, "y": 0, "w": 4, "h": 2},
    {"panel_id": "kpi-aov", "x": 8, "y": 0, "w": 4, "h": 2},
    {"panel_id": "revenue-by-month", "x": 0, "y": 2, "w": 7, "h": 4},
    {"panel_id": "orders-by-channel", "x": 7, "y": 2, "w": 5, "h": 4},
    {"panel_id": "top-products", "x": 0, "y": 6, "w": 12, "h": 5},
]


def panels_for(range_key: str, data_end: date) -> list[Panel]:
    days = RANGES.get(range_key, 90)
    start = (data_end - timedelta(days=days - 1)).isoformat()
    return [Panel.model_validate({**p, "sql": p["sql"].replace("{start}", start), "insight": ""}) for p in _PANELS]
