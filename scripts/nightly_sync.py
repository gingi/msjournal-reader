#!/usr/bin/env python3
"""Incremental nightly journal sync with file-state tracking.

Checks each .ink journal file's mtime + size + md5 (and the corrections map's
hash) against a persisted state file.  Only re-imports journals whose source
files have actually changed.  Always rebuilds yearly exports and the FTS index
when at least one journal was re-imported.

State file location: user_corrections/local/file_state.json

Usage:
  PYTHONPATH=. python3 scripts/nightly_sync.py \
    --config user_corrections/local/journals.json

Options:
  --force           Ignore state file, re-import everything (weekly rebuild mode).
  --rewrite-corr    After import, rewrite all existing exports with current
                    corrections map (useful when corrections changed but ink
                    files didn't).  Implied by --force.
  --dry-run         Show what would be done without doing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

STATE_FILE = "user_corrections/local/file_state.json"


def _file_md5(p: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _file_fingerprint(p: Path) -> dict:
    """Return a dict describing the current on-disk state of *p*."""
    st = p.stat()
    return {
        "path": str(p),
        "mtime": st.st_mtime,
        "size": st.st_size,
        "md5": _file_md5(p),
    }


def load_state(repo_root: Path) -> dict:
    sp = repo_root / STATE_FILE
    if sp.exists():
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(repo_root: Path, state: dict) -> None:
    sp = repo_root / STATE_FILE
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _has_changed(fp: dict, old: dict | None) -> bool:
    """Return True if a file fingerprint differs from old state."""
    if old is None:
        return True
    # Compare size + mtime first (cheap), then md5
    if fp["size"] != old.get("size") or fp["mtime"] != old.get("mtime"):
        return True
    if fp["md5"] != old.get("md5"):
        return True
    return False


# ---------------------------------------------------------------------------
# Pipeline helpers (invoke existing scripts via runpy)
# ---------------------------------------------------------------------------

def _run_script(repo_root: Path, script_name: str, argv: list[str]) -> None:
    original = list(sys.argv)
    try:
        sys.argv = [script_name] + argv
        runpy.run_path(str(repo_root / "scripts" / script_name), run_name="__main__")
    finally:
        sys.argv = original


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True,
                    help="Path to journals.json config file")
    ap.add_argument("--force", action="store_true",
                    help="Ignore state, re-import everything (weekly rebuild)")
    ap.add_argument("--rewrite-corr", action="store_true",
                    help="Rewrite all exports with current corrections map")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change, don't execute")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = (repo_root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    journals = [Path(x).expanduser().resolve() for x in (cfg.get("journals") or [])]
    if not journals:
        raise SystemExit("Config has no journals[]")

    # Load pipeline paths
    paths_cfg_path = repo_root / "user_corrections/local/pipeline_paths.json"
    paths_cfg = json.loads(paths_cfg_path.read_text(encoding="utf-8")) if paths_cfg_path.exists() else {}
    exports_base = paths_cfg.get("exports_base", "")
    yearly_out = paths_cfg.get("yearly_out", "")
    index_db = paths_cfg.get("index_db", "")

    if not all([exports_base, yearly_out, index_db]):
        raise SystemExit("pipeline_paths.json must define exports_base, yearly_out, index_db")

    # Corrections map fingerprint
    corr_map_rel = cfg.get("corrections_map", "")
    corr_map_path = (repo_root / corr_map_rel).resolve() if corr_map_rel else None
    corr_fp = _file_fingerprint(corr_map_path) if corr_map_path and corr_map_path.exists() else None

    # Load previous state
    state = load_state(repo_root)
    prev_journals = state.get("journals", {})
    prev_corr = state.get("corrections_map")

    # Determine which journals changed
    changed_journals: list[Path] = []
    journal_fps: dict[str, dict] = {}

    for ink in journals:
        if not ink.exists():
            print(f"SKIP missing: {ink}")
            continue
        fp = _file_fingerprint(ink)
        journal_fps[str(ink)] = fp

        if args.force:
            changed_journals.append(ink)
        elif _has_changed(fp, prev_journals.get(str(ink))):
            changed_journals.append(ink)

    # Check if corrections map changed
    corr_changed = False
    if corr_fp and _has_changed(corr_fp, prev_corr):
        corr_changed = True

    # Summary
    print(f"Journals: {len(journals)} configured, {len(changed_journals)} changed")
    if corr_changed:
        print("Corrections map: CHANGED")
    else:
        print("Corrections map: unchanged")

    if args.dry_run:
        for j in changed_journals:
            print(f"  WOULD re-import: {j.name}")
        if corr_changed or args.rewrite_corr or args.force:
            print("  WOULD rewrite exports with current corrections")
        if changed_journals or corr_changed or args.rewrite_corr or args.force:
            print("  WOULD rebuild yearly exports + index")
        return

    anything_done = False

    # Phase 1: Re-import changed journals via update_exports.py
    if changed_journals:
        # Build a temporary config with only the changed journals
        tmp_cfg = dict(cfg)
        tmp_cfg["journals"] = [str(j) for j in changed_journals]
        tmp_cfg_path = repo_root / "user_corrections/local/_tmp_sync_config.json"
        tmp_cfg_path.write_text(json.dumps(tmp_cfg, indent=2), encoding="utf-8")

        try:
            os.chdir(str(repo_root))
            _run_script(repo_root, "update_exports.py", [
                "--config", str(tmp_cfg_path),
                "--exports-base", exports_base,
                "--yearly-out", yearly_out,
                "--index-db", index_db,
            ])
        finally:
            tmp_cfg_path.unlink(missing_ok=True)

        anything_done = True

    # Phase 2: Rewrite corrections if map changed (or --force / --rewrite-corr)
    if corr_changed or args.rewrite_corr or args.force:
        if corr_map_path:
            print("Rewriting exports with current corrections map...")
            os.chdir(str(repo_root))
            _run_script(repo_root, "rewrite_exports_with_corrections.py", [
                "--corrections-map", str(corr_map_path),
                "--exports-base", exports_base,
                "--rebuild-yearly",
                "--rebuild-index",
            ])
            anything_done = True

    # Phase 3: If only yearly/index rebuild is needed (e.g. changed journals
    # but update_exports already handles rebuild), we're done.

    if not anything_done:
        print("NOOP: nothing changed since last sync")
    else:
        print("DONE: sync complete")

    # Save new state
    new_state = {
        "journals": journal_fps,
        "corrections_map": corr_fp,
        "corrections_model_version": state.get("corrections_model_version"),
        "last_sync_epoch": int(time.time()),
        "last_sync_mode": "force" if args.force else "incremental",
    }
    save_state(repo_root, new_state)
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
