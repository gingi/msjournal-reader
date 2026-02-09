from __future__ import annotations

import re
from dataclasses import dataclass

from .types import DateCandidate

# A permissive header pattern: DOW, MONTH D, YYYY
DATE_LINE_RE = re.compile(
    r"^(?P<dow>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s+"
    r"(?P<month>[a-zA-Z]{3,12})\s+"
    r"(?P<day>\d{1,2})\s*,?\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)

DOW_ONLY_RE = re.compile(r"^(?P<dow>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*,?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ParseResult:
    candidate: DateCandidate


def parse_dow_month_day_year(lines: list[str]) -> DateCandidate | None:
    """Try parse from the first few non-empty lines.

    Also handles the Azure OCR quirk where DOW is on its own line, and the rest on the next line.
    """

    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    if not lines:
        return None

    # Two-line stitch: "FRIDAY" + "JANUARY 10, 2025"
    if len(lines) >= 2 and DOW_ONLY_RE.fullmatch(lines[0]):
        stitched = f"{lines[0]} {lines[1]}"
        m = DATE_LINE_RE.match(stitched)
        if m:
            return DateCandidate(
                dow=str(m.group("dow")),
                month_token=str(m.group("month")),
                day_token=str(m.group("day")),
                year_token=str(m.group("year")),
                source=stitched,
            )

    for ln in lines[:10]:
        m = DATE_LINE_RE.match(ln)
        if not m:
            continue
        return DateCandidate(
            dow=str(m.group("dow")),
            month_token=str(m.group("month")),
            day_token=str(m.group("day")),
            year_token=str(m.group("year")),
            source=ln,
        )

    return None
