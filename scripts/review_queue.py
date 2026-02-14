#!/usr/bin/env python3
"""Interactive reviewer for mined OCR correction candidates.

Reads a JSONL queue produced by scripts/mine_suspects.py and lets you accept or
edit a replacement. Accepted items are appended to a regex corrections map and
marked as reviewed in a state file so they don't get re-suggested.

Default behavior is deliberately conservative:
- It only writes *word-boundary* regex replacements: ["\\bTOKEN\\b", "REPL"].
- It lowercases the token for matching (token itself is stored lowercased by the miner).

Files (defaults):
- queue: user_corrections/local/review_queue.jsonl
- corrections map: user_corrections/local/regex_corrections.json
  (a JSON list of [pattern, replacement])
- review state: user_corrections/local/review_state.json

Example:
  python3 scripts/review_queue.py \
    --queue user_corrections/local/review_queue.jsonl \
    --corrections-map user_corrections/local/regex_corrections.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(json.loads(line))
    return items


def append_regex_rule(corrections: list, token: str, repl: str) -> None:
    # exact word-boundary match; escape token just in case
    pat = r"\\b" + re.escape(token) + r"\\b"
    corrections.append([pat, repl])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="user_corrections/local/review_queue.jsonl")
    ap.add_argument("--corrections-map", default="user_corrections/local/regex_corrections.json")
    ap.add_argument("--state", default="user_corrections/local/review_state.json")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--non-interactive", action="store_true", help="Print items and exit (no writes)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    queue_path = Path(args.queue)
    if not queue_path.is_absolute():
        queue_path = repo_root / queue_path

    corrections_path = Path(args.corrections_map)
    if not corrections_path.is_absolute():
        corrections_path = repo_root / corrections_path

    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = repo_root / state_path

    items = load_jsonl(queue_path)
    if not items:
        print(f"No queue items at {queue_path}")
        return

    state = load_json(state_path, default={})
    reviewed_tokens = state.get("reviewed_tokens") or {}
    corrections = load_json(corrections_path, default=[])
    if not isinstance(corrections, list):
        raise SystemExit(f"Corrections map must be a JSON list: {corrections_path}")

    n = 0
    for it in items:
        if n >= int(args.max):
            break
        token = str(it.get("token") or "").strip().lower()
        if not token:
            continue
        if token in reviewed_tokens:
            continue
        suggestions = it.get("suggestions") or []
        best = suggestions[0]["replacement"] if suggestions else ""

        if args.non_interactive:
            print(json.dumps(it, ensure_ascii=False))
            n += 1
            continue

        print("\n" + "=" * 80)
        print(f"TOKEN: {token}  (count={it.get('count')})")
        if suggestions:
            print("Suggestions:")
            for i, s in enumerate(suggestions[:5], start=1):
                print(f"  {i}) {s.get('replacement')}  (freq={s.get('freq')}, score={s.get('score'):.2f})")
        exs = it.get("examples") or []
        if exs:
            print("Examples:")
            for e in exs[:4]:
                print(f"  - {e.get('doc')} p{e.get('page')}: {e.get('line')}")

        print("\nAction:")
        print("  [enter] accept best suggestion")
        print("  1-5    accept that suggestion")
        print("  e      edit replacement")
        print("  s      skip")
        print("  q      quit")

        choice = input(f"> ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            reviewed_tokens[token] = {"status": "skipped", "ts": int(time.time()), "id": it.get("id")}
            n += 1
            continue

        repl = ""
        if choice == "":
            repl = str(best).strip()
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(suggestions):
                repl = str(suggestions[idx].get("replacement") or "").strip()
        elif choice == "e":
            repl = input("Replacement: ").strip()

        if not repl:
            print("No replacement chosen; skipping.")
            reviewed_tokens[token] = {"status": "skipped", "ts": int(time.time()), "id": it.get("id")}
            n += 1
            continue

        append_regex_rule(corrections, token, repl)
        reviewed_tokens[token] = {
            "status": "accepted",
            "replacement": repl,
            "ts": int(time.time()),
            "id": it.get("id"),
        }
        print(f"Added rule: \\b{token}\\b -> {repl}")
        n += 1

    if args.non_interactive:
        return

    state["reviewed_tokens"] = reviewed_tokens
    save_json(state_path, state)
    save_json(corrections_path, corrections)
    print("\nSaved:")
    print(f"  state: {state_path}")
    print(f"  corrections: {corrections_path} (rules={len(corrections)})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        raise
