"""metrics.yaml compiles for every metric/grain/dimension; anomalies rank sensibly."""

from __future__ import annotations

from pathlib import Path

import pytest

from hearthly import anomalies, metrics

REQUIRED = {
    "gross_revenue", "net_revenue", "aov", "orders", "refund_rate", "refund_rate_by_amount",
    "on_time_delivery_pct", "avg_first_response_minutes", "csat", "agent_accuracy",
    "agent_auto_resolution_rate", "agent_cost_per_successful_task",
}


def test_required_metrics_present() -> None:
    assert REQUIRED <= set(metrics.load_layer().metrics)


@pytest.mark.parametrize("name", sorted(metrics.load_layer().metrics))
def test_every_metric_every_dimension(business_db: Path, name: str) -> None:
    m = metrics.load_layer().get(name)
    total = metrics.get_metric(name, "total")
    assert total["row_count"] == 1 and total["rows"][0][0] is not None
    assert total["sql"].lstrip().upper().startswith(("WITH", "SELECT"))
    for dim in m.base.dimensions:
        res = metrics.get_metric(name, "month", group_by=dim)
        assert res["columns"] == ["period", dim, name]


@pytest.mark.parametrize("grain", metrics.GRAINS)
def test_grains(business_db: Path, grain: str) -> None:
    res = metrics.get_metric("orders", grain)
    assert res["row_count"] >= 1
    if grain != "total":
        assert res["columns"] == ["period", "orders"]


def test_consistency_between_metrics(business_db: Path) -> None:
    g = metrics.get_metric("gross_revenue", "total")["rows"][0][0]
    o = metrics.get_metric("orders", "total")["rows"][0][0]
    aov = metrics.get_metric("aov", "total")["rows"][0][0]
    assert aov == pytest.approx(g / o, rel=1e-6)
    by_category = sum(r[1] for r in metrics.get_metric("gross_revenue", "total", group_by="category")["rows"])
    assert by_category == pytest.approx(g, rel=1e-9)


def test_bad_requests_are_actionable(business_db: Path) -> None:
    with pytest.raises(metrics.MetricError, match="Available"):
        metrics.get_metric("revenue_typo")
    with pytest.raises(metrics.MetricError, match="Allowed dimensions"):
        metrics.get_metric("csat", group_by="courier")
    with pytest.raises(metrics.MetricError, match="grain"):
        metrics.get_metric("orders", "hourly")
    with pytest.raises(metrics.MetricError, match="ISO date"):
        metrics.get_metric("orders", start="last tuesday")


def test_anomalies_rank_by_abs_z(business_db: Path) -> None:
    res = anomalies.detect_anomalies("tickets", "category", "last_30_days")
    zs = [abs(a["z_score"]) for a in res["anomalies"]]
    assert zs == sorted(zs, reverse=True)
    assert res["groups_considered"] >= 3


@pytest.mark.parametrize("period,days", [("last_7_days", 7), ("14d", 14), ("30", 30), (21, 21), ("last_month", 30)])
def test_period_parsing(period: object, days: int) -> None:
    assert anomalies.parse_period(period) == days  # type: ignore[arg-type]


def test_period_rejects_garbage() -> None:
    with pytest.raises(metrics.MetricError):
        anomalies.parse_period("yesterday-ish")
