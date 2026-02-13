#!/usr/bin/env python3
"""Query the journal FTS index.

Usage:
  python3 scripts/query_index.py --db /path/to/journal_index.sqlite --q "october 7" --limit 10
  python3 scripts/query_index.py --db ... --q "taxes" --from 2025-12-01 --to 2025-12-31
"""

from __future__ import annotations

import argparse
import re
import sqlite3


def _coerce_db_path(p: str) -> str:
    """Accept either WSL paths (/c/...) or Windows paths (C:\\...)."""
    m = re.match(r"^([A-Za-z]):\\(.*)$", p)
    if not m:
        return p
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return f"/{drive}/{rest}"


def _coerce_fts_query(q: str) -> str:
    """Heuristic guardrail for common non-FTS inputs (especially file paths).

    SQLite FTS5 MATCH has its own query language; unescaped characters like '/'
    in a path can raise: `fts5: syntax error near "/"`.

    If it *looks* like a path, treat it as a literal phrase.
    """
    if ("/" in q or "\\" in q) and '"' not in q:
        return f'"{q}"'
    return q


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--q", required=True, help="FTS query")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    args = ap.parse_args()

    db_path = _coerce_db_path(args.db)
    q = _coerce_fts_query(args.q)

    con = sqlite3.connect(db_path)

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
        "SELECT p.date, p.doc, p.page, p.path, p.snippet "
        "FROM pages_fts f "
        "JOIN pages p ON p.path = f.path "
        "WHERE pages_fts MATCH ?" + where_sql + " "
        "ORDER BY p.date ASC, p.doc ASC, p.page ASC "
        "LIMIT ?"
    )

    qparams: list[object] = [q] + params + [int(args.limit)]

    rows = con.execute(sql, qparams).fetchall()
    for r in rows:
        d, doc, page, path, snip = r
        print(f"{d} {doc}/page_{int(page):04d} :: {snip}")
        print(f"  {path}")

    con.close()


if __name__ == "__main__":
    main()
