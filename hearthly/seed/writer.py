"""Write a generated Dataset into a fresh SQLite file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .generator import Dataset
from .schema import SCHEMA_SQL, TABLE_ORDER


def write_database(dataset: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    for p in (tmp, Path(f"{tmp}-journal")):
        p.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA_SQL)
        with conn:
            for table in TABLE_ORDER:
                rows = dataset.rows[table]
                if not rows:
                    continue
                placeholders = ",".join("?" * len(rows[0]))
                conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        conn.execute("ANALYZE")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"foreign key violations: {fk_errors[:5]}")
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    tmp.replace(path)
