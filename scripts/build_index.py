#!/usr/bin/env python3
"""Build (or incrementally update) a lightweight search index over exported journal text.

Goal: optimize agent-style querying without loading giant markdown files.

- Indexes per-page exported text files: <exports-base>/<doc>/page_XXXX.txt
- Extracts date (from the header), a time key (first HH:MM), and stores a short snippet.
- Stores an FTS (full-text search) table for quick keyword search.
- Stores metadata so you can filter by date range and jump back to the original file.

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

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

DATE_LINE_RE = re.compile(
    r"^(?P<dow>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)\s+"
    r"(?P<day>\d{1,2})\s*,?\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)

TIME_RE = re.compile(r"\b(?P<h>\d{1,2}):(?P<m>\d{2})\b")


@dataclass(frozen=True)
class Parsed:
    d: date
    time_key: int
    snippet: str


def parse_date(text: str) -> date | None:
    for line in text.splitlines()[:6]:
        m = DATE_LINE_RE.match(line.strip())
        if not m:
            continue
        y = int(m.group("year"))
        mo = MONTHS[m.group("month").lower()]
        da = int(m.group("day"))
        return date(y, mo, da)
    return None


def parse_time_key(text: str) -> int:
    for line in text.splitlines()[:16]:
        m = TIME_RE.search(line)
        if m:
            h = int(m.group("h"))
            mi = int(m.group("m"))
            return h * 60 + mi
    return 0


def make_snippet(text: str, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", text.strip())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def parse(text: str, *, max_snippet_chars: int) -> Parsed | None:
    d = parse_date(text)
    if not d:
        return None
    tk = parse_time_key(text)
    snip = make_snippet(text, max_snippet_chars)
    return Parsed(d=d, time_key=tk, snippet=snip)


def init_db(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
          path TEXT PRIMARY KEY,
          mtime_ns INTEGER NOT NULL,
          date TEXT NOT NULL,
          time_key INTEGER NOT NULL,
          year INTEGER NOT NULL,
          doc TEXT NOT NULL,
          page INTEGER NOT NULL,
          snippet TEXT NOT NULL
        );
        """
    )

    # FTS over full page content; store path so we can map back.
    con.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
        USING fts5(path UNINDEXED, content);
        """
    )

    con.execute("CREATE INDEX IF NOT EXISTS idx_pages_date ON pages(date);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pages_year ON pages(year);")


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
        INSERT INTO pages(path, mtime_ns, date, time_key, year, doc, page, snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          mtime_ns=excluded.mtime_ns,
          date=excluded.date,
          time_key=excluded.time_key,
          year=excluded.year,
          doc=excluded.doc,
          page=excluded.page,
          snippet=excluded.snippet;
        """,
        (
            path,
            int(mtime_ns),
            parsed.d.isoformat(),
            int(parsed.time_key),
            int(parsed.d.year),
            doc,
            int(page),
            parsed.snippet,
        ),
    )

    # Replace into FTS (delete then insert by path).
    con.execute("DELETE FROM pages_fts WHERE path = ?", (path,))
    con.execute("INSERT INTO pages_fts(path, content) VALUES (?, ?)", (path, content))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--max-snippet-chars", type=int, default=400)
    args = ap.parse_args()

    exports_base = Path(args.exports_base)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path))
    init_db(con)

    # Track paths present now so we can delete removed entries.
    seen_paths: set[str] = set()

    total = 0
    updated = 0

    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        if doc_dir.name in {"yearly", "index"}:
            continue

        for page_path in sorted(doc_dir.glob("page_*.txt")):
            pstr = str(page_path)
            seen_paths.add(pstr)
            st = page_path.stat()
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))

            # Determine if file is indexable
            indexable = True
            text = None
            parsed = None
            
            if st.st_size == 0:
                indexable = False
            else:
                text = page_path.read_text(encoding="utf-8", errors="replace").strip()
                if not text:
                    indexable = False
                else:
                    parsed = parse(text, max_snippet_chars=int(args.max_snippet_chars))
                    if not parsed:
                        indexable = False

            # If not indexable, delete any existing entries
            if not indexable:
                con.execute("DELETE FROM pages WHERE path = ?", (pstr,))
                con.execute("DELETE FROM pages_fts WHERE path = ?", (pstr,))
                continue

            row = con.execute("SELECT mtime_ns FROM pages WHERE path = ?", (pstr,)).fetchone()
            if row and int(row[0]) == mtime_ns:
                total += 1
                continue

            m = re.search(r"page_(\d{4})", page_path.stem)
            page_num = int(m.group(1)) if m else 0

            upsert(
                con,
                path=pstr,
                mtime_ns=mtime_ns,
                parsed=parsed,
                doc=doc_dir.name,
                page=page_num,
                content=text,
            )
            updated += 1
            total += 1

    # delete missing
    cur = con.execute("SELECT path FROM pages")
    to_delete = [r[0] for r in cur.fetchall() if r[0] not in seen_paths]
    for p in to_delete:
        con.execute("DELETE FROM pages WHERE path = ?", (p,))
        con.execute("DELETE FROM pages_fts WHERE path = ?", (p,))

    con.commit()
    con.close()

    print(f"OK: index at {db_path}")
    print(f"pages_total_seen={total} updated={updated} deleted={len(to_delete)}")


if __name__ == "__main__":
    main()
