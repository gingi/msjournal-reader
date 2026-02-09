from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from .parsers import parse_dow_month_day_year
from .repair import candidate_to_date, repair_with_context
from .types import DateAssignment, DatePolicy


@dataclass(frozen=True)
class Page:
    doc: str
    page: int
    path: Path
    text: str


GroupMode = Literal["auto", "date", "page"]


def auto_detect_date_mode(pages: list[Page], policy: DatePolicy) -> bool:
    """Return True if we should attempt date grouping for this document."""

    hits = 0
    for p in pages[: policy.auto_scan_pages]:
        lines = p.text.splitlines()[:10]
        cand = parse_dow_month_day_year(lines)
        if not cand:
            continue
        if candidate_to_date(cand):
            hits += 1
        if hits >= policy.auto_min_hits:
            return True
    return False


def assign_dates(pages: list[Page], policy: DatePolicy) -> list[DateAssignment]:
    """Assign dates to pages (optional; pages may end up with None dates)."""

    # First pass: parse candidates and direct dates.
    assigns: list[DateAssignment] = []
    prev_d: date | None = None

    for p in pages:
        cand = parse_dow_month_day_year(p.text.splitlines()[:10])
        if not cand:
            assigns.append(DateAssignment(d=None, method="none", confidence=0.0))
            continue

        d = candidate_to_date(cand)
        if d and prev_d and policy.allow_repair:
            delta = (d - prev_d).days
            if delta < 0 or delta > 3:
                rep = repair_with_context(cand, prev=prev_d, policy=policy)
                if rep and rep.d:
                    d = rep.d
                    assigns.append(rep)
                    prev_d = d
                    continue

        if d:
            assigns.append(DateAssignment(d=d, method="parsed", confidence=1.0))
            prev_d = d
        else:
            assigns.append(DateAssignment(d=None, method="none", confidence=0.0))

    if not policy.allow_infer_continuations:
        return assigns

    # Second pass: infer dates for undated pages between known dates.
    known = [(i, a.d) for i, a in enumerate(assigns) if a.d is not None]
    for k in range(len(known) - 1):
        i0, d0 = known[k]
        i1, d1 = known[k + 1]
        if i1 <= i0 + 1:
            continue
        gap_pages = list(range(i0 + 1, i1))
        gap_days = (d1 - d0).days

        fill: date | None = None
        if gap_days == 1:
            fill = d0
        elif gap_days == 2:
            fill = d0.fromordinal(d0.toordinal() + 1)

        if not fill:
            continue

        for gi in gap_pages:
            if assigns[gi].d is None:
                assigns[gi] = DateAssignment(d=fill, method="inferred", confidence=0.3, note="neighbor-gap")

    # Trailing undated pages: treat as continuations of the last known date.
    if known:
        last_i, last_d = known[-1]
        for gi in range(last_i + 1, len(assigns)):
            if assigns[gi].d is None:
                assigns[gi] = DateAssignment(d=last_d, method="inferred", confidence=0.2, note="trailing")

    return assigns
