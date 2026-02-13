#!/usr/bin/env python3
"""Render a compact Slack-friendly prompt from a mined review queue.

Reads the JSONL produced by scripts/mine_suspects.py and writes a short text
summary suitable for posting to chat.

It does *not* mutate state; it's safe to run from cron.

Example:
  python3 scripts/render_review_prompt.py \
    --queue user_corrections/local/review_queue.jsonl \
    --out user_corrections/local/review_prompt.txt \
    --limit 12
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(p: Path) -> list[dict]:
    items: list[dict] = []
    if not p.exists():
        return items
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(json.loads(line))
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument(
        "--context",
        default="These are likely recurring OCR mistakes mined from your exported journal pages.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    queue_path = Path(args.queue)
    if not queue_path.is_absolute():
        queue_path = repo_root / queue_path

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path

    items = load_jsonl(queue_path)
    items = items[: max(0, int(args.limit))]

    lines: list[str] = []
    if not items:
        lines.append("No new OCR correction candidates today.")
    else:
        lines.append("Journal-reader: OCR correction candidates are ready for review.")
        lines.append(args.context.strip())
        lines.append("")
        lines.append(f"Top {len(items)} unresolved tokens:")
        for i, it in enumerate(items, start=1):
            tok = str(it.get("token") or "").strip()
            cnt = it.get("count")
            suggs = it.get("suggestions") or []
            best = str(suggs[0].get("replacement") if suggs else "").strip()
            lines.append(f"{i:>2}) {tok}  ({cnt}x)  →  {best}")
        lines.append("")
        lines.append("To review in chat: DM me `jr: review` (one item at a time). You can include @mention, but it’s not required.")
        lines.append("Then use: `jr: accept 1` / `jr: accept Stacey's` / `jr: skip` / `jr: image`. ")
        lines.append("To advance to the next item, send: `jr: next`.")
        lines.append("Note: the numbered list above is just a ranking preview; in DM, `1/2/3` refer to the suggestion choices for the *current* item, not the list index.")
        lines.append("If you want to see the original handwriting image for an item, reply `image`. ")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"OK: wrote {out_path}")


if __name__ == "__main__":
    main()
