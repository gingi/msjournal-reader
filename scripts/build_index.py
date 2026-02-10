#!/usr/bin/env python3
"""Build (or incrementally update) a lightweight search index over exported journal pages.

Philosophy:
- Canonical identity is (doc, page). This always exists.
- Dates are optional metadata (nullable) because some journals have no dates or different formats.

Inputs:
- <exports-base>/<doc>/page_XXXX.md

The index stores:
- pages: metadata per page (doc, page, path, mtime_ns, optional date)
- pages_fts: full-text search over content

Usage:
  PYTHONPATH=. python3 scripts/build_index.py \
    --exports-base "/c/.../exports/msjournal-reader" \
    --db "/c/.../exports/msjournal-reader/index/journal_index.sqlite"

Then query with scripts/query_index.py.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from msjournal_reader.date.parsers import parse_dow_month_day_year
from msjournal_reader.date.repair import candidate_to_date

PAGE_RE = re.compile(r"(?:page|pdfpage)_(\d{4})")
TIME_RE = re.compile(r"\b(?P<h>\d{1,2}):(?P<m>\d{2})\b")


@dataclass(frozen=True)
class Parsed:
    d: date | None
    time_key: int | None
    snippet: str


def parse_time_key(text: str) -> int | None:
    for line in text.splitlines()[:16]:
        m = TIME_RE.search(line)
        if m:
            return int(m.group("h")) * 60 + int(m.group("m"))
    return None


def make_snippet(text: str, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", text.strip())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _read_page_markdown(p: Path) -> str:
    md = p.read_text(encoding="utf-8", errors="replace").strip()
    if not md:
        return ""
    lines = md.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest = rest[1:]
        return "\n".join(rest).strip()
    return md


def parse(text: str, *, max_snippet_chars: int) -> Parsed:
    cand = parse_dow_month_day_year(text.splitlines()[:10])
    d = candidate_to_date(cand) if cand else None
    tk = parse_time_key(text)
    snip = make_snippet(text, max_snippet_chars)
    return Parsed(d=d, time_key=tk, snippet=snip)


def init_db(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
          path TEXT PRIMARY KEY,
          mtime_ns INTEGER NOT NULL,
          doc TEXT NOT NULL,
          page INTEGER NOT NULL,
          date TEXT,              -- nullable ISO date
          year INTEGER,           -- nullable
          time_key INTEGER NOT NULL,
          snippet TEXT NOT NULL
        );
        """
    )

    con.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
        USING fts5(path UNINDEXED, content);
        """
    )

    con.execute("CREATE INDEX IF NOT EXISTS idx_pages_doc_page ON pages(doc, page);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pages_date ON pages(date);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pages_year ON pages(year);")


def _schema_version_ok(con: sqlite3.Connection) -> bool:
    # Detect whether the existing 'pages' table has the nullable date column.
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(pages);").fetchall()]
    except sqlite3.OperationalError:
        return True
    want = {"path", "mtime_ns", "doc", "page", "date", "year", "time_key", "snippet"}
    return set(cols) >= want


def reset_db(con: sqlite3.Connection) -> None:
    con.execute("DROP TABLE IF EXISTS pages;")
    con.execute("DROP TABLE IF EXISTS pages_fts;")


def upsert(
    con: sqlite3.Connection,
    *,
    path: str,
    mtime_ns: int,
    parsed: Parsed,
    doc: str,
    page: int,
    content: str,
) -> None:
    con.execute(
        """
        INSERT INTO pages(path, mtime_ns, doc, page, date, year, time_key, snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          mtime_ns=excluded.mtime_ns,
          doc=excluded.doc,
          page=excluded.page,
          date=excluded.date,
          year=excluded.year,
          time_key=excluded.time_key,
          snippet=excluded.snippet;
        """,
        (
            path,
            int(mtime_ns),
            doc,
            int(page),
            parsed.d.isoformat() if parsed.d else None,
            int(parsed.d.year) if parsed.d else None,
            int(parsed.time_key) if parsed.time_key is not None else None,
            parsed.snippet,
        ),
    )

    con.execute("DELETE FROM pages_fts WHERE path = ?", (path,))
    con.execute("INSERT INTO pages_fts(path, content) VALUES (?, ?)", (path, content))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--max-snippet-chars", type=int, default=400)
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-parse and upsert all non-empty pages even if mtime_ns is unchanged.",
    )
    ap.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate tables before indexing.",
    )
    args = ap.parse_args()

    exports_base = Path(args.exports_base)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    updated = 0
    seen = 0

    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row

        if args.reset:
            reset_db(con)

        init_db(con)

        if not _schema_version_ok(con):
            reset_db(con)
            init_db(con)

        # Existing mtimes for incremental update
        existing: dict[str, int] = {}
        for r in con.execute("SELECT path, mtime_ns FROM pages;").fetchall():
            existing[str(r["path"])] = int(r["mtime_ns"])

        for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
            if doc_dir.name in {"yearly", "index"}:
                continue
            for page_path in sorted(doc_dir.glob("*.md")):
                if page_path.name == "combined.md":
                    continue
                try:
                    st = page_path.stat()
                except FileNotFoundError:
                    continue
                if st.st_size == 0:
                    continue

                content = _read_page_markdown(page_path)
                if not content:
                    continue

                m = PAGE_RE.search(page_path.stem)
                page_num = int(m.group(1)) if m else 0

                key = str(page_path.resolve())
                seen += 1

                if not args.force and key in existing and existing[key] == int(st.st_mtime_ns):
                    continue

                parsed = parse(content, max_snippet_chars=int(args.max_snippet_chars))
                upsert(
                    con,
                    path=key,
                    mtime_ns=int(st.st_mtime_ns),
                    parsed=parsed,
                    doc=doc_dir.name,
                    page=page_num,
                    content=content,
                )
                updated += 1

        # Delete records for files that no longer exist
        for path in list(existing.keys()):
            if not os.path.exists(path):
                con.execute("DELETE FROM pages WHERE path = ?", (path,))
                con.execute("DELETE FROM pages_fts WHERE path = ?", (path,))

        con.commit()

    print(f"OK: index at {db_path}")
    print(f"pages_total_seen={seen} updated={updated}")


if __name__ == "__main__":
    main()
