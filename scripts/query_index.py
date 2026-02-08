#!/usr/bin/env python3
"""Query the journal FTS index.

Usage:
  python3 scripts/query_index.py --db /path/to/journal_index.sqlite --q "october 7" --limit 10
  python3 scripts/query_index.py --db ... --q "taxes" --from 2025-12-01 --to 2025-12-31
"""

from __future__ import annotations

import argparse
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--q", required=True, help="FTS query")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)

    where = []
    params: list[object] = []

    if args.date_from:
        where.append("p.date >= ?")
        params.append(args.date_from)
    if args.date_to:
        where.append("p.date <= ?")
        params.append(args.date_to)

    where_sql = (" AND " + " AND ".join(where)) if where else ""

    sql = (
        "SELECT p.date, p.time_key, p.doc, p.page, p.path, p.snippet "
        "FROM pages_fts f "
        "JOIN pages p ON p.path = f.path "
        "WHERE pages_fts MATCH ?" + where_sql + " "
        "ORDER BY p.date ASC, p.time_key ASC "
        "LIMIT ?"
    )

    qparams: list[object] = [args.q] + params + [int(args.limit)]

    rows = con.execute(sql, qparams).fetchall()
    for r in rows:
        d, tk, doc, page, path, snip = r
        hh = int(tk) // 60
        mm = int(tk) % 60
        t = f"{hh:02d}:{mm:02d}" if tk else "--:--"
        print(f"{d} {t} {doc}/page_{int(page):04d} :: {snip}")
        print(f"  {path}")

    con.close()


if __name__ == "__main__":
    main()
