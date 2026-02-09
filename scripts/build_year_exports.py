#!/usr/bin/env python3
"""Build grouped markdown exports from per-page OCR markdown.

Default behavior:
- Try to group by date (AUTO).
- If dates are not sufficiently detectable, fall back to page-based grouping.

This script is intentionally thin; date parsing/heuristics live in msjournal_reader.date.

Inputs:
- <exports-base>/<doc>/page_*.md

Outputs:
- Date-grouped: <out-dir>/journal-YYYY.md
- Page-grouped fallback: <out-dir>/journal-pages-<doc>.md

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

from msjournal_reader.date.assign import Page, assign_dates, auto_detect_date_mode
from msjournal_reader.date.types import DatePolicy

PAGE_NUM_RE = re.compile(r"(?:page|pdfpage)_(\d{4})")


def _read_page_markdown(p: Path) -> str:
    """Read per-page markdown and return the OCR text body (best-effort)."""
    md = p.read_text(encoding="utf-8", errors="replace").strip()
    if not md:
        return ""

    # Our exporter writes:
    #   # Page N\n\n<ocr text>
    # Strip the first markdown heading if present.
    lines = md.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        # drop first line and leading blank lines
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest = rest[1:]
        return "\n".join(rest).strip()
    return md


@dataclass(frozen=True)
class Entry:
    key: str  # date isoformat or page label
    sort_key: tuple
    doc: str
    page: int
    text: str


def iter_doc_pages(doc_dir: Path) -> list[Page]:
    pages: list[Page] = []
    for p in sorted(doc_dir.glob("*.md")):
        if p.name == "combined.md":
            continue
        m = PAGE_NUM_RE.search(p.stem)
        page_num = int(m.group(1)) if m else 0
        text = _read_page_markdown(p)
        if not text:
            continue
        pages.append(Page(doc=doc_dir.name, page=page_num, path=p, text=text))
    return pages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--group-by", choices=["auto", "date", "page"], default="auto")
    ap.add_argument("--include-source", action="store_true")
    ap.add_argument(
        "--fill-missing-days",
        action="store_true",
        help="In date-grouped mode, insert placeholder headings for missing days within each year.",
    )
    ap.add_argument("--min-year", type=int, default=None, help="Ignore assigned dates earlier than this year")
    ap.add_argument("--max-year", type=int, default=None, help="Ignore assigned dates later than this year")

    # Date-policy knobs (optional)
    ap.add_argument("--no-date-repair", action="store_true")
    ap.add_argument("--no-infer-continuations", action="store_true")
    ap.add_argument("--auto-min-hits", type=int, default=3)
    ap.add_argument("--auto-scan-pages", type=int, default=20)

    args = ap.parse_args()

    exports_base = Path(args.exports_base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    policy = DatePolicy(
        allow_repair=not args.no_date_repair,
        allow_infer_continuations=not args.no_infer_continuations,
        auto_min_hits=int(args.auto_min_hits),
        auto_scan_pages=int(args.auto_scan_pages),
    )

    entries_by_year: dict[int, list[Entry]] = {}

    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        if doc_dir.name in {"yearly", "index"}:
            continue

        pages = iter_doc_pages(doc_dir)
        if not pages:
            continue

        # Heuristic: PDF-extracted docs are often sparse (only selected pages).
        # Disable chronology-based repair/inference to avoid "fixing" legitimate jumps.
        doc_policy = policy
        if doc_dir.name.endswith("-pdf"):
            doc_policy = DatePolicy(
                allow_repair=False,
                allow_infer_continuations=False,
                auto_min_hits=policy.auto_min_hits,
                auto_scan_pages=policy.auto_scan_pages,
            )

        mode = args.group_by
        if mode == "auto":
            mode = "date" if auto_detect_date_mode(pages, doc_policy) else "page"

        if mode == "page":
            # Emit a page-grouped doc export.
            out_path = out_dir / f"journal-pages-{doc_dir.name}.md"
            parts: list[str] = [f"# Journal Pages — {doc_dir.name}\n"]
            for p in pages:
                parts.append(f"\n## Page {p.page:04d}\n")
                if args.include_source:
                    parts.append(f"\n### ({doc_dir.name}/{p.path.name})\n")
                parts.append(p.text.rstrip() + "\n")
            out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
            print(f"OK: wrote {out_path} ({len(pages)} pages)")
            continue

        # Date-grouped mode
        assigns = assign_dates(pages, doc_policy)

        # Decide if this doc actually has usable dates (forced mode may still fail).
        if not any(a.d is not None for a in assigns):
            out_path = out_dir / f"journal-pages-{doc_dir.name}.md"
            parts = [f"# Journal Pages — {doc_dir.name}\n", "\n*(date grouping requested but no dates were parseable; falling back to pages)*\n"]
            for p in pages:
                parts.append(f"\n## Page {p.page:04d}\n")
                if args.include_source:
                    parts.append(f"\n### ({doc_dir.name}/{p.path.name})\n")
                parts.append(p.text.rstrip() + "\n")
            out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
            print(f"WARN: wrote {out_path} (no parseable dates)")
            continue

        for p, a in zip(pages, assigns):
            if not a.d:
                # If a page has no assigned date, keep it out of yearly exports;
                # it will still be searchable via the index.
                continue

            if args.min_year is not None and a.d.year < int(args.min_year):
                continue
            if args.max_year is not None and a.d.year > int(args.max_year):
                continue

            y = a.d.year
            entries_by_year.setdefault(y, []).append(
                Entry(
                    key=a.d.isoformat(),
                    sort_key=(a.d.isoformat(), p.page, p.doc),
                    doc=p.doc,
                    page=p.page,
                    text=p.text,
                )
            )

    # Write yearly exports.
    for year, items in sorted(entries_by_year.items()):
        items.sort(key=lambda e: e.sort_key)
        out_path = out_dir / f"journal-{year}.md"

        parts: list[str] = [f"# Journal {year}\n"]
        cur_day: str | None = None
        cur_date: date | None = None

        for e in items:
            d = date.fromisoformat(e.key)

            if args.fill_missing_days and cur_date is not None:
                dd = cur_date.fromordinal(cur_date.toordinal() + 1)
                while dd < d and dd.year == year:
                    parts.append(f"\n## {dd.isoformat()}\n")
                    parts.append("*(no entry parsed for this day)*\n")
                    dd = dd.fromordinal(dd.toordinal() + 1)

            if e.key != cur_day:
                parts.append(f"\n## {e.key}\n")
                cur_day = e.key
                cur_date = d

            if args.include_source:
                parts.append(f"\n### ({e.doc}/page_{e.page:04d}.md)\n")
            parts.append(e.text.rstrip() + "\n")

        if args.fill_missing_days and cur_date is not None and cur_date.year == year:
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
