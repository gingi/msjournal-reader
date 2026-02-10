#!/usr/bin/env python3
"""Apply a trained post-corrector model to a page export.

Example:
  python3 scripts/apply_postcorrector.py \
    --model-dir user_corrections/local/models/byt5 \
    --in out/journal-feb-2026/page_0001.md \
    --out out_corrected/page_0001.md

Note: per-page exports are Markdown ("# Page N" header + OCR body). This tool preserves
that wrapper and only rewrites the OCR body.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from msjournal_reader.postcorrector import load_postcorrector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pc = load_postcorrector(Path(args.model_dir), device=args.device, max_new_tokens=int(args.max_new_tokens))

    raw = Path(args.inp).read_text(encoding="utf-8", errors="replace")

    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        header = lines[0]
        body = "\n".join(lines[1:]).lstrip("\n")
        fixed_body = pc.apply(body)
        fixed = header + "\n\n" + fixed_body.strip() + "\n"
    else:
        fixed = pc.apply(raw)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(fixed, encoding="utf-8")
    print(f"OK: {args.inp} -> {args.out}")


if __name__ == "__main__":
    main()
