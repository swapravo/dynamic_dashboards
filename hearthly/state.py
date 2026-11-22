"""Dashboard and activity storage in data/state.db (separate from the business DB, WAL mode).

The MCP server writes; the web app reads. Both are separate processes, so every operation
opens a short-lived connection.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config
from .spec import DashboardSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboards (
    id         TEXT PRIMARY KEY,
    spec       TEXT NOT NULL,
    version    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dashboard_versions (
    dashboard_id TEXT NOT NULL,
    version      INTEGER NOT NULL,
    spec         TEXT NOT NULL,
    change       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (dashboard_id, version)
);
CREATE TABLE IF NOT EXISTS activity_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    tool         TEXT NOT NULL,
    args_summary TEXT NOT NULL,
    sql          TEXT,
    rows         INTEGER,
    ms           REAL NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    dashboard_id TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(ts);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or config.state_db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ----- dashboards

    def save_dashboard(self, spec: DashboardSpec, change: str) -> DashboardSpec:
        """Insert or update; bumps version and records history. Returns the stored spec."""
        ts = now_iso()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT version, created_at FROM dashboards WHERE id = ?", (spec.id,)).fetchone()
            version = (row["version"] + 1) if row else 1
            stored = spec.model_copy(update={"version": version, "updated_at": ts})
            blob = stored.model_dump_json()
            if row:
                conn.execute("UPDATE dashboards SET spec = ?, version = ?, updated_at = ? WHERE id = ?",
                             (blob, version, ts, spec.id))
            else:
                conn.execute("INSERT INTO dashboards (id, spec, version, created_at, updated_at) VALUES (?,?,?,?,?)",
                             (spec.id, blob, version, ts, ts))
            conn.execute("INSERT INTO dashboard_versions (dashboard_id, version, spec, change, created_at) "
                         "VALUES (?,?,?,?,?)", (spec.id, version, blob, change, ts))
        return stored

    def get_dashboard(self, dashboard_id: str) -> DashboardSpec | None:
        with self._conn() as conn:
            row = conn.execute("SELECT spec FROM dashboards WHERE id = ?", (dashboard_id,)).fetchone()
        return DashboardSpec.model_validate_json(row["spec"]) if row else None

    def exists(self, dashboard_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM dashboards WHERE id = ?", (dashboard_id,)).fetchone() is not None

    def list_dashboards(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id, spec, version, created_at, updated_at FROM dashboards "
                                "ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            spec = json.loads(r["spec"])
            out.append({"id": r["id"], "title": spec["title"], "subtitle": spec.get("subtitle", ""),
                        "panels": len(spec["panels"]), "version": r["version"],
                        "created_at": r["created_at"], "updated_at": r["updated_at"]})
        return out

    def history(self, dashboard_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT version, change, created_at FROM dashboard_versions WHERE dashboard_id = ? "
                                "ORDER BY version DESC", (dashboard_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_dashboard(self, dashboard_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
            conn.execute("DELETE FROM dashboard_versions WHERE dashboard_id = ?", (dashboard_id,))
            return cur.rowcount > 0

    def reset(self, *, keep_activity: bool = False) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM dashboards")
            conn.execute("DELETE FROM dashboard_versions")
            if not keep_activity:
                conn.execute("DELETE FROM activity_log")

    # ----- activity

    def log_activity(self, tool: str, args_summary: str, ms: float, status: str = "ok", *, sql: str | None = None,
                     rows: int | None = None, error: str | None = None, dashboard_id: str | None = None,
                     detail: Any = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO activity_log (ts, tool, args_summary, sql, rows, ms, status, error, dashboard_id, detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), tool, args_summary[:500], sql, rows, round(ms, 1), status, (error or None) and error[:1000],
                 dashboard_id, json.dumps(detail) if detail is not None else None))
            return int(cur.lastrowid or 0)

    def activity_since(self, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if after_id:
                rows = conn.execute("SELECT * FROM activity_log WHERE id > ? ORDER BY id LIMIT ?",
                                    (after_id, limit)).fetchall()
            else:  # latest `limit`, oldest first
                rows = conn.execute("SELECT * FROM (SELECT * FROM activity_log ORDER BY id DESC LIMIT ?) "
                                    "ORDER BY id", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"]) if d["detail"] else None
            out.append(d)
        return out

    def change_marker(self) -> tuple[int, str]:
        """(latest activity id, dashboards signature). Cheap; polled by the web app's SSE loop."""
        with self._conn() as conn:
            act = conn.execute("SELECT COALESCE(MAX(id), 0) FROM activity_log").fetchone()[0]
            sig = conn.execute("SELECT COALESCE(group_concat(id || ':' || version, ','), '') FROM "
                               "(SELECT id, version FROM dashboards ORDER BY id)").fetchone()[0]
        return int(act), str(sig)


def main(argv: list[str] | None = None) -> int:
    """`python -m hearthly.state --reset` clears dashboards and the activity feed before a class."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m hearthly.state")
    parser.add_argument("--reset", action="store_true", help="delete all dashboards and activity")
    parser.add_argument("--keep-activity", action="store_true", help="with --reset: keep the activity feed")
    args = parser.parse_args(argv)
    store = StateStore()
    if args.reset:
        store.reset(keep_activity=args.keep_activity)
        print(f"Cleared dashboards{'' if args.keep_activity else ' and activity'} in {store.path}")
    else:
        for d in store.list_dashboards():
            print(f"{d['id']:<28} v{d['version']:<3} {d['panels']} panels  {d['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
