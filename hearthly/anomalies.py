"""Simple, explainable anomaly ranking: recent window vs equal-length baseline windows."""

from __future__ import annotations

import math
import re
from datetime import timedelta
from typing import Any

from . import config, metrics, sqlguard

BASELINE_BLOCKS = 6
_PERIOD = re.compile(r"^(?:last_)?(\d{1,3})(?:_?d(?:ays?)?)?$")


def parse_period(period: str | int) -> int:
    """'last_14_days', '14d', '14' or 14 → 14 (allowed 3..90)."""
    if isinstance(period, int):
        days = period
    else:
        p = str(period).strip().lower()
        named = {"last_week": 7, "last_month": 30, "last_quarter": 90}
        if p in named:
            days = named[p]
        else:
            m = _PERIOD.match(p)
            if not m:
                raise metrics.MetricError(
                    f"period must look like 'last_7_days', 'last_14_days', 'last_30_days' or a number of days (got {period!r}).")
            days = int(m.group(1))
    if not 3 <= days <= 90:
        raise metrics.MetricError("period must be between 3 and 90 days.")
    return days


def detect_anomalies(metric_name: str, dimension: str, period: str | int = "last_14_days", top: int = 10) -> dict[str, Any]:
    layer = metrics.load_layer()
    metric = layer.get(metric_name)
    if dimension not in metric.base.dimensions:
        raise metrics.MetricError(
            f"Metric '{metric_name}' cannot be split by '{dimension}'. "
            f"Allowed dimensions: {', '.join(metric.base.dimensions)}.")
    n = parse_period(period)
    end = metrics.data_end_date()
    start = end - timedelta(days=n * (BASELINE_BLOCKS + 1) - 1)
    col = metric.base.time_column
    # block 0 = most recent n days, 1..BASELINE_BLOCKS = earlier equal-length windows
    block = f"CAST((julianday('{end.isoformat()}') - julianday({col})) / {n} AS INTEGER)"
    sql = metrics.compile_metric(metric, "total", start, end, dimension, bucket_override=block)
    res = sqlguard.run_select(sql, limit=config.MAX_PANEL_ROWS)

    series: dict[Any, dict[int, float]] = {}
    for period_block, member, value in res.rows:
        if value is None:
            continue
        series.setdefault(member, {})[int(period_block)] = float(value)

    findings: list[dict[str, Any]] = []
    for member, blocks in series.items():
        if 0 not in blocks:
            continue
        baseline = [blocks[b] for b in range(1, BASELINE_BLOCKS + 1) if b in blocks]
        if len(baseline) < 3:
            continue
        mean = sum(baseline) / len(baseline)
        var = sum((x - mean) ** 2 for x in baseline) / (len(baseline) - 1)
        std = max(math.sqrt(var), abs(mean) * 0.03, 1e-9)
        recent = blocks[0]
        z = (recent - mean) / std
        ratio = recent / mean if mean else None
        findings.append({
            dimension: member,
            "recent_value": round(recent, 6),
            "baseline_mean": round(mean, 6),
            "ratio_to_baseline": round(ratio, 3) if ratio is not None else None,
            "z_score": round(z, 2),
            "direction": "up" if recent > mean else "down",
        })
    findings.sort(key=lambda f: abs(f["z_score"]), reverse=True)
    return {
        "metric": metric_name,
        "dimension": dimension,
        "recent_window": {"start": (end - timedelta(days=n - 1)).isoformat(), "end": end.isoformat(), "days": n},
        "baseline": f"{BASELINE_BLOCKS} preceding {n}-day windows ({start.isoformat()} to {(end - timedelta(days=n)).isoformat()})",
        "method": "z = (recent − mean(baseline windows)) / std(baseline windows); ranked by |z|. "
                  "Small groups are noisy: confirm with run_query before concluding.",
        "format": metric.format,
        "anomalies": findings[:top],
        "groups_considered": len(findings),
        "sql": sql,
        "elapsed_ms": round(res.elapsed_ms, 1),
    }
