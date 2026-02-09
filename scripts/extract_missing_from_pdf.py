#!/usr/bin/env python3
"""Extract missing journal entries from a PDF export.

This is a pragmatic fallback when the original .ink export is missing pages.

- Renders each PDF page to a PNG
- Runs OCR (Azure Vision Read via msjournal-reader engine)
- Applies corrections
- Parses the handwritten date header
- Writes per-page outputs only for *target dates* (e.g., missing days)

Provenance:
- Writes a sidecar JSON per exported page recording the source PDF page index
  and a sha256 of the rendered PNG bytes.

Usage:
  # Example: fill July 2025 gaps
  source /path/to/azure.env
  PYTHONPATH=. python3 scripts/extract_missing_from_pdf.py \
    --pdf "/c/.../Journal - Jan 2025-July 2025.pdf" \
    --exports-base "/c/.../exports/msjournal-reader" \
    --doc "journal-jan-2025-july-2025-pdf" \
    --target-year 2025 --target-month 7

Optional:
  --missing-from-yearly "/c/.../yearly/journal-2025.md"  (auto-target missing days)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import fitz  # PyMuPDF

from msjournal_reader.corrections import apply_corrections
from msjournal_reader.ocr.registry import build_engine


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

# More permissive than the yearly builder: OCR often mangles months (e.g. "Julz").
DATE_LINE_RE = re.compile(
    r"^(?P<dow>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s+"
    r"(?P<month>[a-zA-Z]{3,12})\s+"
    r"(?P<day>\d{1,2})\s*,?\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)


def _month_token_to_int(tok: str) -> int | None:
    tok = tok.strip().lower()
    if not tok:
        return None
    # normalize common OCR confusions
    tok = tok.replace("|", "l")
    tok = re.sub(r"[^a-z]", "", tok)
    if len(tok) >= 3:
        pref = tok[:3]
        for name, num in MONTHS.items():
            if name.startswith(pref):
                return num
    return MONTHS.get(tok)


def parse_date(text: str) -> date | None:
    lines = [ln.strip() for ln in text.splitlines()[:12] if ln.strip()]

    # Azure OCR sometimes splits: "FRIDAY"\n"JANUARY 10, 2025"
    if len(lines) >= 2:
        if re.fullmatch(r"(?i)(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", lines[0]):
            stitched = f"{lines[0]} {lines[1]}"
            m = DATE_LINE_RE.match(stitched)
            if m:
                y = int(m.group("year"))
                mo = _month_token_to_int(m.group("month"))
                da = int(m.group("day"))
                if mo:
                    try:
                        return date(y, mo, da)
                    except ValueError:
                        return None

    for line in lines:
        m = DATE_LINE_RE.match(line)
        if not m:
            continue
        y = int(m.group("year"))
        mo = _month_token_to_int(m.group("month"))
        da = int(m.group("day"))
        if not mo:
            continue
        try:
            return date(y, mo, da)
        except ValueError:
            return None
    return None


def iter_missing_dates_from_yearly(yearly_md: Path, year: int) -> set[str]:
    text = yearly_md.read_text(encoding="utf-8", errors="replace")
    found = set(re.findall(rf"^(?:#{{1,6}})\s*({year}-\d{{2}}-\d{{2}})\b", text, flags=re.M))
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    missing: set[str] = set()
    d = start
    while d <= end:
        s = d.isoformat()
        if s not in found:
            missing.add(s)
        d += timedelta(days=1)
    return missing


@dataclass
class Provenance:
    source_pdf: str
    pdf_page_index: int
    rendered_png_sha256: str


def render_page_png_bytes(doc: fitz.Document, page_index: int, *, dpi: int) -> bytes:
    page = doc.load_page(page_index)
    # 72 dpi is default; scale to requested dpi
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


def write_outputs(doc_out: Path, stem: str, text: str, prov: Provenance) -> None:
    (doc_out / f"{stem}.txt").write_text(text, encoding="utf-8")
    (doc_out / f"{stem}.md").write_text(f"# {stem}\n\n{text}\n", encoding="utf-8")
    (doc_out / f"{stem}.provenance.json").write_text(json.dumps(asdict(prov), indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--doc", required=True, help="Output doc directory name under exports-base")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--start-page", type=int, default=0, help="0-based PDF page index to start from")
    ap.add_argument("--end-page", type=int, default=None, help="0-based PDF page index to stop at (inclusive)")

    ap.add_argument("--corrections-map", default=None)

    ap.add_argument("--target-year", type=int, default=None)
    ap.add_argument("--target-month", type=int, default=None)

    ap.add_argument("--missing-from-yearly", default=None, help="Path to yearly markdown to compute missing dates")

    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    exports_base = Path(args.exports_base).expanduser().resolve()
    doc_out = exports_base / args.doc

    if not pdf_path.exists():
        raise SystemExit(f"Missing PDF: {pdf_path}")

    corr_path = Path(args.corrections_map).expanduser().resolve() if args.corrections_map else None

    engine = build_engine("azure")

    target_missing: set[str] | None = None
    if args.missing_from_yearly:
        y = args.target_year
        if not y:
            raise SystemExit("--missing-from-yearly requires --target-year")
        target_missing = iter_missing_dates_from_yearly(Path(args.missing_from_yearly), y)

    exports_base.mkdir(parents=True, exist_ok=True)
    doc_out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    total = doc.page_count

    start = max(0, int(args.start_page))
    end = int(args.end_page) if args.end_page is not None else (total - 1)
    end = min(end, total - 1)
    if start > end:
        raise SystemExit(f"Invalid page range: start={start} end={end} (doc pages={total})")

    kept = 0
    seen_dates: set[str] = set()

    for i in range(start, end + 1):
        png = render_page_png_bytes(doc, i, dpi=args.dpi)
        sha = hashlib.sha256(png).hexdigest()

        text = engine.ocr_png_bytes(png)
        text = apply_corrections(text, corr_path)
        d = parse_date(text)
        if not d:
            continue
        if d.year < 2024:
            continue

        if args.target_year and d.year != args.target_year:
            continue
        if args.target_month and d.month != args.target_month:
            continue

        ds = d.isoformat()
        if target_missing is not None and ds not in target_missing:
            continue

        stem = f"pdfpage_{i:04d}__{ds}"
        prov = Provenance(source_pdf=str(pdf_path), pdf_page_index=i, rendered_png_sha256=sha)
        write_outputs(doc_out, stem, text, prov)
        kept += 1
        seen_dates.add(ds)
        print(f"KEEP {ds} (pdf page {i})")

    doc.close()
    print(f"DONE: kept={kept} pages (unique_dates={len(seen_dates)}) into {doc_out}")


if __name__ == "__main__":
    main()
