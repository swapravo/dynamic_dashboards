"""Read-only, time-limited SQL execution against the business database.

Defence in depth:
1. The file is opened with a read-only URI (`mode=ro`) and `PRAGMA query_only=ON`.
2. A lexical pre-check strips comments/strings, then allows exactly one statement starting
   with SELECT or WITH.
3. A SQLite authorizer allows only reads, SELECT, recursive CTEs and an allowlist of pure
   functions. ATTACH, PRAGMA, writes, DDL and anything else are denied by SQLite itself.
4. A progress handler aborts any statement after QUERY_TIMEOUT_SECONDS.
5. Results are capped (fetchmany(limit + 1) → `truncated`).
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import config


class QueryError(ValueError):
    """A query was rejected or failed. The message is safe to show to the model and the user."""


ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "avg", "count", "group_concat", "string_agg", "max", "min", "sum", "total", "median",
    # window functions
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # scalar
    "abs", "coalesce", "ifnull", "iif", "if", "nullif", "instr", "length", "octet_length", "lower", "upper",
    "ltrim", "rtrim", "trim", "replace", "substr", "substring", "printf", "format", "round", "sign",
    "char", "unicode", "hex", "quote", "typeof", "likely", "unlikely", "likelihood", "like", "glob",
    "concat", "concat_ws", "random", "max_scalar", "min_scalar",
    # date & time
    "date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff",
    # math
    "ceil", "ceiling", "floor", "trunc", "sqrt", "pow", "power", "exp", "ln", "log", "log10", "log2",
    "mod", "pi", "acos", "asin", "atan", "atan2", "cos", "sin", "tan", "degrees", "radians",
    # json (read-only helpers)
    "json", "json_array", "json_object", "json_extract", "json_type", "json_valid", "json_group_array",
    "json_group_object", "json_array_length",
})

_LEAD_KEYWORD = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float
    row_limit: int
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]


# --------------------------------------------------------------------------- lexical checks


def strip_sql(sql: str) -> tuple[str, int]:
    """Return (sql with comments blanked and string contents removed, number of top-level ';').

    Raises QueryError on unterminated strings/comments. A trailing ';' followed only by
    whitespace is allowed and not counted.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    statements_ended = 0
    pending_semicolon = False
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
            continue
        if ch == "/" and nxt == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                raise QueryError("Unterminated /* comment. Remove comments and send a single SELECT statement.")
            i = j + 2
            out.append(" ")
            continue
        if ch in ("'", '"', "`", "["):
            close = "]" if ch == "[" else ch
            j = i + 1
            while True:
                j = sql.find(close, j)
                if j == -1:
                    raise QueryError("Unterminated quoted string or identifier.")
                if close != "]" and j + 1 < n and sql[j + 1] == close:  # doubled quote escape
                    j += 2
                    continue
                break
            if pending_semicolon:
                statements_ended += 1
                pending_semicolon = False
            out.append(ch + "x" + close)  # keep a placeholder token, drop contents
            i = j + 1
            continue
        if ch == ";":
            pending_semicolon = True
            out.append(" ")
            i += 1
            continue
        if pending_semicolon and not ch.isspace():
            statements_ended += 1
            pending_semicolon = False
        out.append(ch)
        i += 1
    return "".join(out), statements_ended


def check_select_only(sql: str) -> str:
    """Validate that `sql` is a single SELECT/WITH statement. Returns the SQL without a trailing ';'."""
    if not sql or not sql.strip():
        raise QueryError("Empty query. Send one SELECT statement.")
    if "\x00" in sql:
        raise QueryError("Query contains a NUL byte.")
    stripped, extra_statements = strip_sql(sql)
    if extra_statements:
        raise QueryError("Only one statement is allowed per call. Remove the ';' and anything after it.")
    if not _LEAD_KEYWORD.match(stripped):
        first = stripped.strip().split(None, 1)[0].upper() if stripped.strip() else ""
        raise QueryError(
            f"Only read-only SELECT queries are allowed (got '{first}'). Start the query with SELECT or WITH.")
    return sql.strip().rstrip(";").rstrip()


# --------------------------------------------------------------------------- connection


def _authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        name = (arg2 or "").lower()
        return sqlite3.SQLITE_OK if name in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.business_db_path())
    if not path.exists():
        raise QueryError(f"Business database not found at {path}. Run: python -m hearthly.seed --reset")
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_authorizer)
    return conn


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<blob {len(bytes(value))} bytes>"
    if isinstance(value, float):
        return round(value, 6)
    return value


def _friendly(err: sqlite3.Error, timed_out: bool) -> QueryError:
    msg = str(err)
    if timed_out or "interrupted" in msg:
        return QueryError(
            f"Query exceeded the {config.QUERY_TIMEOUT_SECONDS:g}s time limit. Aggregate earlier, filter by date, "
            "or avoid cross joins.")
    if "not authorized" in msg or "prohibited" in msg:
        return QueryError(
            "Query rejected by the read-only guard: only SELECT over existing tables and standard read-only "
            "functions is allowed (no PRAGMA, ATTACH, writes or extension functions).")
    if "no such column" in msg or "no such table" in msg:
        return QueryError(f"{msg}. Call describe_schema to see exact table and column names.")
    if "one statement at a time" in msg:
        return QueryError("Only one statement is allowed per call.")
    return QueryError(f"SQLite error: {msg}")


def run_select(sql: str, limit: int = config.MAX_QUERY_ROWS, *, hard_cap: int = config.MAX_PANEL_ROWS,
               timeout: float = config.QUERY_TIMEOUT_SECONDS, db_path: Path | None = None) -> QueryResult:
    """Run one read-only SELECT and return at most `limit` rows."""
    clean = check_select_only(sql)
    limit = max(1, min(int(limit), hard_cap))
    conn = connect_readonly(db_path)
    deadline = time.monotonic() + timeout
    state = {"timed_out": False}

    def progress() -> int:
        if time.monotonic() > deadline:
            state["timed_out"] = True
            return 1
        return 0

    conn.set_progress_handler(progress, 10_000)
    t0 = time.perf_counter()
    try:
        cur = conn.execute(clean)
        columns = [d[0] for d in (cur.description or [])]
        raw = cur.fetchmany(limit + 1)
    except sqlite3.Error as err:
        raise _friendly(err, state["timed_out"]) from None
    finally:
        conn.close()
    elapsed = (time.perf_counter() - t0) * 1000
    truncated = len(raw) > limit
    rows = [[_jsonable(v) for v in r] for r in raw[:limit]]
    return QueryResult(clean, columns, rows, truncated, elapsed, limit)
