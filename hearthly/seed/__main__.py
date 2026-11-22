"""Rebuild the Hearthly business database.

    python -m hearthly.seed --reset            # 18 months ending yesterday
    python -m hearthly.seed --reset --as-of 2026-11-22
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date

from .. import config
from .generator import HearthlyGenerator
from .secrets import write_secrets
from .writer import write_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hearthly.seed", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete and rebuild data/hearthly.db")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="treat this date as 'today' (data ends the day before). Default: today")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-secrets", action="store_true", help="skip regenerating docs/DEMO_SECRETS.md")
    args = parser.parse_args(argv)

    path = config.business_db_path()
    if path.exists() and not args.reset:
        print(f"{path} already exists; pass --reset to rebuild it.", file=sys.stderr)
        return 1
    as_of = args.as_of or date.today()
    t0 = time.perf_counter()
    dataset = HearthlyGenerator(as_of, seed=args.seed).build()
    write_database(dataset, path)
    conn = sqlite3.connect(path)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in dataset.rows}
    conn.close()
    print(f"Wrote {path} (as of {as_of}, data {dataset.timeline.start} .. {dataset.timeline.end}) "
          f"in {time.perf_counter() - t0:.1f}s")
    for t, n in counts.items():
        print(f"  {t:<16} {n:>8,}")
    if not args.no_secrets:
        out = write_secrets(path, dataset.timeline)
        print(f"Presenter notes: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
