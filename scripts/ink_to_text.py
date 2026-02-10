#!/usr/bin/env python3
"""Convert Microsoft Journal .ink files (SQLite) into text using OCR.

This repo currently implements Azure AI Vision Read.
The code is structured so additional providers can be added in msjournal_reader/ocr/.

Usage:
  python3 scripts/ink_to_text.py file1.ink [file2.ink ...] --out-dir ./out \
    --engine azure --corrections-map user_corrections/example_regex.json

Env:
  AZURE_VISION_ENDPOINT, AZURE_VISION_KEY (or put them in .env)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from msjournal_reader.corrections import apply_corrections
from msjournal_reader.ink import extract_pages_png
from msjournal_reader.ocr.registry import build_engine


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


def process_ink(
    ink_path: Path,
    out_dir: Path,
    *,
    engine_name: str,
    azure_language: str,
    azure_timeout_s: int,
    corrections_map: Path | None,
    postcorrector_model: Path | None,
    postcorrector_device: str,
) -> Path:
    stem = slug(ink_path.stem)
    doc_out = out_dir / stem
    doc_out.mkdir(parents=True, exist_ok=True)

    engine = build_engine(engine_name, azure_language=azure_language, azure_timeout_s=azure_timeout_s)

    postcorrector = None
    if postcorrector_model:
        try:
            from msjournal_reader.postcorrector import load_postcorrector

            postcorrector = load_postcorrector(postcorrector_model, device=postcorrector_device)
        except Exception as e:
            raise RuntimeError(
                "Failed to load post-corrector. Install optional ML deps (requirements-ml.txt) "
                "and verify --postcorrector-model points at a trained model directory.\n\n"
                f"Original error: {e}"
            )

    pages = extract_pages_png(ink_path)

    combined_md_parts: list[str] = []

    for page in pages:
        text = engine.ocr_png_bytes(page.png_bytes)
        text = apply_corrections(text, corrections_map)
        if postcorrector:
            text = postcorrector.apply(text)

        page_md = doc_out / f"page_{page.order:04d}.md"

        page_md.write_text(f"# Page {page.order}\n\n{text}\n", encoding="utf-8")

        combined_md_parts.append(f"# Page {page.order}\n\n{text}\n")

    combined_md_path = doc_out / "combined.md"

    combined_md_path.write_text("\n".join(combined_md_parts).strip() + "\n", encoding="utf-8")

    return combined_md_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help=".ink file(s)")
    ap.add_argument("--out-dir", default="./out", help="Output directory")
    ap.add_argument(
        "--engine",
        default="azure",
        help="OCR engine (only 'azure' implemented here for now)",
    )
    ap.add_argument("--azure-language", default="en", help="Azure Read language hint (default: en)")
    ap.add_argument("--azure-timeout", type=int, default=180, help="Azure Read poll timeout seconds (default: 180)")
    ap.add_argument(
        "--corrections-map",
        default=None,
        help="Optional JSON corrections (dict map or regex list) applied post-OCR",
    )
    ap.add_argument(
        "--postcorrector-model",
        default=None,
        help="Optional trained seq2seq model dir (e.g. user_corrections/local/models/byt5). Applied after corrections-map.",
    )
    ap.add_argument(
        "--allow-nonlocal-postcorrector",
        action="store_true",
        help="Allow a post-corrector model path outside user_corrections/local/ (not recommended; easier to accidentally commit).",
    )
    ap.add_argument("--postcorrector-device", default="cpu", help="cpu|cuda|mps (default: cpu)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    corr = Path(args.corrections_map).expanduser().resolve() if args.corrections_map else None
    pc_model = Path(args.postcorrector_model).expanduser().resolve() if args.postcorrector_model else None
    if pc_model and not args.allow_nonlocal_postcorrector:
        from msjournal_reader.local_paths import require_under

        repo_root = Path(__file__).resolve().parents[1]
        allowed = (repo_root / "user_corrections" / "local").resolve()
        try:
            # Allow symlinks under user_corrections/local/ so you can keep the
            # actual model directory on OneDrive and link it back.
            pc_model = require_under(
                pc_model,
                allowed,
                hint=(
                    "Refusing to load --postcorrector-model outside user_corrections/local/. "
                    "Move it under user_corrections/local/ (recommended), or pass --allow-nonlocal-postcorrector."
                ),
                resolve_symlinks=False,
            )
        except ValueError as e:
            raise SystemExit(str(e))

    for inp in args.inputs:
        ink_path = Path(inp).expanduser().resolve()
        if not ink_path.exists():
            print(f"Missing: {ink_path}", file=sys.stderr)
            continue
        combined = process_ink(
            ink_path,
            out_dir,
            engine_name=args.engine,
            azure_language=args.azure_language,
            azure_timeout_s=args.azure_timeout,
            corrections_map=corr,
            postcorrector_model=pc_model,
            postcorrector_device=str(args.postcorrector_device),
        )
        print(f"OK: {ink_path.name} -> {combined}")


if __name__ == "__main__":
    main()
