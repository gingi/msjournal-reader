#!/usr/bin/env python3
"""Export the rendered PNG for a given journal doc+page.

This lets the chat workflow send the handwriting image on demand.

It maps a doc slug (exports folder name) back to the source .ink file by
slug(ink.stem) using the same slug() logic as scripts/update_exports.py.

Example:
  python3 scripts/export_page_png.py \
    --config user_corrections/local/journals.json \
    --doc "journal-feb-2026" \
    --page 12 \
    --out /tmp/page.png
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from msjournal_reader.ink import extract_pages_png


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


def load_config(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--doc", required=True, help="Doc slug (exports folder name, e.g. journal-feb-2026)")
    ap.add_argument("--page", required=True, type=int, help="Page order number")
    ap.add_argument("--out", required=True, help="Output PNG path")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path

    cfg = load_config(cfg_path)
    journals = [Path(x).expanduser().resolve() for x in (cfg.get("journals") or [])]
    if not journals:
        raise SystemExit("Config has no journals[]")

    doc = str(args.doc).strip()
    ink_path = None
    for j in journals:
        if slug(j.stem) == doc:
            ink_path = j
            break
    if ink_path is None:
        raise SystemExit(f"No .ink matched doc slug={doc}. Check config journals[]")

    pages = extract_pages_png(ink_path)
    wanted = int(args.page)
    hit = None
    for p in pages:
        if int(p.order) == wanted:
            hit = p
            break
    if hit is None:
        raise SystemExit(f"Page {wanted} not found in {ink_path}")

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(hit.png_bytes)
    print(str(out_path))


if __name__ == "__main__":
    main()
