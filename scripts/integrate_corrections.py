#!/usr/bin/env python3
"""Manage deferred integration of new correction rules into exported pages.

Concept:
- Accepting a correction updates the corrections map immediately.
- "Integrating" means rewriting already-exported pages to apply the new rules
  and rebuilding derived artifacts (yearly + SQLite FTS index).

Policy (as requested):
- Start a 1-hour timer from the first actionable item in a review session.
- If user completes the review session (no remaining items), integrate now.
- Otherwise integrate after the hour.
- Also integrate nightly if there are unintegrated corrections.

State file (gitignored): user_corrections/local/integration_state.json

Commands:
- touch: mark dirty + set due_at if not already dirty
- integrate: run integration (force or if-due)
- status: print current state
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    h.update(path.read_bytes())
    return h.hexdigest()


def now_s() -> int:
    return int(time.time())


def cmd_touch(state_path: Path, corrections_map: Path, delay_s: int) -> str:
    st = load_json(state_path, default={})
    dirty = bool(st.get("dirty"))

    if corrections_map.exists():
        st["current_rules_sha1"] = sha1_file(corrections_map)

    if not dirty:
        t = now_s()
        st["dirty"] = True
        st["dirty_since"] = t
        st["due_at"] = t + int(delay_s)
        save_json(state_path, st)
        return f"OK: marked dirty; due_at={st['due_at']} (in ~{delay_s//60}m)"

    # Already dirty; do not push due_at out (per request)
    save_json(state_path, st)
    return "OK: already dirty (timer unchanged)"


def run_integration(repo_root: Path, corrections_map: Path) -> str:
    import subprocess

    cmd = [
        "python3",
        str(repo_root / "scripts" / "rewrite_exports_with_corrections.py"),
        "--corrections-map",
        str(corrections_map),
        "--rebuild-yearly",
        "--rebuild-index",
    ]

    env = dict(**{k: v for k, v in dict(**__import__("os").environ).items()})
    env["PYTHONPATH"] = str(repo_root)

    p = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        raise SystemExit(f"Integration failed (code={p.returncode})\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return out or "OK"


def cmd_integrate(state_path: Path, corrections_map: Path, if_due: bool, force: bool) -> str:
    st = load_json(state_path, default={})

    if not st.get("dirty"):
        return "NOOP: nothing to integrate"

    due_at = int(st.get("due_at") or 0)
    t = now_s()
    if if_due and not force and due_at and t < due_at:
        return f"NOOP: not due yet (due_at={due_at}, now={t})"

    if corrections_map.exists():
        st["current_rules_sha1"] = sha1_file(corrections_map)

    repo_root = Path(__file__).resolve().parents[1]
    result = run_integration(repo_root, corrections_map)

    st["dirty"] = False
    st["last_integrated_at"] = t
    st["last_integrated_rules_sha1"] = st.get("current_rules_sha1")
    st.pop("due_at", None)
    save_json(state_path, st)

    return "Integrated corrections into exports/index.\n" + result


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_touch = sub.add_parser("touch")
    p_touch.add_argument("--state", default="user_corrections/local/integration_state.json")
    p_touch.add_argument("--corrections-map", default="user_corrections/local/gingi_regex.v2.json")
    p_touch.add_argument("--delay-s", type=int, default=3600)

    p_int = sub.add_parser("integrate")
    p_int.add_argument("--state", default="user_corrections/local/integration_state.json")
    p_int.add_argument("--corrections-map", default="user_corrections/local/gingi_regex.v2.json")
    p_int.add_argument("--if-due", action="store_true")
    p_int.add_argument("--force", action="store_true")

    p_status = sub.add_parser("status")
    p_status.add_argument("--state", default="user_corrections/local/integration_state.json")

    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = repo_root / state_path

    if args.cmd == "status":
        st = load_json(state_path, default={})
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return

    # touch/integrate need the corrections map
    corrections_map = Path(args.corrections_map)
    if not corrections_map.is_absolute():
        corrections_map = repo_root / corrections_map
    corrections_map = corrections_map.expanduser().resolve()

    if args.cmd == "touch":
        print(cmd_touch(state_path, corrections_map, int(args.delay_s)))
        return

    if args.cmd == "integrate":
        print(cmd_integrate(state_path, corrections_map, bool(args.if_due), bool(args.force)))
        return


if __name__ == "__main__":
    main()
