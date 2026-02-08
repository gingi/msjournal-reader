#!/usr/bin/env python3
"""Train a lightweight word/phrase correction map from (gold, hyp) pairs.

NOT ML. Output: JSON mapping of "wrong" -> "right" (lowercased).

Assumption: filenames match like:
  gold: journal-feb-2026_page-0001.txt
  hyp : page_0001.txt   (inside --hyp-dir)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jiwer import process_words


def normalize_for_training(s: str) -> str:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", required=True)
    ap.add_argument("--hyp-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-count", type=int, default=1)
    ap.add_argument("--exclude-pages", default="")
    args = ap.parse_args()

    gold_dir = Path(args.gold_dir)
    hyp_dir = Path(args.hyp_dir)

    exclude = {p.strip() for p in (args.exclude_pages or "").split(",") if p.strip()}

    counts: dict[tuple[str, str], int] = {}

    for gold_path in sorted(gold_dir.glob("*.txt")):
        m = re.search(r"page[-_](\d{4})", gold_path.name)
        if not m:
            continue
        page = m.group(1)
        if page in exclude:
            continue
        hyp_path = hyp_dir / f"page_{page}.txt"
        if not hyp_path.exists():
            continue

        gold_raw = gold_path.read_text(encoding="utf-8", errors="replace")
        hyp_raw = hyp_path.read_text(encoding="utf-8", errors="replace")

        gold = normalize_for_training(gold_raw)
        hyp = normalize_for_training(hyp_raw)

        out = process_words(gold, hyp)
        ref_words = out.references[0]
        hyp_words = out.hypotheses[0]

        for chunk in out.alignments[0]:
            if chunk.type != "substitute":
                continue
            r = ref_words[chunk.ref_start_idx : chunk.ref_end_idx]
            h = hyp_words[chunk.hyp_start_idx : chunk.hyp_end_idx]

            if not (1 <= len(r) <= 4 and 1 <= len(h) <= 4):
                continue

            right = " ".join([x.strip() for x in r]).strip()
            wrong = " ".join([x.strip() for x in h]).strip()
            if not right or not wrong or right == wrong:
                continue
            if len(right) <= 2 or len(wrong) <= 2:
                continue

            counts[(wrong, right)] = counts.get((wrong, right), 0) + 1

    by_wrong: dict[str, dict[str, int]] = {}
    for (wrong, right), c in counts.items():
        by_wrong.setdefault(wrong, {})[right] = c

    mapping: dict[str, str] = {}
    for wrong, rights in by_wrong.items():
        best_right, best_c = sorted(rights.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if best_c >= args.min_count:
            mapping[wrong] = best_right

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OK: learned {len(mapping)} substitutions -> {out_path}")


if __name__ == "__main__":
    main()
