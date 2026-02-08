#!/usr/bin/env python3
"""Apply a learned corrections JSON (wrong->right) to a text file.

Usage:
  python3 scripts/apply_corrections.py --map corrections.json --in in.txt --out out.txt
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))

    text = Path(args.inp).read_text(encoding="utf-8", errors="replace")

    for wrong in sorted(mapping.keys(), key=len, reverse=True):
        right = mapping[wrong]
        wrong_s = str(wrong).strip()
        if not wrong_s:
            continue
        patt = re.compile(rf"\b{re.escape(wrong_s)}\b", flags=re.IGNORECASE)
        text = patt.sub(str(right), text)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(text, encoding="utf-8")
    print(f"OK: {args.inp} -> {args.out}")


if __name__ == "__main__":
    main()
