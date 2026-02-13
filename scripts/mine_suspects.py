#!/usr/bin/env python3
"""Mine OCR tokens that are good candidates for *systematic* correction.

Goal: produce a small daily queue (~20) of likely recurring OCR errors, not
single-instance oddities.

Heuristics (dictionary-free):
- Build corpus token frequencies from exported pages.
- Identify "rare" tokens that are close (edit distance 1) to a much more
  frequent token in the corpus (SymSpell-style deletes).
- Rank by potential impact: freq(rare) * log1p(freq(suggested)).
- Skip tokens already covered by the corrections map (simple \bTOKEN\b patterns).
- Maintain a reviewed-state file so we don't keep asking about the same token.

Output: JSONL queue, each line is a review item:
{
  "id": "...",
  "token": "...",
  "count": 7,
  "suggestions": [{"replacement":"...","score":...,"freq":...}, ...],
  "examples": [{"path": ".../page_0123.txt", "doc": "journal-2024", "page": 123, "line": "..."}, ...]
}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']{1,}")
PAGE_RE = re.compile(r"page_(\d{4})")


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


def _read_page_markdown(p: Path) -> str:
    md = p.read_text(encoding="utf-8", errors="replace")
    lines = md.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest = rest[1:]
        return "\n".join(rest)
    return md


def iter_page_texts(exports_base: Path, allow_docs: set[str] | None = None):
    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        if doc_dir.name in {"yearly", "index"}:
            continue
        if allow_docs is not None and doc_dir.name not in allow_docs:
            continue
        for page_path in sorted(doc_dir.glob("page_*.md")):
            try:
                st = page_path.stat()
            except FileNotFoundError:
                continue
            if st.st_size == 0:
                continue
            yield doc_dir.name, page_path


def tokenize(text: str) -> list[str]:
    return [m.group(0) for m in TOKEN_RE.finditer(text)]


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def parse_corrections_tokens(corrections_path: Path) -> set[str]:
    """Best-effort: extract literal tokens from patterns like \\btoken\\b."""
    toks: set[str] = set()
    try:
        data = json.loads(corrections_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return toks
    except Exception:
        return toks

    if not isinstance(data, list):
        return toks

    for item in data:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item)):
            continue
        pat = item[0]
        m = re.fullmatch(r"\\b(.+?)\\b", pat)
        if not m:
            continue
        # Only keep simple word-ish tokens
        lit = m.group(1)
        if re.fullmatch(r"[A-Za-z][A-Za-z']{1,}", lit):
            toks.add(lit.lower())
    return toks


def deletes1(w: str) -> set[str]:
    return {w[:i] + w[i + 1 :] for i in range(len(w))}


def edit_distance_1(a: str, b: str) -> bool:
    """Return True if Levenshtein distance(a,b) == 1."""
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False

    # substitution
    if la == lb:
        diff = sum(1 for i in range(la) if a[i] != b[i])
        return diff == 1

    # insertion/deletion
    if la + 1 == lb:
        a, b = b, a
        la, lb = lb, la
    # now la == lb+1
    i = j = 0
    used = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        if used:
            return False
        used = True
        i += 1
    return True


@dataclass
class Candidate:
    token: str
    count: int
    best_repl: str
    best_score: float
    best_freq: int
    suggestions: list[dict]


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports-base", required=True)
    ap.add_argument("--out-queue", required=True)
    ap.add_argument("--max-items", type=int, default=20)
    ap.add_argument(
        "--config",
        default=None,
        help="Optional journals.json; if provided, only mine doc slugs present in config journals[].",
    )
    ap.add_argument(
        "--state",
        default="user_corrections/local/review_state.json",
        help="Reviewed-state JSON path (relative to repo root unless absolute).",
    )
    ap.add_argument(
        "--corrections-map",
        default="user_corrections/local/gingi_regex.v2.json",
        help="Corrections map (regex list) used to skip already-addressed tokens.",
    )
    ap.add_argument("--min-rare", type=int, default=2, help="Minimum frequency for a rare token to be considered")
    ap.add_argument("--max-rare", type=int, default=20, help="Maximum frequency for a rare token to be considered")
    ap.add_argument("--freq-threshold", type=int, default=50, help="Minimum frequency for a token to be considered a likely correct word")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    exports_base = Path(args.exports_base)
    out_queue = Path(args.out_queue)

    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = repo_root / state_path

    corrections_path = Path(args.corrections_map)
    if not corrections_path.is_absolute():
        corrections_path = repo_root / corrections_path

    reviewed = load_json(state_path, default={})
    reviewed_tokens: set[str] = set((reviewed.get("reviewed_tokens") or {}).keys())
    skip_tokens = parse_corrections_tokens(corrections_path)

    allow_docs: set[str] | None = None
    if args.config:
        cfg_path = Path(str(args.config))
        if not cfg_path.is_absolute():
            cfg_path = repo_root / cfg_path
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            journals = [Path(x) for x in (cfg.get("journals") or [])]
            allow_docs = {_slug(p.stem) for p in journals}
        except Exception:
            allow_docs = None

    # 1) Corpus token counts + gather examples lines
    counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = defaultdict(list)

    for doc, page_path in iter_page_texts(exports_base, allow_docs=allow_docs):
        text = _read_page_markdown(page_path)
        toks = tokenize(text)
        if not toks:
            continue
        # Keep up to a few example lines per token
        lines = text.splitlines()
        for t in toks:
            tl = t.lower()
            counts[tl] += 1
        # For examples, scan lines once
        for line in lines[:120]:
            if not line.strip():
                continue
            for m in TOKEN_RE.finditer(line):
                tl = m.group(0).lower()
                if len(examples[tl]) >= 4:
                    continue
                pm = PAGE_RE.search(page_path.stem)
                page_num = int(pm.group(1)) if pm else 0
                examples[tl].append(
                    {
                        "path": str(page_path),
                        "doc": doc,
                        "page": page_num,
                        "line": line.strip(),
                    }
                )

    if not counts:
        raise SystemExit("No tokens found; exports-base empty?")

    # 2) Build deletes index for frequent tokens
    frequent = {t for t, c in counts.items() if c >= int(args.freq_threshold) and len(t) >= 3}
    del_index: dict[str, set[str]] = defaultdict(set)
    for t in frequent:
        for d in deletes1(t):
            del_index[d].add(t)

    # 3) Find rare candidates close to frequent tokens
    candidates: list[Candidate] = []
    for tok, c in counts.items():
        if c < int(args.min_rare) or c > int(args.max_rare):
            continue
        if tok in skip_tokens or tok in reviewed_tokens:
            continue
        if len(tok) < 3:
            continue
        # candidate suggestions from deletes
        suggs: set[str] = set()
        for d in deletes1(tok):
            suggs |= del_index.get(d, set())
        if not suggs:
            continue
        # keep only true edit distance 1
        suggs = {s for s in suggs if edit_distance_1(tok, s)}
        if not suggs:
            continue

        scored = []
        for s in sorted(suggs):
            sf = counts.get(s, 0)
            score = float(c) * math.log1p(float(sf))
            scored.append((score, s, sf))
        scored.sort(reverse=True)
        best_score, best, best_f = scored[0]
        suggestions = [
            {"replacement": s, "freq": int(sf), "score": float(sc)}
            for (sc, s, sf) in scored[:5]
        ]
        candidates.append(
            Candidate(
                token=tok,
                count=int(c),
                best_repl=best,
                best_score=float(best_score),
                best_freq=int(best_f),
                suggestions=suggestions,
            )
        )

    # 4) Rank and write queue
    candidates.sort(key=lambda x: (x.best_score, x.count, x.best_freq), reverse=True)

    # Deduplicate by (token,best_repl) just in case
    picked: list[Candidate] = []
    seen_pairs: set[tuple[str, str]] = set()
    for c in candidates:
        k = (c.token, c.best_repl)
        if k in seen_pairs:
            continue
        seen_pairs.add(k)
        picked.append(c)
        if len(picked) >= int(args.max_items):
            break

    out_queue.parent.mkdir(parents=True, exist_ok=True)

    now = int(time.time())
    items = []
    for c in picked:
        h = hashlib.sha1(f"{c.token}|{c.best_repl}".encode("utf-8")).hexdigest()[:16]
        item = {
            "id": f"{now}-{h}",
            "token": c.token,
            "count": c.count,
            "suggestions": c.suggestions,
            "examples": examples.get(c.token, [])[:4],
            "created_at": now,
        }
        items.append(item)

    # Write as JSONL (one item per line)
    out_queue.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + ("\n" if items else ""), encoding="utf-8")

    print(f"OK: wrote queue {out_queue} items={len(items)}")


if __name__ == "__main__":
    main()
