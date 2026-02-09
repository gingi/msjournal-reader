#!/usr/bin/env python3
"""Build yearly markdown files from exported per-page OCR text.

Scans <exports-base>/<doc>/page_*.txt, parses a date header (e.g. "MONDAY, JANUARY 1, 2026"),
then writes one markdown per year in chronological order.

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
    doc: str
    page: str
    text: str


def _fix_date_by_dow(d: date, dow: str, *, max_delta_days: int = 3) -> date:
    """Heuristic: if the handwritten day-of-week doesn't match the numeric date,
    adjust to the nearest date within +/- max_delta_days that *does* match.

    This catches common human errors like writing "Monday" on a Tuesday and vice versa.
    """

    dow = dow.strip().lower()
    want = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }.get(dow)
    if want is None:
        return d

    if d.weekday() == want:
        return d

    candidates: list[tuple[int, date]] = []
    for delta in range(-max_delta_days, max_delta_days + 1):
        if delta == 0:
            continue
        dd = d.fromordinal(d.toordinal() + delta)
        if dd.weekday() == want:
            candidates.append((delta, dd))

    if not candidates:
        return d

    # Prefer the smallest absolute change; break ties by preferring the past (negative delta)
    candidates.sort(key=lambda x: (abs(x[0]), x[0] > 0))
    return candidates[0][1]


def parse_date(text: str) -> date | None:
    for line in text.splitlines()[:6]:
        m = DATE_LINE_RE.match(line.strip())
        if not m:
            continue
        y = int(m.group("year"))
        mo = MONTHS[m.group("month").lower()]
        da = int(m.group("day"))
        d = date(y, mo, da)
        d = _fix_date_by_dow(d, str(m.group("dow")))
        return d
    return None


def parse_time_key(text: str) -> int:
    for line in text.splitlines()[:16]:
        m = TIME_RE.search(line)
        if m:
            return int(m.group("h")) * 60 + int(m.group("m"))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--include-source", action="store_true")
    args = ap.parse_args()

    exports_base = Path(args.exports_base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries: list[Entry] = []

    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        if doc_dir.name in {"yearly", "index"}:
            continue
        for page_path in sorted(doc_dir.glob("page_*.txt")):
            if page_path.stat().st_size == 0:
                continue
            raw = page_path.read_text(encoding="utf-8", errors="replace").strip()
            if not raw or raw.lower().startswith("(see attached image"):
                continue

            d = parse_date(raw)
            if not d:
                continue
            tk = parse_time_key(raw)
            entries.append(Entry(d=d, t_key=tk, doc=doc_dir.name, page=page_path.stem, text=raw))

    if not entries:
        raise SystemExit("No entries found (no parseable dates).")

    by_year: dict[int, list[Entry]] = {}
    for e in entries:
        by_year.setdefault(e.d.year, []).append(e)

    for year, items in sorted(by_year.items()):
        items.sort(key=lambda e: (e.d.isoformat(), e.t_key, e.doc, e.page))
        out_path = out_dir / f"journal-{year}.md"

        parts: list[str] = [f"# Journal {year}\n"]
        cur_day: str | None = None

        for e in items:
            day = e.d.isoformat()
            if day != cur_day:
                parts.append(f"\n## {day}\n")
                cur_day = day
            if args.include_source:
                parts.append(f"\n### ({e.doc}/{e.page})\n")
            parts.append(e.text.rstrip() + "\n")

        out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
        print(f"OK: wrote {out_path} ({len(items)} entries)")


if __name__ == "__main__":
    main()
