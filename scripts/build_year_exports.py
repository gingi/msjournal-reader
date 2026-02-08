#!/usr/bin/env python3
"""Build yearly markdown files from exported per-page OCR text.

This scans an export base directory (produced by scripts/ink_to_text.py) and groups
pages by detected entry date (YYYY-MM-DD). It then writes one markdown file per year.

It is intentionally conservative:
- skips empty pages
- skips pages with no parseable date header

Usage:
  PYTHONPATH=. python3 scripts/build_year_exports.py \
    --exports-base "/c/.../exports/msjournal-reader" \
    --out-dir "/c/.../exports/msjournal-reader/yearly"
"""

from __future__ import annotations

import argparse
import re
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
class Entry:
    d: date
    t_key: int
    source: str
    page: str
    text: str


def parse_date(text: str) -> date | None:
    for line in text.splitlines()[:5]:
        m = DATE_LINE_RE.match(line.strip())
        if not m:
            continue
        y = int(m.group("year"))
        mo = MONTHS[m.group("month").lower()]
        da = int(m.group("day"))
        return date(y, mo, da)
    return None


def parse_time_key(text: str) -> int:
    # Try to find a time in the first ~10 lines to order multiple entries per day.
    for line in text.splitlines()[:12]:
        m = TIME_RE.search(line)
        if m:
            h = int(m.group("h"))
            mi = int(m.group("m"))
            return h * 60 + mi
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--include-source", action="store_true", help="Include source folder/page id headings")
    args = ap.parse_args()

    exports_base = Path(args.exports_base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries: list[Entry] = []

    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        # skip internal outputs
        if doc_dir.name in {"yearly"}:
            continue
        for page_path in sorted(doc_dir.glob("page_*.txt")):
            raw = page_path.read_text(encoding="utf-8", errors="replace")
            txt = raw.strip()
            if not txt:
                continue
            if txt.lower().startswith("(see attached image"):
                continue

            d = parse_date(txt)
            if not d:
                continue
            t_key = parse_time_key(txt)

            page = page_path.stem  # page_0001
            entries.append(Entry(d=d, t_key=t_key, source=doc_dir.name, page=page, text=txt))

    if not entries:
        raise SystemExit("No entries found (no parseable dates).")

    # group by year
    by_year: dict[int, list[Entry]] = {}
    for e in entries:
        by_year.setdefault(e.d.year, []).append(e)

    for year, items in sorted(by_year.items()):
        items.sort(key=lambda e: (e.d.isoformat(), e.t_key, e.source, e.page))
        out_path = out_dir / f"journal-{year}.md"

        parts: list[str] = [f"# Journal {year}\n"]
        cur_day: str | None = None

        for e in items:
            day = e.d.isoformat()
            if day != cur_day:
                parts.append(f"\n## {day}\n")
                cur_day = day

            if args.include_source:
                parts.append(f"\n### ({e.source}/{e.page})\n")

            parts.append(e.text.rstrip() + "\n")

        out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
        print(f"OK: wrote {out_path} ({len(items)} entries)")


if __name__ == "__main__":
    main()
