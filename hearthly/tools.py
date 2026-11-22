"""Tool implementations shared by the MCP server, the fallback demo script and the tests.

Every public function logs one row to state.db's activity_log (tool, args summary, SQL,
row count, milliseconds, status) so the web app can show "What Claude just did".
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from . import anomalies, config, metrics, sqlguard
from .schema_docs import COLUMN_NOTES, CONVENTIONS, DATABASE_SUMMARY, TABLE_NOTES
from .seed.schema import TABLE_ORDER
from .spec import DashboardPatch, DashboardSpec, LayoutItem, Panel, PanelPatch, reflow
from .state import StateStore
from .validate import PanelRun, SpecError, validate_spec


class ToolInputError(ValueError):
    """Bad tool input (unknown dashboard, panel, table...). Message is actionable."""


KNOWN_ERRORS = (ToolInputError, sqlguard.QueryError, metrics.MetricError, SpecError)


def dashboard_url(dashboard_id: str) -> str:
    return f"http://{config.WEB_HOST}:{config.WEB_PORT}/dynamic#{dashboard_id}"


def _store() -> StateStore:
    return StateStore()


def _short(value: Any, n: int = 80) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


@contextmanager
def _activity(tool: str, args_summary: str) -> Iterator[dict[str, Any]]:
    rec: dict[str, Any] = {"sql": None, "rows": None, "dashboard_id": None, "detail": None}
    t0 = time.perf_counter()
    try:
        yield rec
    except Exception as err:
        _store().log_activity(tool, args_summary, (time.perf_counter() - t0) * 1000, "error", sql=rec["sql"],
                              error=str(err) if isinstance(err, KNOWN_ERRORS) else "internal error",
                              dashboard_id=rec["dashboard_id"], detail=rec["detail"])
        raise
    _store().log_activity(tool, args_summary, (time.perf_counter() - t0) * 1000, "ok", sql=rec["sql"],
                          rows=rec["rows"], dashboard_id=rec["dashboard_id"], detail=rec["detail"])


# --------------------------------------------------------------------------- schema


def _internal_conn() -> sqlite3.Connection:
    """Read-only connection without the authorizer, for trusted introspection (PRAGMA table_info)."""
    path = config.business_db_path()
    if not path.exists():
        raise ToolInputError(f"Business database not found at {path}. Run: python -m hearthly.seed --reset")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


@lru_cache(maxsize=4)
def _schema_cached(path: str, mtime: float) -> dict[str, Any]:
    conn = _internal_conn()
    try:
        tables: dict[str, Any] = {}
        for t in TABLE_ORDER:
            fks = {r[3]: f"{r[2]}.{r[4]}" for r in conn.execute(f"PRAGMA foreign_key_list({t})")}
            cols = []
            for _cid, name, ctype, notnull, _default, pk in conn.execute(f"PRAGMA table_info({t})"):
                col: dict[str, Any] = {"name": name, "type": ctype, "nullable": not notnull and not pk}
                if pk:
                    col["primary_key"] = True
                if name in fks:
                    col["references"] = fks[name]
                note = COLUMN_NOTES.get(t, {}).get(name)
                if note:
                    col["note"] = note
                if ctype == "TEXT" and not name.endswith(("_at", "_date")) and name not in ("name", "email", "sku"):
                    vals = conn.execute(f"SELECT DISTINCT {name} FROM {t} WHERE {name} IS NOT NULL "
                                        f"ORDER BY {name} LIMIT 13").fetchall()
                    if len(vals) <= 12:
                        col["values"] = [v[0] for v in vals]
                cols.append(col)
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cur = conn.execute(f"SELECT * FROM {t} ORDER BY id LIMIT 3")
            sample = {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
            tables[t] = {"name": t, "description": TABLE_NOTES[t], "row_count": count, "columns": cols,
                         "sample_rows": sample}
        lo, hi = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    finally:
        conn.close()
    return {"database": DATABASE_SUMMARY, "data_range": {"first_order_date": lo, "last_order_date": hi},
            "conventions": CONVENTIONS, "tables": tables}


def schema_snapshot() -> dict[str, Any]:
    path = config.business_db_path()
    if not path.exists():
        raise ToolInputError(f"Business database not found at {path}. Run: python -m hearthly.seed --reset")
    return _schema_cached(str(path), path.stat().st_mtime)


def describe_schema(table: str | None = None) -> dict[str, Any]:
    with _activity("describe_schema", f"table={table}" if table else "all tables") as rec:
        snap = schema_snapshot()
        if table:
            if table not in snap["tables"]:
                raise ToolInputError(f"Unknown table '{table}'. Tables: {', '.join(snap['tables'])}.")
            t = snap["tables"][table]
            rec["rows"] = len(t["sample_rows"]["rows"])
            return {**t, "conventions": snap["conventions"], "data_range": snap["data_range"]}
        overview = []
        for t in snap["tables"].values():
            overview.append({**t, "sample_rows": {"columns": t["sample_rows"]["columns"],
                                                  "rows": t["sample_rows"]["rows"][:2]}})
        rec["rows"] = len(overview)
        return {"database": snap["database"], "data_range": snap["data_range"], "conventions": snap["conventions"],
                "tables": overview}


# --------------------------------------------------------------------------- queries & metrics


def run_query(sql: str, limit: int = config.MAX_QUERY_ROWS) -> dict[str, Any]:
    with _activity("run_query", _short(sql, 120)) as rec:
        rec["sql"] = sql
        limit = max(1, min(int(limit), config.MAX_QUERY_ROWS))
        res = sqlguard.run_select(sql, limit=limit, hard_cap=config.MAX_QUERY_ROWS)
        rec["rows"] = res.row_count
        return res.as_dict()


def list_metrics() -> dict[str, Any]:
    with _activity("list_metrics", "") as rec:
        layer = metrics.load_layer()
        items = [m.summary() for m in layer.metrics.values()]
        rec["rows"] = len(items)
        return {
            "metrics": items,
            "grains": list(metrics.GRAINS),
            "notes": [
                "Ratios are fractions 0-1: use format 'percent' in panels.",
                "get_metric returns the exact SQL it ran; paste that SQL into dashboard panels for consistent numbers.",
                "Refund metrics are cohorted by order date, so the most recent weeks read low.",
            ],
        }


def get_metric(name: str, grain: str = "week", start: str | None = None, end: str | None = None,
               group_by: str | None = None, rolling_days: int | None = None) -> dict[str, Any]:
    window = f" {start or ''}→{end or ''}" if start or end else f" last {rolling_days or 90}d"
    summary = f"{name} by {grain}" + (f" × {group_by}" if group_by else "") + window
    with _activity("get_metric", summary) as rec:
        out = metrics.get_metric(name, grain, start, end, group_by, rolling_days)
        rec["sql"], rec["rows"] = out["sql"], out["row_count"]
        return out


def detect_anomalies(metric: str, dimension: str, period: str = "last_14_days") -> dict[str, Any]:
    with _activity("detect_anomalies", f"{metric} by {dimension}, {period}") as rec:
        out = anomalies.detect_anomalies(metric, dimension, period)
        rec["sql"], rec["rows"] = out["sql"], len(out["anomalies"])
        return out


# --------------------------------------------------------------------------- dashboards


def _panel_summaries(runs: list[PanelRun], spec: DashboardSpec) -> list[dict[str, Any]]:
    by_id = {p.id: p for p in spec.panels}
    return [{"id": r.panel_id, "type": by_id[r.panel_id].type, "title": by_id[r.panel_id].title,
             "rows": r.row_count, "ms": round(r.elapsed_ms, 1)} for r in runs]


def _save(spec: DashboardSpec, change: str, rec: dict[str, Any], focus: list[str] | None = None) -> dict[str, Any]:
    """Validate and store. `focus` = ids of panels this call added/edited (their SQL goes to the feed)."""
    rec["dashboard_id"] = spec.id
    try:
        laid_out, runs, warnings = validate_spec(spec)
    except SpecError as err:
        rec["detail"] = {"errors": err.errors}
        raise
    stored = _store().save_dashboard(laid_out, change)
    panels = _panel_summaries(runs, stored)
    rec["rows"] = sum(p["rows"] for p in panels)
    rec["detail"] = {"title": stored.title, "version": stored.version, "panels": panels, "change": change,
                     "focus": focus or []}
    focused = [p for p in stored.panels if focus and p.id in focus]
    rec["sql"] = "\n\n".join(f"-- {p.id}\n{p.sql.strip()}" for p in focused) or None
    return {
        "id": stored.id,
        "title": stored.title,
        "version": stored.version,
        "url": dashboard_url(stored.id),
        "panels": panels,
        "layout": [i.model_dump() for i in stored.layout],
        "warnings": warnings,
        "message": f"Saved '{stored.title}' (version {stored.version}). It is live in the /dynamic workspace "
                   "and re-runs its SQL on every refresh.",
    }


def _require(dashboard_id: str) -> DashboardSpec:
    spec = _store().get_dashboard(dashboard_id)
    if spec is None:
        existing = [d["id"] for d in _store().list_dashboards()]
        raise ToolInputError(f"No dashboard with id '{dashboard_id}'. Existing ids: {', '.join(existing) or '(none)'}.")
    return spec


def create_dashboard(spec: DashboardSpec | dict[str, Any], replace: bool = False) -> dict[str, Any]:
    spec = spec if isinstance(spec, DashboardSpec) else DashboardSpec.model_validate(spec)
    with _activity("create_dashboard", f"'{spec.title}' ({len(spec.panels)} panels)") as rec:
        rec["dashboard_id"] = spec.id
        if _store().exists(spec.id) and not replace:
            raise ToolInputError(f"Dashboard '{spec.id}' already exists. Use update_dashboard / add_panel to change "
                                 "it, pass replace=true to overwrite it, or choose a new id.")
        return _save(spec, "replaced" if replace else "created", rec)


def _apply_panel_patch(current: dict[str, Panel], patch: PanelPatch) -> Panel:
    if patch.id in current:
        base = current[patch.id].model_dump()
        changes = patch.model_dump(exclude_none=True, exclude={"encoding"})
        base.update(changes)
        if patch.encoding is not None:
            enc = base["encoding"]
            enc.update(patch.encoding.model_dump(exclude_none=True))
        return Panel.model_validate(base)
    missing = [f for f in ("type", "title", "sql") if getattr(patch, f) is None]
    if missing:
        raise ToolInputError(f"Panel '{patch.id}' does not exist yet, so it needs {', '.join(missing)} to be added "
                             f"(existing panels: {', '.join(current) or 'none'}).")
    return Panel.model_validate(patch.model_dump(exclude_none=True))


def update_dashboard(dashboard_id: str, patch: DashboardPatch | dict[str, Any]) -> dict[str, Any]:
    patch = patch if isinstance(patch, DashboardPatch) else DashboardPatch.model_validate(patch)
    with _activity("update_dashboard", f"{dashboard_id}: {_short(patch.model_dump(exclude_defaults=True), 100)}") as rec:
        rec["dashboard_id"] = dashboard_id
        spec = _require(dashboard_id)
        panels = {p.id: p for p in spec.panels}
        order = [p.id for p in spec.panels]
        changes: list[str] = []
        for pid in patch.remove_panel_ids:
            if pid not in panels:
                raise ToolInputError(f"Cannot remove panel '{pid}': not on dashboard '{dashboard_id}'. "
                                     f"Panels: {', '.join(order)}.")
            del panels[pid]
            order.remove(pid)
            changes.append(f"removed {pid}")
        for pp in patch.panels:
            is_new = pp.id not in panels
            panels[pp.id] = _apply_panel_patch(panels, pp)
            if is_new:
                order.append(pp.id)
            changes.append(("added " if is_new else "edited ") + pp.id)
        if patch.panel_order is not None:
            if sorted(patch.panel_order) != sorted(order):
                raise ToolInputError(f"panel_order must list exactly these panel ids: {', '.join(order)}.")
            order = list(patch.panel_order)
            changes.append("reordered")
        layout = {i.panel_id: i for i in spec.layout if i.panel_id in panels}
        for item in patch.layout:
            if item.panel_id not in panels:
                raise ToolInputError(f"layout refers to unknown panel '{item.panel_id}'.")
            layout[item.panel_id] = item
        if patch.layout:
            changes.append("layout")
        updates: dict[str, Any] = {"panels": [panels[i] for i in order], "layout": list(layout.values())}
        for f in ("title", "subtitle", "refresh_seconds"):
            v = getattr(patch, f)
            if v is not None:
                updates[f] = v
                changes.append(f)
        if not changes:
            raise ToolInputError("The patch is empty: nothing to change.")
        new_spec = DashboardSpec.model_validate({**spec.model_dump(), **{k: v for k, v in updates.items()
                                                                        if k not in ("panels", "layout")},
                                                 "panels": [p.model_dump() for p in updates["panels"]],
                                                 "layout": [i.model_dump() for i in updates["layout"]]})
        if patch.remove_panel_ids or patch.panel_order is not None:
            new_spec = reflow(new_spec)
        return _save(new_spec, "; ".join(changes), rec, focus=[pp.id for pp in patch.panels if pp.sql is not None])


def add_panel(dashboard_id: str, panel: Panel | dict[str, Any], position: LayoutItem | dict[str, Any] | None = None
              ) -> dict[str, Any]:
    panel = panel if isinstance(panel, Panel) else Panel.model_validate(panel)
    with _activity("add_panel", f"{dashboard_id} + {panel.type} '{panel.title}'") as rec:
        rec["dashboard_id"] = dashboard_id
        spec = _require(dashboard_id)
        if any(p.id == panel.id for p in spec.panels):
            raise ToolInputError(f"Panel id '{panel.id}' already exists on '{dashboard_id}'. Use update_dashboard to "
                                 "edit it or pick a new id.")
        layout = list(spec.layout)
        if position is not None:
            pos = position if isinstance(position, LayoutItem) else LayoutItem.model_validate(
                {"panel_id": panel.id, **{k: v for k, v in dict(position).items() if k != "panel_id"}})
            layout.append(pos.model_copy(update={"panel_id": panel.id}))
        new_spec = spec.model_copy(update={"panels": [*spec.panels, panel], "layout": layout})
        return _save(new_spec, f"added {panel.id}", rec, focus=[panel.id])


def remove_panel(dashboard_id: str, panel_id: str) -> dict[str, Any]:
    with _activity("remove_panel", f"{dashboard_id} − {panel_id}") as rec:
        rec["dashboard_id"] = dashboard_id
        spec = _require(dashboard_id)
        if not any(p.id == panel_id for p in spec.panels):
            raise ToolInputError(f"Panel '{panel_id}' is not on '{dashboard_id}'. "
                                 f"Panels: {', '.join(p.id for p in spec.panels)}.")
        if len(spec.panels) == 1:
            raise ToolInputError("Cannot remove the last panel; a dashboard needs at least one.")
        new_spec = reflow(spec.model_copy(update={"panels": [p for p in spec.panels if p.id != panel_id]}))
        return _save(new_spec, f"removed {panel_id}", rec)


def list_dashboards() -> dict[str, Any]:
    with _activity("list_dashboards", "") as rec:
        items = [{**d, "url": dashboard_url(d["id"])} for d in _store().list_dashboards()]
        rec["rows"] = len(items)
        return {"dashboards": items}


def get_dashboard(dashboard_id: str) -> dict[str, Any]:
    with _activity("get_dashboard", dashboard_id) as rec:
        rec["dashboard_id"] = dashboard_id
        spec = _require(dashboard_id)
        rec["rows"] = len(spec.panels)
        return {"spec": spec.model_dump(), "url": dashboard_url(spec.id),
                "history": _store().history(dashboard_id)[:10]}
