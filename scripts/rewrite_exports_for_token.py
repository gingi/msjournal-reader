#!/usr/bin/env python3
"""Apply current corrections map to already-exported pages that contain a token.

This is the fast path after accepting a correction in chat:
- Find page_*.md that contain the token (word-boundary, case-insensitive)
- Re-apply corrections map to the body text
- Rewrite only changed files

Optionally rebuild yearly exports + SQLite FTS index afterward.

Example:
  PYTHONPATH=. python3 scripts/rewrite_exports_for_token.py \
    --exports-base "/c/.../exports/msjournal-reader" \
    --token julz \
    --corrections-map user_corrections/local/gingi_regex.v2.json \
    --yearly-out "/c/.../exports/msjournal-reader/yearly" \
    --index-db "/c/.../exports/msjournal-reader/index/journal_index.sqlite"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from msjournal_reader.corrections import apply_corrections


def read_body(md_path: Path) -> tuple[str, str]:
    raw = md_path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith("# Page"):
        header = lines[0].rstrip() + "\n\n"
        body = "\n".join(lines[1:]).lstrip("\n")
        return header, body
    return "", raw


def write_page(md_path: Path, header: str, body: str) -> None:
    md_path.write_text((header + body.strip() + "\n").lstrip("\n"), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--corrections-map", required=True)
    ap.add_argument("--exports-base")
    ap.add_argument("--yearly-out")
    ap.add_argument("--index-db")
    ap.add_argument(
        "--paths-config",
        default="user_corrections/local/pipeline_paths.json",
        help="JSON file with exports_base/yearly_out/index_db defaults.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    # Load defaults from paths-config if explicit args are missing
    cfg_path = Path(args.paths_config)
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path
    cfg = {}
    if cfg_path.exists():
        import json

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    exports_base_raw = args.exports_base or cfg.get("exports_base")
    yearly_out_raw = args.yearly_out or cfg.get("yearly_out")
    index_db_raw = args.index_db or cfg.get("index_db")

    if not exports_base_raw:
        raise SystemExit("Missing --exports-base (or exports_base in --paths-config)")

    exports_base = Path(str(exports_base_raw)).expanduser().resolve()
    corr_path = Path(args.corrections_map).expanduser().resolve()
    args.yearly_out = yearly_out_raw
    args.index_db = index_db_raw
    token = str(args.token).strip().lower()
    if not token:
        raise SystemExit("Empty token")

    pat = re.compile(r"\\b" + re.escape(token) + r"\\b", re.IGNORECASE)

    changed = 0
    scanned = 0

    for doc_dir in sorted([p for p in exports_base.iterdir() if p.is_dir()]):
        if doc_dir.name in {"yearly", "index"}:
            continue
        for md in sorted(doc_dir.glob("page_*.md")):
            scanned += 1
            try:
                header, body = read_body(md)
            except FileNotFoundError:
                continue

            if not pat.search(body):
                continue

            new_body = apply_corrections(body, corr_path)
            if new_body.strip() == body.strip():
                continue

            write_page(md, header, new_body)
            changed += 1

    print(f"OK: rewrote pages containing '{token}': changed={changed} scanned={scanned}")

    # Rebuild derived artifacts if requested
    if args.yearly_out:
        import runpy, sys

        original_argv = list(sys.argv)
        try:
            sys.argv = [
                "build_year_exports.py",
                "--exports-base",
                str(exports_base),
                "--out-dir",
                str(Path(args.yearly_out).expanduser().resolve()),
            ]
            runpy.run_path(str(Path(__file__).resolve().parent / "build_year_exports.py"), run_name="__main__")
        finally:
            sys.argv = original_argv

    if args.index_db:
        import runpy, sys

        original_argv = list(sys.argv)
        try:
            sys.argv = [
                "build_index.py",
                "--exports-base",
                str(exports_base),
                "--db",
                str(Path(args.index_db).expanduser().resolve()),
            ]
            runpy.run_path(str(Path(__file__).resolve().parent / "build_index.py"), run_name="__main__")
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    main()
