from __future__ import annotations

import json
from pathlib import Path

from msjournal_reader.corrections import apply_corrections


def test_apply_corrections_dict_word_boundaries(tmp_path: Path) -> None:
    m = {"cat": "dog", "new york": "NYC"}
    p = tmp_path / "map.json"
    p.write_text(json.dumps(m), encoding="utf-8")

    text = "A cat scatters. New York is big. new york!"
    out = apply_corrections(text, p)

    # word boundary: 'cat' replaced, but not inside 'scatters'
    assert "A dog scatters" in out
    assert "NYC is big" in out


def test_apply_corrections_regex_list_order(tmp_path: Path) -> None:
    # order matters: first turns 'abc' into 'x', second turns 'x' into 'y'
    rules = [["abc", "x"], ["x", "y"]]
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules), encoding="utf-8")

    out = apply_corrections("abc", p)
    assert out == "y"


def test_apply_corrections_missing_file_is_noop(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    text = "hello"
    assert apply_corrections(text, missing) == text
