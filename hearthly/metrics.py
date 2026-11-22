"""Semantic layer: load metrics.yaml and compile metrics into SQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from . import config, sqlguard

Grain = Literal["day", "week", "month", "quarter", "total"]
GRAINS: tuple[str, ...] = ("day", "week", "month", "quarter", "total")


class MetricError(ValueError):
    """Bad metric request; message is actionable for the caller."""


@dataclass(frozen=True)
class Dimension:
    name: str
    expr: str
    join: str | None = None


@dataclass(frozen=True)
class Base:
    name: str
    description: str
    from_clause: str
    time_column: str
    cte: str | None
    where: str | None
    dimensions: dict[str, Dimension]


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    description: str
    base: Base
    expression: str
    unit: str
    format: str
    additive: bool

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": " ".join(self.description.split()),
            "unit": self.unit,
            "format": self.format,
            "dimensions": list(self.base.dimensions),
            "formula": self.expression,
            "base": self.base.name,
        }


@dataclass
class SemanticLayer:
    metrics: dict[str, Metric]
    bases: dict[str, Base]
    raw_text: str = field(repr=False)

    def get(self, name: str) -> Metric:
        if name not in self.metrics:
            raise MetricError(f"Unknown metric '{name}'. Available: {', '.join(self.metrics)}.")
        return self.metrics[name]


def _load(path: Path) -> SemanticLayer:
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    bases: dict[str, Base] = {}
    for bname, b in doc["bases"].items():
        dims = {
            dname: Dimension(dname, str(d["expr"]), d.get("join"))
            for dname, d in (b.get("dimensions") or {}).items()
        }
        bases[bname] = Base(bname, " ".join(str(b.get("description", "")).split()), b["from"].strip(),
                            b["time_column"], (b.get("cte") or "").strip() or None, b.get("where"), dims)
    metrics: dict[str, Metric] = {}
    for mname, m in doc["metrics"].items():
        if m["base"] not in bases:
            raise ValueError(f"metric {mname}: unknown base {m['base']}")
        metrics[mname] = Metric(mname, m["label"], str(m["description"]).strip(), bases[m["base"]],
                                " ".join(str(m["expression"]).split()), m["unit"], m["format"], bool(m.get("additive")))
    return SemanticLayer(metrics, bases, text)


@lru_cache(maxsize=4)
def _cached(path: str, mtime: float) -> SemanticLayer:
    return _load(Path(path))


def load_layer() -> SemanticLayer:
    path = config.metrics_path()
    return _cached(str(path), path.stat().st_mtime)


def bucket_expr(grain: str, col: str) -> str | None:
    if grain == "day":
        return col
    if grain == "week":  # ISO week starting Monday, labelled by its Monday
        return f"date({col}, '-' || ((CAST(strftime('%w', {col}) AS INTEGER) + 6) % 7) || ' days')"
    if grain == "month":
        return f"strftime('%Y-%m', {col})"
    if grain == "quarter":
        return f"strftime('%Y', {col}) || '-Q' || ((CAST(strftime('%m', {col}) AS INTEGER) + 2) / 3)"
    if grain == "total":
        return None
    raise MetricError(f"Unknown grain '{grain}'. Use one of: {', '.join(GRAINS)}.")


def data_end_date() -> date:
    """Last date with orders (the data ends 'yesterday')."""
    res = sqlguard.run_select("SELECT MAX(order_date) FROM orders", limit=1)
    return date.fromisoformat(res.rows[0][0])


def _parse_date(value: str | None, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise MetricError(f"{name} must be an ISO date like 2026-01-31 (got {value!r}).") from None


def resolve_range(start: str | None, end: str | None, default_days: int = 90) -> tuple[date, date]:
    e = _parse_date(end, "end") or data_end_date()
    s = _parse_date(start, "start") or (e - timedelta(days=default_days - 1))
    if s > e:
        raise MetricError(f"start ({s}) is after end ({e}).")
    return s, e


ANCHOR = "(SELECT MAX(order_date) FROM orders)"


def rolling_filter(col: str, grain: str, days: int) -> str:
    """Date filter for a rolling window ending at the latest data.

    For week/month grains only complete periods are kept (a partial first or last bucket would
    make trends and period-over-period comparisons misleading)."""
    if grain == "week":
        start = bucket_expr("week", f"date({ANCHOR}, '-{days} day')")
        end = bucket_expr("week", f"date({ANCHOR}, '+1 day')")
        return f"{col} >= date({start}, '+7 day') AND {col} < {end}"
    if grain == "month":
        return (f"{col} >= date({ANCHOR}, '-{days} day', 'start of month', '+1 month') "
                f"AND {col} < date({ANCHOR}, '+1 day', 'start of month')")
    return f"{col} > date({ANCHOR}, '-{days} day')"


def compile_metric(metric: Metric, grain: str, start: date, end: date, group_by: str | None = None,
                   *, bucket_override: str | None = None, rolling_days: int | None = None) -> str:
    """Compile to one SELECT. With `rolling_days`, the date filter is relative to the latest data
    (so saved dashboards stay live) instead of the literal start/end dates."""
    base = metric.base
    dim: Dimension | None = None
    if group_by:
        if group_by not in base.dimensions:
            raise MetricError(
                f"Metric '{metric.name}' cannot be grouped by '{group_by}'. "
                f"Allowed dimensions: {', '.join(base.dimensions) or '(none)'}.")
        dim = base.dimensions[group_by]
    bucket = bucket_override or bucket_expr(grain, base.time_column)

    select: list[str] = []
    group: list[str] = []
    if bucket:
        select.append(f"{bucket} AS period")
        group.append("period")
    if dim:
        select.append(f"{dim.expr} AS {dim.name}")
        group.append(dim.name)
    select.append(f"{metric.expression} AS {metric.name}")

    if rolling_days:
        where = [rolling_filter(base.time_column, grain, int(rolling_days))]
    else:
        where = [f"{base.time_column} BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"]
    if base.where:
        where.insert(0, base.where)
    joins = f"\n{dim.join}" if dim and dim.join else ""

    sql = ""
    if base.cte:
        sql += f"WITH {base.cte}\n"
    sql += "SELECT " + ",\n       ".join(select)
    sql += f"\nFROM {base.from_clause}{joins}"
    sql += "\nWHERE " + "\n  AND ".join(where)
    if group:
        sql += "\nGROUP BY " + ", ".join(group)
        sql += "\nORDER BY " + ", ".join(group)
    return sql


def get_metric(name: str, grain: str = "week", start: str | None = None, end: str | None = None,
               group_by: str | None = None, rolling_days: int | None = None) -> dict[str, Any]:
    """Compute a metric. Without start/end the window is rolling (default 90 days, or `rolling_days`)."""
    layer = load_layer()
    metric = layer.get(name)
    if grain not in GRAINS:
        raise MetricError(f"Unknown grain '{grain}'. Use one of: {', '.join(GRAINS)}.")
    rolling = None
    if not start and not end:
        rolling = int(rolling_days or 90)
        if not 1 <= rolling <= 800:
            raise MetricError("rolling_days must be between 1 and 800.")
        s, e = resolve_range(None, None, default_days=rolling)
    else:
        s, e = resolve_range(start, end)
    sql = compile_metric(metric, grain, s, e, group_by or None, rolling_days=rolling)
    result = sqlguard.run_select(sql, limit=config.MAX_PANEL_ROWS)
    return {
        "metric": metric.name,
        "label": metric.label,
        "definition": " ".join(metric.description.split()),
        "unit": metric.unit,
        "format": metric.format,
        "grain": grain,
        "start": s.isoformat(),
        "end": e.isoformat(),
        "window": (f"rolling {rolling} days to the latest data (SQL stays live)"
                   + ("; complete weeks/months only" if grain in ("week", "month") else "")) if rolling else "fixed dates",
        "group_by": group_by,
        "sql": sql,
        **result.as_dict(),
    }
