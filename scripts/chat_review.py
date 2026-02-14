#!/usr/bin/env python3
"""Slack-friendly chat review helper for OCR correction candidates.

This script is meant to be driven by the OpenClaw agent in a DM:
- `next` prints the next unresolved candidate as a compact prompt.
- `answer` records a decision (accept/skip) and updates the corrections map.
- `image` exports the full-page PNG for the currently pending item.

State is stored under user_corrections/local/ so users can skip days and resume.

Files (defaults):
- queue: user_corrections/local/review_queue.jsonl (from mine_suspects.py)
- state: user_corrections/local/review_state.json
- corrections map: user_corrections/local/regex_corrections.json (regex list)

This script is deliberately conservative: it only writes word-boundary rules
for single tokens: ["\\bTOKEN\\b", "replacement"].
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Make this script runnable without installing the package (no PYTHONPATH required)
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def ensure_regex_list(path: Path) -> list:
    data = load_json(path, default=[])
    if data == []:
        return []
    if not isinstance(data, list):
        raise SystemExit(f"Corrections map must be a JSON list: {path}")
    return data


def append_word_rule(rules: list, token: str, repl: str) -> None:
    pat = r"\\b" + re.escape(token) + r"\\b"
    rules.append([pat, repl])


def pick_next_item(items: list[dict], reviewed_tokens: dict) -> dict | None:
    for it in items:
        tok = str(it.get("token") or "").strip().lower()
        if not tok:
            continue
        if tok in reviewed_tokens:
            continue
        return it
    return None


def format_prompt(it: dict) -> str:
    tok = str(it.get("token") or "").strip()
    cnt = it.get("count")
    suggs = it.get("suggestions") or []
    exs = it.get("examples") or []

    lines: list[str] = []
    lines.append(f"OCR fix candidate: *{tok}* ({cnt}x)")
    if suggs:
        lines.append("Pick a replacement:")
        for i, s in enumerate(suggs[:3], start=1):
            rep = s.get("replacement")
            freq = s.get("freq")
            lines.append(f"  {i}) {rep} (seen {freq}x)")
    else:
        lines.append("No suggestions found; reply with the correct replacement.")

    if exs:
        lines.append("Context (examples):")
        for e in exs[:2]:
            doc = e.get("doc")
            page = e.get("page")
            line = str(e.get("line") or "").strip()
            if len(line) > 180:
                line = line[:177] + "..."
            lines.append(f"  - {doc} p{page}: {line}")

    lines.append("Reply with `1`/`2`/`3`, a custom replacement, `skip`, or `image`.")
    return "\n".join(lines)


def cmd_next(repo_root: Path, queue_path: Path, state_path: Path) -> str:
    state = load_json(state_path, default={})
    reviewed_tokens = state.get("reviewed_tokens") or {}

    items = load_jsonl(queue_path)
    it = pick_next_item(items, reviewed_tokens)
    if not it:
        # Clear pending if nothing to do
        state.pop("pending", None)
        save_json(state_path, state)
        return "No unresolved OCR candidates right now. (If you ran OCR recently, wait for the next mining job.)"

    # Store pending
    tok = str(it.get("token") or "").strip().lower()
    state["pending"] = {
        "id": it.get("id"),
        "token": tok,
        "suggestions": it.get("suggestions") or [],
        "examples": it.get("examples") or [],
        "ts": int(time.time()),
    }
    save_json(state_path, state)
    return format_prompt(it)


def parse_answer(raw: str, pending: dict) -> tuple[str, str | None]:
    s = raw.strip()
    sl = s.lower()
    if sl in {"skip", "s"}:
        return "skip", None
    if sl in {"image", "img"}:
        return "image", None
    if sl in {"stop", "done", "quit", "q"}:
        return "stop", None

    suggs = pending.get("suggestions") or []
    if s.isdigit():
        idx = int(s) - 1
        if 0 <= idx < len(suggs):
            rep = str(suggs[idx].get("replacement") or "").strip()
            if rep:
                return "accept", rep

    # Support "3 <replacement>" (common Slack reply pattern)
    m = re.match(r"^3\s+(.+)$", s)
    if m:
        rep = m.group(1).strip()
        if rep:
            return "accept", rep

    # Otherwise treat as a custom replacement
    if s:
        return "accept", s

    return "invalid", None


def cmd_answer(
    repo_root: Path,
    queue_path: Path,
    state_path: Path,
    corrections_path: Path,
    answer: str,
) -> str:
    state = load_json(state_path, default={})
    reviewed_tokens = state.get("reviewed_tokens") or {}
    pending = state.get("pending")
    if not pending:
        return "Nothing pending. DM `review` to get the next candidate."

    tok = str(pending.get("token") or "").strip().lower()
    if not tok:
        state.pop("pending", None)
        save_json(state_path, state)
        return "Pending item was invalid; cleared. DM `review` again."

    action, repl = parse_answer(answer, pending)

    if action == "image":
        return "IMAGE_REQUEST"

    if action == "stop":
        # Keep pending so user can resume later
        return "OK — stopping review for now. DM `review` when you want to continue."

    if action == "skip":
        reviewed_tokens[tok] = {"status": "skipped", "ts": int(time.time()), "id": pending.get("id")}
        state["reviewed_tokens"] = reviewed_tokens
        state.pop("pending", None)
        save_json(state_path, state)
        return f"Skipped *{tok}*. DM `review` for the next one."

    if action != "accept" or not repl:
        return "Didn’t understand that. Reply with `1`/`2`/`3`, a replacement, `skip`, or `image`."

    # Append correction rule
    rules = ensure_regex_list(corrections_path)

    # Dedup: don't add identical rule twice
    pat = r"\\b" + re.escape(tok) + r"\\b"
    exists = any(isinstance(x, list) and len(x) == 2 and x[0] == pat and x[1] == repl for x in rules)
    if not exists:
        append_word_rule(rules, tok, repl)
        corrections_path.parent.mkdir(parents=True, exist_ok=True)
        corrections_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reviewed_tokens[tok] = {
        "status": "accepted",
        "replacement": repl,
        "ts": int(time.time()),
        "id": pending.get("id"),
    }
    state["reviewed_tokens"] = reviewed_tokens
    state.pop("pending", None)
    save_json(state_path, state)

    return f"Added correction: *{tok}* → *{repl}*. Saved; will be integrated into exports/index later."


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "journal"


def cmd_image(repo_root: Path, cfg_path: Path, state_path: Path, out_path: Path) -> str:
    """Export the full-page PNG for the current pending item and return JSON.

    The JSON includes the exported PNG path plus the exact example context
    (doc/page/line/path) used to select the page.
    """
    from msjournal_reader.ink import extract_single_page_png

    state = load_json(state_path, default={})
    pending = state.get("pending")
    if not pending:
        raise SystemExit("Nothing pending")

    exs = pending.get("examples") or []
    if not exs:
        raise SystemExit("No examples attached to pending item")

    e0 = exs[0]
    doc = str(e0.get("doc") or "").strip()
    page = int(e0.get("page") or 0)
    if not doc or page <= 0:
        raise SystemExit("Example missing doc/page")

    cfg = load_json(cfg_path, default={})
    journals = [Path(x).expanduser().resolve() for x in (cfg.get("journals") or [])]
    if not journals:
        raise SystemExit("Config has no journals[]")

    ink_path = None
    for j in journals:
        if _slug(j.stem) == doc:
            ink_path = j
            break
    if ink_path is None:
        raise SystemExit(f"No .ink matched doc slug={doc}. Check config journals[]")

    hit = extract_single_page_png(ink_path, page)
    if hit is None:
        raise SystemExit(f"Page {page} not found in {ink_path}")

    out_path = Path(out_path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(hit.png_bytes)

    return json.dumps(
        {
            "png": str(out_path),
            "doc": doc,
            "page": page,
            "example": {
                "path": e0.get("path"),
                "line": e0.get("line"),
            },
        },
        ensure_ascii=False,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_next = sub.add_parser("next")
    p_next.add_argument("--queue", default="user_corrections/local/review_queue.jsonl")
    p_next.add_argument("--state", default="user_corrections/local/review_state.json")

    p_ans = sub.add_parser("answer")
    p_ans.add_argument("text", help="User reply text")
    p_ans.add_argument("--queue", default="user_corrections/local/review_queue.jsonl")
    p_ans.add_argument("--state", default="user_corrections/local/review_state.json")
    p_ans.add_argument("--corrections-map", default="user_corrections/local/gingi_regex.v2.json")

    p_img = sub.add_parser("image")
    p_img.add_argument("--config", default="user_corrections/local/journals.json")
    p_img.add_argument("--state", default="user_corrections/local/review_state.json")
    p_img.add_argument("--out", default="/tmp/journal-reader-page.png")

    args = ap.parse_args()

    repo_root = REPO_ROOT

    if args.cmd == "next":
        queue = Path(args.queue)
        if not queue.is_absolute():
            queue = repo_root / queue
        state = Path(args.state)
        if not state.is_absolute():
            state = repo_root / state
        print(cmd_next(repo_root, queue, state))
        return

    if args.cmd == "answer":
        queue = Path(args.queue)
        if not queue.is_absolute():
            queue = repo_root / queue
        state = Path(args.state)
        if not state.is_absolute():
            state = repo_root / state
        corr = Path(args.corrections_map)
        if not corr.is_absolute():
            corr = repo_root / corr
        print(cmd_answer(repo_root, queue, state, corr, args.text))
        return

    if args.cmd == "image":
        cfg = Path(args.config)
        if not cfg.is_absolute():
            cfg = repo_root / cfg
        state = Path(args.state)
        if not state.is_absolute():
            state = repo_root / state
        out = Path(args.out)
        # Print JSON (png path + context) so the agent can attach it and
        # paste the exact context used.
        print(cmd_image(repo_root, cfg, state, out))
        return


if __name__ == "__main__":
    main()
