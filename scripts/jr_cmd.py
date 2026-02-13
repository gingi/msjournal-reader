#!/usr/bin/env python3
"""Deterministic command parser for the journal-reader Slack DM workflow.

This is designed for "bang commands" so the bot doesn't need to guess whether
we're in the review loop.

Prefix: jr:

Commands:
  jr: review | jr: next
  jr: accept 1|2|3
  jr: accept <replacement text>
  jr: skip
  jr: image
  jr: stop
  jr: status

Behavior:
- Only parses/acts on commands; everything else should be treated as normal chat.
- Uses scripts/chat_review.py for queue state.
- Uses scripts/integrate_corrections.py touch/integrate for deferred integration.

Output:
- Prints text for the bot to send.
- For jr: image, prints JSON with png path + context (passthrough from chat_review.py).

Note: keep this script side-effect free beyond the expected state/corrections writes.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, py_path: bool = False) -> str:
    env = None
    if py_path:
        import os

        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
    p = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        # Keep errors short and actionable for chat
        msg = err.splitlines()[-1] if err else f"command failed: {' '.join(cmd)}"
        raise SystemExit(msg)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="Raw user message text (tokens).")
    args = ap.parse_args()

    raw = " ".join(args.text).strip()
    if not raw:
        raise SystemExit("No input")

    # Slack often includes a leading mention like "@Okemo". Strip a single leading mention-ish token.
    # Examples:
    #   "@Okemo jr: review" -> "jr: review"
    #   "<@U123> jr: review" -> "jr: review"
    raw2 = raw
    parts0 = raw2.split(None, 1)
    if parts0 and (parts0[0].startswith("@") or (parts0[0].startswith("<@") and parts0[0].endswith(">"))):
        raw2 = parts0[1] if len(parts0) > 1 else ""
    raw2 = raw2.strip()

    # Normalize input that starts with the prefix (after optional mention)
    low = raw2.lower()
    if low.startswith("jr:"):
        body = raw2[3:].strip()
    else:
        # Allow calling without prefix when invoked manually
        body = raw2

    # tokenization that respects quotes
    parts = shlex.split(body)
    if not parts:
        raise SystemExit("Missing command")

    cmd = parts[0].lower()
    rest = parts[1:]

    if cmd in {"review", "next"}:
        return_text = run(["python3", "scripts/chat_review.py", "next"], py_path=True)
        print(return_text)
        return

    if cmd == "skip":
        out = run(["python3", "scripts/chat_review.py", "answer", "skip"], py_path=True)
        print(out + "\n\n" + "When ready: `jr: next`.")
        return

    if cmd == "stop":
        out = run(["python3", "scripts/chat_review.py", "answer", "stop"], py_path=True)
        print(out)
        return

    if cmd == "image":
        # Pass through JSON from chat_review.py image
        out = run(["python3", "scripts/chat_review.py", "image"], py_path=True)
        # Validate it's JSON (but still print original)
        try:
            json.loads(out)
        except Exception:
            pass
        print(out)
        return

    if cmd == "accept":
        if not rest:
            raise SystemExit("Usage: !jr accept 1|2|3 OR !jr accept <replacement>")
        # If first arg is 1/2/3, pass that through; else pass the replacement text
        if rest[0] in {"1", "2", "3"} and len(rest) == 1:
            ans = rest[0]
        else:
            ans = " ".join(rest)
        out = run(["python3", "scripts/chat_review.py", "answer", ans], py_path=True)
        # Start (or keep) integration timer if this was an accepted correction
        if out.lower().startswith("added correction"):
            _ = run(["python3", "scripts/integrate_corrections.py", "touch", "--delay-s", "3600"], py_path=True)

        # Check whether queue is finished; if so, integrate now.
        # We do this by calling `next` but not printing it. This will pre-load the next pending
        # item internally; user can fetch it with `jr: next`.
        nxt = run(["python3", "scripts/chat_review.py", "next"], py_path=True)
        if nxt.lower().startswith("no unresolved"):
            integ = run(["python3", "scripts/integrate_corrections.py", "integrate", "--force"], py_path=True)
            print(out + "\n\n" + integ)
            return

        print(out + "\n\n" + "Saved. When ready: `jr: next`. (I’ve queued up the next item.)")
        return

    if cmd == "status":
        st = run(["python3", "scripts/integrate_corrections.py", "status"], py_path=True)
        print(st)
        return

    raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
