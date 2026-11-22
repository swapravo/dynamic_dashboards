"""Seed determinism and the six planted stories, each checked with SQL."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from hearthly.seed.generator import Dataset, HearthlyGenerator
from hearthly.seed.stories import StoryNumbers, measure
from hearthly.seed.writer import write_database

from .conftest import AS_OF


def _table_digest(path: Path) -> str:
    conn = sqlite3.connect(path)
    h = hashlib.sha256()
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            h.update(repr(row).encode())
    conn.close()
    return h.hexdigest()


def test_seed_is_deterministic(tmp_path: Path, dataset: Dataset, business_db: Path) -> None:
    again = HearthlyGenerator(AS_OF, seed=42).build()
    assert again.rows == dataset.rows
    other = tmp_path / "again.db"
    write_database(again, other)
    assert _table_digest(other) == _table_digest(business_db)


def test_different_seed_differs() -> None:
    a = HearthlyGenerator(AS_OF, seed=42).build()
    b = HearthlyGenerator(AS_OF, seed=7).build()
    assert a.rows["orders"][:200] != b.rows["orders"][:200]


def test_volumes_and_window(conn: sqlite3.Connection) -> None:
    n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    n_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert 105_000 <= n_orders <= 135_000
    assert 35_000 <= n_customers <= 46_000
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 40
    lo, hi = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    assert hi == str(AS_OF - timedelta(days=1)), "data must end yesterday"
    assert 540 <= (AS_OF - timedelta(days=1) - __import__("datetime").date.fromisoformat(lo)).days <= 550


def test_foreign_keys_hold(business_db: Path) -> None:
    c = sqlite3.connect(business_db)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.close()


def test_no_real_pii(conn: sqlite3.Connection) -> None:
    domains = {r[0] for r in conn.execute("SELECT DISTINCT substr(email, instr(email, '@') + 1) FROM customers")}
    assert domains == {"example.com"}


@pytest.fixture(scope="module")
def story(conn: sqlite3.Connection, dataset: Dataset) -> StoryNumbers:
    return measure(conn, dataset.timeline)


def test_story1_kettle_batch(conn: sqlite3.Connection, story: StoryNumbers) -> None:
    b17_rate = conn.execute("""
        SELECT COUNT(DISTINCT r.order_item_id) * 1.0 / COUNT(DISTINCT oi.id)
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        LEFT JOIN refunds r ON r.order_item_id = oi.id
        WHERE p.name = 'AirBrew Electric Kettle' AND oi.batch_code = 'KT-B17'""").fetchone()[0]
    baseline = story["baseline_item_refund_rate"]
    assert b17_rate >= 2.5 * baseline
    assert story["kettle_b17_defective_share"] >= 0.6
    span = conn.execute("""
        SELECT julianday(MAX(date(s.dispatched_at))) - julianday(MIN(date(s.dispatched_at)))
        FROM order_items oi JOIN shipments s ON s.order_id = oi.order_id WHERE oi.batch_code = 'KT-B17'""").fetchone()[0]
    assert 12 <= span <= 15
    assert story["kettle_b17_start"] == AS_OF - timedelta(days=60)


def test_story2_courier_delay(story: StoryNumbers) -> None:
    assert story["swiftship_ne_late_pct"] >= 0.22
    assert story["baseline_late_pct"] <= 0.08
    assert story["swiftship_ne_late_pct"] >= 3.5 * story["baseline_late_pct"]
    assert story["other_couriers_ne_recent_late_pct"] <= 0.10, "only SwiftShip should be affected"
    assert story["ne_wismo_per_day_recent"] >= 1.8 * story["ne_wismo_per_day_prior"]


def test_story3_flash_sale(story: StoryNumbers) -> None:
    assert 0.28 <= story["flash_revenue_lift"] <= 0.55
    assert -11 <= story["flash_margin_delta_pts"] <= -6
    assert story["flash_repeat_rate"] <= 0.6 * story["other_repeat_rate"]


def test_story4_seasonality(story: StoryNumbers) -> None:
    assert story["festive_avg_daily_revenue"] >= 1.2 * story["other_avg_daily_revenue"]
    assert story["january_avg_daily_revenue"] >= 1.08 * story["other_avg_daily_revenue"]
    assert story["weekend_avg_daily_revenue"] >= 1.15 * story["weekday_avg_daily_revenue"]


def test_story5_refunddesk_drift(conn: sqlite3.Connection, story: StoryNumbers) -> None:
    assert story["acc_v3"] >= 0.89
    assert story["acc_v4"] <= 0.85
    assert story["acc_v3"] - story["acc_v4"] >= 0.07
    # concentrated in boundary cases
    boundary_drop = story["acc_v3_boundary"] - story["acc_v4_boundary"]
    normal_drop = story["acc_v3_normal"] - story["acc_v4_normal"]
    assert boundary_drop >= 3 * normal_drop
    # model swap: cheaper but slower
    assert story["cost_lite"] <= 0.5 * story["cost_pro"]
    assert story["latency_lite"] >= 1.3 * story["latency_pro"]
    first_v4 = conn.execute("SELECT MIN(date(run_at)) FROM agent_runs WHERE prompt_version = 'v4'").fetchone()[0]
    assert first_v4 >= str(AS_OF - timedelta(days=21))
    first_lite = conn.execute("SELECT MIN(date(run_at)) FROM agent_runs WHERE model = 'hx-lite-2026-10'").fetchone()[0]
    assert first_lite >= str(AS_OF - timedelta(days=10))


def test_story6_data_quality(story: StoryNumbers) -> None:
    assert 0.005 <= story["null_state_pct"] <= 0.02
    assert story["late_arriving_refunds"] >= 3
