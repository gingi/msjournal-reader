#!/usr/bin/env python3
"""Incrementally export Microsoft Journal .ink files and rebuild yearly markdown.

This avoids re-OCRing everything nightly by skipping pages already exported.

Config is expected to be per-user and should live under user_corrections/local/.

Usage:
  # example
  PYTHONPATH=. python3 scripts/update_exports.py \
    --config user_corrections/local/journals.json \
    --exports-base "/c/.../exports/msjournal-reader" \
    --yearly-out "/c/.../exports/msjournal-reader/yearly"
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from msjournal_reader.corrections import apply_corrections
from msjournal_reader.ink import PNG_MAGIC
from msjournal_reader.ocr.registry import build_engine


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


@dataclass(frozen=True)
class JournalCfg:
    path: Path


def load_config(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def iter_pages(ink_path: Path):
    con = sqlite3.connect(str(ink_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT id, page_order FROM pages ORDER BY page_order")
    for row in cur.fetchall():
        yield row["id"], int(row["page_order"])

    con.close()


def get_png_blob(ink_path: Path, page_id: bytes) -> bytes | None:
    con = sqlite3.connect(str(ink_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT bytes FROM blobs WHERE owner_id = ? AND ordinal = 0", (page_id,))
    r = cur.fetchone()
    con.close()
    if not r or r[0] is None:
        return None
    b = bytes(r[0])
    if b[:8] != PNG_MAGIC:
        return None
    return b


def write_outputs(doc_out: Path, page_order: int, text: str) -> None:
    page_txt = doc_out / f"page_{page_order:04d}.txt"
    page_md = doc_out / f"page_{page_order:04d}.md"

    page_txt.write_text(text, encoding="utf-8")
    page_md.write_text(f"# Page {page_order}\n\n{text}\n", encoding="utf-8")


def rebuild_combined(doc_out: Path) -> None:
    parts_txt: list[str] = []
    parts_md: list[str] = []

    for p in sorted(doc_out.glob("page_*.txt")):
        t = p.read_text(encoding="utf-8", errors="replace").strip()
        if not t:
            continue
        m = re.search(r"page_(\d{4})", p.stem)
        page = int(m.group(1)) if m else 0
        parts_txt.append(t)
        parts_md.append(f"# Page {page}\n\n{t}\n")

    (doc_out / "combined.txt").write_text("\n\n".join(parts_txt).strip() + "\n", encoding="utf-8")
    (doc_out / "combined.md").write_text("\n".join(parts_md).strip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--yearly-out", required=True)
    args = ap.parse_args()

    cfg_path = Path(args.config)
    exports_base = Path(args.exports_base)
    yearly_out = Path(args.yearly_out)

    cfg = load_config(cfg_path)
    journals = [Path(x) for x in (cfg.get("journals") or [])]
    if not journals:
        raise SystemExit("Config has no journals[]")

    corrections_map = cfg.get("corrections_map")
    corr_path = Path(corrections_map).expanduser().resolve() if corrections_map else None

    engine = build_engine("azure", azure_language=str(cfg.get("azure_language", "en")), azure_timeout_s=int(cfg.get("azure_timeout_s", 180)))

    exports_base.mkdir(parents=True, exist_ok=True)

    total_new = 0

    for ink in journals:
        ink = ink.expanduser().resolve()
        if not ink.exists():
            print(f"SKIP missing: {ink}")
            continue

        doc_out = exports_base / slug(ink.stem)
        doc_out.mkdir(parents=True, exist_ok=True)

        for page_id, page_order in iter_pages(ink):
            out_txt = doc_out / f"page_{page_order:04d}.txt"
            if out_txt.exists() and out_txt.stat().st_size > 0:
                continue

            png = get_png_blob(ink, page_id)
            if not png:
                # still create empty file to avoid rework
                out_txt.write_text("", encoding="utf-8")
                continue

            text = engine.ocr_png_bytes(png)
            text = apply_corrections(text, corr_path)

            write_outputs(doc_out, page_order, text)
            total_new += 1
            print(f"OK {ink.name}: page {page_order:04d}")

        rebuild_combined(doc_out)

    # rebuild year files
    import runpy
    import sys

    sys.argv = [
        "build_year_exports.py",
        "--exports-base",
        str(exports_base),
        "--out-dir",
        str(yearly_out),
    ]
    runpy.run_path(str(Path(__file__).resolve().parent / "build_year_exports.py"), run_name="__main__")

    print(f"DONE: exported new_pages={total_new}")


if __name__ == "__main__":
    main()
