#!/usr/bin/env python3
"""Evaluate OCR output against a gold transcription using WER.

Usage:
  python3 scripts/eval_wer.py --gold gold/file.txt --hyp out/.../page_0000.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jiwer import cer, process_words, wer


def normalize_for_wer(s: str) -> str:
    import re

    s = s.lower()
    s = s.replace("’", "'")

    circled = {
        "①": "1",
        "②": "2",
        "③": "3",
        "④": "4",
        "⑤": "5",
        "⑥": "6",
        "⑦": "7",
        "⑧": "8",
        "⑨": "9",
        "⑩": "10",
    }
    for k, v in circled.items():
        s = s.replace(k, v)

    s = re.sub(r"[^a-z0-9\s']+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def read_text(p: Path) -> str:
    raw = p.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        return "\n".join(lines[1:]).lstrip("\n")
    return raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--hyp", required=True)
    args = ap.parse_args()

    gold_raw = read_text(Path(args.gold))
    hyp_raw = read_text(Path(args.hyp))

    gold = normalize_for_wer(gold_raw)
    hyp = normalize_for_wer(hyp_raw)

    w = wer(gold, hyp)
    c = cer(gold_raw, hyp_raw)

    out = process_words(gold, hyp)
    hits = out.hits
    subs = out.substitutions
    ins = out.insertions
    dels = out.deletions
    total = hits + subs + dels

    print(f"GOLD: {args.gold}")
    print(f"HYP : {args.hyp}")
    print(f"WER : {w:.4f}")
    print(f"CER : {c:.4f}")
    print(f"Words: total={total} hits={hits} subs={subs} ins={ins} dels={dels}")


if __name__ == "__main__":
    main()
