"""The read-only SQL guard must reject anything that is not a single SELECT."""

from __future__ import annotations

from pathlib import Path

import pytest

from hearthly import sqlguard
from hearthly.sqlguard import QueryError, run_select

REJECTED = [
    "INSERT INTO products (sku, name, category, unit_cost, list_price) VALUES ('x','x','x',1,1)",
    "UPDATE products SET list_price = 0",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "CREATE TABLE evil (x)",
    "ALTER TABLE orders ADD COLUMN x",
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
    "DETACH DATABASE main",
    "PRAGMA table_info(orders)",
    "PRAGMA writable_schema = ON",
    "VACUUM",
    "REINDEX",
    "BEGIN",
    "REPLACE INTO products VALUES (1,'x','x','x',1,1)",
    # multi-statement
    "SELECT 1; DROP TABLE orders",
    "SELECT 1; SELECT 2",
    "SELECT 1;\n-- harmless?\nDELETE FROM orders",
    "SELECT 1 ;/* gap */ PRAGMA query_only = OFF",
    # comment tricks
    "/* SELECT */ DROP TABLE orders",
    "-- SELECT\nDELETE FROM orders",
    "/* unterminated SELECT 1",
    "SELECT 1 /*",
    "SELECT 'unterminated",
    # CTE wrapping writes
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "WITH x AS (SELECT 1) INSERT INTO products SELECT * FROM products",
    # dangerous functions
    "SELECT load_extension('/tmp/evil')",
    "SELECT readfile('/etc/passwd')",
    "SELECT sqlite_compileoption_get(0)",
    "SELECT fts3_tokenizer('simple')",
    # pragma table-valued function
    "SELECT * FROM pragma_table_info('orders')",
    "SELECT * FROM pragma_database_list",
    "",
    "   ",
]


@pytest.mark.parametrize("sql", REJECTED)
def test_rejected(business_db: Path, sql: str) -> None:
    with pytest.raises(QueryError):
        run_select(sql)


ALLOWED = [
    "SELECT COUNT(*) FROM orders",
    "select count(*) from orders;",
    "  WITH t AS (SELECT order_date FROM orders) SELECT COUNT(*) FROM t",
    "SELECT ';' AS semi, 'DROP TABLE orders' AS text",
    "SELECT 1 -- trailing comment ; DROP TABLE x",
    "SELECT /* inline ; */ 1",
    "SELECT \"name\" FROM products WHERE name LIKE '%Kettle%'",
    "SELECT name FROM products WHERE name = 'D''Souza'",
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 5) SELECT SUM(i) FROM n",
    "SELECT strftime('%Y-%m', order_date) m, ROW_NUMBER() OVER (ORDER BY order_date) FROM orders LIMIT 3",
    "SELECT name FROM sqlite_master WHERE type = 'table'",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(business_db: Path, sql: str) -> None:
    res = run_select(sql, limit=5)
    assert res.columns


def test_write_is_impossible_even_past_lexer(business_db: Path) -> None:
    """Bypass the lexical check: the connection itself must refuse writes."""
    conn = sqlguard.connect_readonly()
    for stmt in ("DELETE FROM orders", "PRAGMA query_only = OFF", "ATTACH DATABASE ':memory:' AS m"):
        with pytest.raises(Exception):
            conn.execute(stmt)
    conn.set_authorizer(None)
    with pytest.raises(Exception):  # mode=ro + query_only still block it
        conn.execute("DELETE FROM orders")
    conn.close()


def test_row_cap_and_truncation(business_db: Path) -> None:
    res = run_select("SELECT id FROM orders", limit=10)
    assert res.row_count == 10 and res.truncated
    res = run_select("SELECT id FROM orders", limit=10_000_000)
    assert res.row_count == sqlguard.config.MAX_PANEL_ROWS and res.truncated


def test_timeout(business_db: Path) -> None:
    slow = ("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
            "SELECT COUNT(*) FROM n")
    with pytest.raises(QueryError, match="time limit"):
        run_select(slow, timeout=0.3)


def test_friendly_error_for_bad_column(business_db: Path) -> None:
    with pytest.raises(QueryError, match="describe_schema"):
        run_select("SELECT nope FROM orders")


def test_blob_and_values_are_json_safe(business_db: Path) -> None:
    res = run_select("SELECT x'00ff' AS b, 1.23456789123 AS f")
    assert res.rows[0][0] == "<blob 2 bytes>"
    assert isinstance(res.rows[0][1], float)
