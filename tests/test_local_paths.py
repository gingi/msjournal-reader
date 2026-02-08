from __future__ import annotations

from pathlib import Path

import pytest

from msjournal_reader.local_paths import is_under, require_under


def test_is_under_true(tmp_path: Path) -> None:
    root = tmp_path / "root"
    child = root / "a" / "b"
    child.mkdir(parents=True)
    assert is_under(child, root)


def test_require_under_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError):
        require_under(other, root)
