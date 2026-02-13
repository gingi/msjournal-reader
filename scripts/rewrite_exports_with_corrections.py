#!/usr/bin/env python3
"""Rewrite exported page markdown by re-applying the current corrections map.

This is intentionally OCR-free: it does not touch the .ink source or rerun OCR.
It simply re-applies msjournal_reader.corrections.apply_corrections() to the
existing exported text to quickly propagate new correction rules.

It preserves the `# Page N` header if present.

Typical usage (defaults read from user_corrections/local/pipeline_paths.json):
  PYTHONPATH=. python3 scripts/rewrite_exports_with_corrections.py \
    --corrections-map user_corrections/local/gingi_regex.v2.json

You can also rebuild derived artifacts:
  --rebuild-yearly / --rebuild-index
"""

from __future__ import annotations

import argparse
import json
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


def load_paths(repo_root: Path, paths_config: str) -> dict:
    p = Path(paths_config)
    if not p.is_absolute():
        p = repo_root / p
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def rebuild_yearly(repo_root: Path, exports_base: Path, yearly_out: Path) -> None:
    import runpy, sys

    original_argv = list(sys.argv)
    try:
        sys.argv = [
            "build_year_exports.py",
            "--exports-base",
            str(exports_base),
            "--out-dir",
            str(yearly_out),
        ]
        runpy.run_path(str(repo_root / "scripts" / "build_year_exports.py"), run_name="__main__")
    finally:
        sys.argv = original_argv


def rebuild_index(repo_root: Path, exports_base: Path, index_db: Path) -> None:
    import runpy, sys

    original_argv = list(sys.argv)
    try:
        sys.argv = [
            "build_index.py",
            "--exports-base",
            str(exports_base),
            "--db",
            str(index_db),
        ]
        runpy.run_path(str(repo_root / "scripts" / "build_index.py"), run_name="__main__")
    finally:
        sys.argv = original_argv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corrections-map", required=True)
    ap.add_argument("--exports-base")
    ap.add_argument("--yearly-out")
    ap.add_argument("--index-db")
    ap.add_argument("--paths-config", default="user_corrections/local/pipeline_paths.json")
    ap.add_argument("--rebuild-yearly", action="store_true")
    ap.add_argument("--rebuild-index", action="store_true")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_paths(repo_root, args.paths_config)

    exports_base_raw = args.exports_base or cfg.get("exports_base")
    yearly_out_raw = args.yearly_out or cfg.get("yearly_out")
    index_db_raw = args.index_db or cfg.get("index_db")

    if not exports_base_raw:
        raise SystemExit("Missing exports_base (arg or paths-config)")

    exports_base = Path(str(exports_base_raw)).expanduser().resolve()
    yearly_out = Path(str(yearly_out_raw)).expanduser().resolve() if yearly_out_raw else None
    index_db = Path(str(index_db_raw)).expanduser().resolve() if index_db_raw else None
    corr = Path(args.corrections_map)
    if not corr.is_absolute():
        corr = repo_root / corr
    corr = corr.expanduser().resolve()

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
            if not body.strip():
                continue
            new_body = apply_corrections(body, corr)
            if new_body.strip() == body.strip():
                continue
            write_page(md, header, new_body)
            changed += 1

    print(f"OK: rewrite_exports_with_corrections changed={changed} scanned={scanned}")

    if args.rebuild_yearly:
        if not yearly_out:
            raise SystemExit("--rebuild-yearly requires yearly_out (arg or paths-config)")
        rebuild_yearly(repo_root, exports_base, yearly_out)
        print("OK: rebuilt yearly")

    if args.rebuild_index:
        if not index_db:
            raise SystemExit("--rebuild-index requires index_db (arg or paths-config)")
        rebuild_index(repo_root, exports_base, index_db)
        print("OK: rebuilt index")


if __name__ == "__main__":
    main()
