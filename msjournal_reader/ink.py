from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class InkPage:
    order: int
    page_id_hex: str
    png_bytes: bytes


def extract_pages_png(db_path: Path) -> list[InkPage]:
    """Extract per-page rendered PNG blobs from a Microsoft Journal .ink file (SQLite DB).

    Observed schema:
    - pages.id (BLOB) + pages.page_order
    - blobs.owner_id == pages.id, blobs.ordinal == 0 holds a PNG render
    """
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT id, page_order FROM pages ORDER BY page_order")
    pages = cur.fetchall()

    out: list[InkPage] = []
    for i, p in enumerate(pages):
        page_order = p["page_order"] if p["page_order"] is not None else i
        page_id = p["id"]

        cur.execute(
            "SELECT bytes FROM blobs WHERE owner_id = ? AND ordinal = 0",
            (page_id,),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            continue

        b = row[0]
        if not (isinstance(b, (bytes, bytearray)) and b[:8] == PNG_MAGIC):
            continue

        page_id_hex = page_id.hex() if isinstance(page_id, (bytes, bytearray)) else str(page_id)
        out.append(InkPage(order=int(page_order), page_id_hex=page_id_hex, png_bytes=bytes(b)))

    con.close()
    out.sort(key=lambda x: x.order)
    return out
