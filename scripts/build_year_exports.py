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

# OCR sometimes mangles month names (e.g. "Julz"); be permissive here.
DATE_LINE_RE = re.compile(
    r"^(?P<dow>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s+"
    r"(?P<month>[a-zA-Z]{3,12})\s+"
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


def _month_token_to_int(tok: str) -> int | None:
    tok = tok.strip().lower()
    if not tok:
        return None
    tok = tok.replace("|", "l")
    tok = re.sub(r"[^a-z]", "", tok)
    if len(tok) >= 3:
        pref = tok[:3]
        for name, num in MONTHS.items():
            if name.startswith(pref):
                return num
    return MONTHS.get(tok)


def _parse_date_match(text: str) -> re.Match[str] | None:
    """Return a regex match for the first plausible date header near the top."""
    lines = [ln.strip() for ln in text.splitlines()[:10] if ln.strip()]

    # Common Azure OCR quirk: split the date header across two lines, e.g.
    #   "FRIDAY"\n"JANUARY 10, 2025"
    # Try to stitch that back together.
    if len(lines) >= 2 and re.fullmatch(
        r"(?i)(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s*",
        lines[0],
    ):
        stitched = f"{lines[0]} {lines[1]}"
        m = DATE_LINE_RE.match(stitched)
        if m:
            return m

    for line in lines:
        m = DATE_LINE_RE.match(line)
        if m:
            return m
    return None


def parse_date(text: str) -> date | None:
    m = _parse_date_match(text)
    if not m:
        return None

    y = int(m.group("year"))
    mo = _month_token_to_int(str(m.group("month")))
    if not mo:
        return None
    da = int(m.group("day"))
    d = date(y, mo, da)
    d = _fix_date_by_dow(d, str(m.group("dow")))
    return d


def infer_date_from_context(text: str, prev: date) -> date | None:
    """Infer the intended date for the current page using chronology.

    Fixes common OCR mistakes in date headers, including:
    - Month token wrong (e.g. JANUARY → JUNE)
    - Day-of-month missing a digit (e.g. 27 → 7)

    Approach:
    - Parse (dow, month_token, day_token, year)
    - Look for a date near (prev + 1 day) with the same weekday.
    - Prefer candidates whose month matches the parsed month (if parseable)
      and whose day-of-month "looks like" the OCR day token.
    """

    m = _parse_date_match(text)
    if not m:
        return None

    y = int(m.group("year"))
    day_tok = str(m.group("day")).strip()
    try:
        ocr_day = int(day_tok)
    except Exception:
        return None

    dow = str(m.group("dow")).strip().lower()
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
        return None

    parsed_month = _month_token_to_int(str(m.group("month")))

    target = prev.fromordinal(prev.toordinal() + 1)

    # Search a tight window around the expected next day.
    # (Widening too much risks "correcting" valid jumps.)
    window = 14

    best: tuple[float, date] | None = None
    for delta in range(-window, window + 1):
        cand = target.fromordinal(target.toordinal() + delta)
        if cand.year != y:
            continue
        if cand.weekday() != want:
            continue

        score = abs(delta)

        # Prefer matching month (if we could parse it).
        if parsed_month is not None and cand.month != parsed_month:
            score += 3.0

        # Prefer day numbers that resemble the OCR token (handles 27→7, 10→1, etc.).
        cand_day_s = str(cand.day)
        if cand.day != ocr_day:
            if cand_day_s.endswith(str(ocr_day)):
                score += 0.5
            else:
                score += 2.0

        if best is None or score < best[0]:
            best = (score, cand)

    if not best:
        return None

    score, cand = best
    # Only accept if it's plausibly close to the expected chronology.
    if abs((cand - target).days) <= 7:
        return cand
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

        # First pass: read pages and parse (best-effort) dates.
        prev_d: date | None = None
        pages: list[tuple[Path, str, date | None]] = []

        for page_path in sorted(doc_dir.glob("page_*.txt")):
            if page_path.stat().st_size == 0:
                continue
            raw = page_path.read_text(encoding="utf-8", errors="replace").strip()
            if not raw:
                continue

            d = parse_date(raw)
            if prev_d and d:
                # If the parsed date jumps vs the prior page within the same journal,
                # attempt a context-based repair (month/day token OCR mistakes).
                delta_days = (d - prev_d).days
                if delta_days < 0 or delta_days > 3:
                    inferred = infer_date_from_context(raw, prev_d)
                    if inferred:
                        d = inferred

            # Track chronology even if we later decide to skip the page.
            if d and d.year >= 2024:
                prev_d = d

            pages.append((page_path, raw, d))

        # Second pass: if some pages have no date header (or OCR failed),
        # assign them a date based on surrounding pages.
        known = [(i, d) for i, (_, _, d) in enumerate(pages) if d is not None]
        for k in range(len(known) - 1):
            i0, d0 = known[k]
            i1, d1 = known[k + 1]
            if i1 <= i0 + 1:
                continue
            gap_pages = list(range(i0 + 1, i1))
            gap_days = (d1 - d0).days

            if gap_days == 1:
                # Continuation pages for the same day.
                fill = d0
            elif gap_days == 2:
                # Exactly one missing day between two headers.
                fill = d0.fromordinal(d0.toordinal() + 1)
            else:
                continue

            for gi in gap_pages:
                pth, raw, _ = pages[gi]
                pages[gi] = (pth, raw, fill)

        # Trailing undated pages: treat as continuations of the last known date.
        if known:
            last_i, last_d = known[-1]
            for gi in range(last_i + 1, len(pages)):
                pth, raw, d = pages[gi]
                if d is None:
                    pages[gi] = (pth, raw, last_d)

        for page_path, raw, d in pages:
            if not d:
                continue
            # Guardrail: this dataset starts in 2024; anything earlier is a parsing/labeling error.
            if d.year < 2024:
                continue
            # Skip pure placeholders.
            if raw.lower().startswith("(see attached image"):
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
        cur_date: date | None = None

        for e in items:
            if cur_date is not None:
                # Fill missing days with a placeholder so each day exists in the yearly export.
                dd = cur_date.fromordinal(cur_date.toordinal() + 1)
                while dd < e.d and dd.year == year:
                    parts.append(f"\n## {dd.isoformat()}\n")
                    parts.append("*(no entry parsed for this day)*\n")
                    dd = dd.fromordinal(dd.toordinal() + 1)

            day = e.d.isoformat()
            if day != cur_day:
                parts.append(f"\n## {day}\n")
                cur_day = day
                cur_date = e.d

            if args.include_source:
                parts.append(f"\n### ({e.doc}/{e.page})\n")
            parts.append(e.text.rstrip() + "\n")

        # Also ensure we end the year with all days present.
        if cur_date is not None and cur_date.year == year:
            dd = cur_date.fromordinal(cur_date.toordinal() + 1)
            end = date(year, 12, 31)
            while dd <= end:
                parts.append(f"\n## {dd.isoformat()}\n")
                parts.append("*(no entry parsed for this day)*\n")
                dd = dd.fromordinal(dd.toordinal() + 1)

        out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
        print(f"OK: wrote {out_path} ({len(items)} entries)")


if __name__ == "__main__":
    main()
