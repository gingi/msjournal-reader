from __future__ import annotations

import json
import re
from pathlib import Path


def apply_corrections(text: str, corrections_path: Path | None) -> str:
    """Apply optional corrections.

    Supports:
    1) JSON dict: {"wrong": "right"} (word-boundary, case-insensitive)
    2) JSON list: [["<regex>", "<replacement>"], ...] (applied in order)

    Also applies a tiny generic baseline (safe fixes only).
    """
    out = text

    # Minimal generic fixes (avoid personalization here)
    generic_regex: list[tuple[str, str]] = [
        (r"\btered\b", "tired"),
        (r"\bliet\b", "diet"),
    ]
    for patt, repl in generic_regex:
        out = re.sub(patt, repl, out, flags=re.IGNORECASE)

    if not corrections_path:
        return out
    if not corrections_path.exists():
        return out

    obj = json.loads(corrections_path.read_text(encoding="utf-8"))

    # Regex list
    if isinstance(obj, list):
        for item in obj:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                continue
            patt, repl = item
            out = re.sub(str(patt), str(repl), out, flags=re.IGNORECASE)
        return out

    # Dict mapping
    if isinstance(obj, dict):
        for wrong in sorted(obj.keys(), key=lambda s: len(str(s)), reverse=True):
            right = obj[wrong]
            wrong_s = str(wrong).strip()
            if not wrong_s:
                continue
            patt = re.compile(rf"\b{re.escape(wrong_s)}\b", flags=re.IGNORECASE)
            out = patt.sub(str(right), out)

    return out
