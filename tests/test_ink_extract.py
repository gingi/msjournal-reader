from __future__ import annotations

import sqlite3
from pathlib import Path

from msjournal_reader.ink import extract_pages_png


def _make_db(p: Path) -> bytes:
    # minimal 1x1 PNG (valid header + IHDR + IDAT + IEND)
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0bIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_extract_pages_png_from_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "x.ink"

    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("CREATE TABLE pages (id BLOB PRIMARY KEY, page_order INTEGER)")
    cur.execute("CREATE TABLE blobs (owner_id BLOB, ordinal INTEGER, bytes BLOB)")

    page_id = b"\x01" * 16
    cur.execute("INSERT INTO pages (id, page_order) VALUES (?, ?)", (page_id, 3))
    cur.execute(
        "INSERT INTO blobs (owner_id, ordinal, bytes) VALUES (?, ?, ?)",
        (page_id, 0, _make_db(db)),
    )

    con.commit()
    con.close()

    pages = extract_pages_png(db)
    assert len(pages) == 1
    assert pages[0].order == 3
    assert pages[0].png_bytes.startswith(b"\x89PNG")
