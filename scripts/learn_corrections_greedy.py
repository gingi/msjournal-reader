#!/usr/bin/env python3
"""Learn a small set of safe regex corrections by optimizing WER on provided gold pages.

Output format: JSON list [[pattern, replacement], ...] where pattern is regex.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jiwer import process_words, wer


def normalize_for_wer(s: str) -> str:
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


def apply_corr(text: str, patt: str, repl: str) -> str:
    return re.sub(patt, repl, text, flags=re.IGNORECASE)


@dataclass(frozen=True)
class Pair:
    page: str
    gold_norm: str
    hyp_norm: str


def score(pairs: list[Pair], corrs: list[tuple[str, str]]) -> float:
    total = 0.0
    for p in pairs:
        hyp = p.hyp_norm
        for patt, repl in corrs:
            hyp = apply_corr(hyp, patt, repl)
        total += wer(p.gold_norm, hyp)
    return total / max(1, len(pairs))


def extract_candidates(pairs: list[Pair]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for p in pairs:
        out = process_words(p.gold_norm, p.hyp_norm)
        ref = out.references[0]
        hyp = out.hypotheses[0]
        for ch in out.alignments[0]:
            if ch.type != "substitute":
                continue
            r = ref[ch.ref_start_idx : ch.ref_end_idx]
            h = hyp[ch.hyp_start_idx : ch.hyp_end_idx]
            if not (1 <= len(r) <= 4 and 1 <= len(h) <= 4):
                continue
            right = " ".join(r).strip()
            wrong = " ".join(h).strip()
            if not right or not wrong or right == wrong:
                continue
            if len(right) <= 2 or len(wrong) <= 2:
                continue
            wrong_esc = re.escape(wrong).replace("\\ ", r"\\s+")
            patt = rf"\b{wrong_esc}\b"
            key = (patt, right)
            counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", required=True)
    ap.add_argument("--hyp-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-corrections", type=int, default=30)
    ap.add_argument("--min-count", type=int, default=1)
    args = ap.parse_args()

    gold_dir = Path(args.gold_dir)
    hyp_dir = Path(args.hyp_dir)

    pairs: list[Pair] = []
    for gp in sorted(gold_dir.glob("*.txt")):
        m = re.search(r"page[-_](\d{4})", gp.name)
        if not m:
            continue
        page = m.group(1)
        hp = hyp_dir / f"page_{page}.md"
        if not hp.exists():
            continue
        gold_norm = normalize_for_wer(gp.read_text(encoding="utf-8", errors="replace"))
        hyp_md = hp.read_text(encoding="utf-8", errors="replace")
        lines = hyp_md.splitlines()
        if lines and lines[0].lstrip().startswith("# Page"):
            hyp_raw = "\n".join(lines[1:])
        else:
            hyp_raw = hyp_md
        hyp_norm = normalize_for_wer(hyp_raw)
        pairs.append(Pair(page=page, gold_norm=gold_norm, hyp_norm=hyp_norm))

    if not pairs:
        raise SystemExit("No (gold,hyp) pairs found")

    base = score(pairs, [])
    print(f"Base avg WER: {base:.4f} across {len(pairs)} pages")

    cand_counts = extract_candidates(pairs)
    candidates = [(patt, repl, c) for (patt, repl), c in cand_counts.items() if c >= args.min_count]
    candidates.sort(key=lambda x: (-x[2], len(x[0])))

    chosen: list[tuple[str, str]] = []
    best = base

    for patt, repl, c in candidates:
        if len(chosen) >= args.max_corrections:
            break
        trial = chosen + [(patt, repl)]
        s = score(pairs, trial)
        if s < best - 1e-6:
            chosen.append((patt, repl))
            best = s
            print(f"+ keep (count={c}) {patt} -> {repl}  avgWER={best:.4f}")

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    print(f"OK: wrote {len(chosen)} corrections -> {outp} (avgWER {best:.4f})")


if __name__ == "__main__":
    main()
