from __future__ import annotations

import re
from datetime import date

from .types import DateAssignment, DateCandidate, DatePolicy

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _month_token_to_int(tok: str) -> int | None:
    tok = tok.strip().lower()
    if not tok:
        return None
    tok = tok.replace("|", "l")
    tok = re.sub(r"[^a-z]", "", tok)
    if len(tok) >= 3:
        pref = tok[:3]
        for name, num in MONTHS.items():
            if name.startswith(pref):
                return num
    return MONTHS.get(tok)


def _dow_to_wanted(dow: str) -> int | None:
    dow = dow.strip().lower()
    return {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }.get(dow)


def _fix_date_by_dow(d: date, dow: str, *, max_delta_days: int = 3) -> date:
    want = _dow_to_wanted(dow)
    if want is None or d.weekday() == want:
        return d

    candidates: list[tuple[int, date]] = []
    for delta in range(-max_delta_days, max_delta_days + 1):
        if delta == 0:
            continue
        dd = d.fromordinal(d.toordinal() + delta)
        if dd.weekday() == want:
            candidates.append((delta, dd))
    if not candidates:
        return d
    candidates.sort(key=lambda x: (abs(x[0]), x[0] > 0))
    return candidates[0][1]


def candidate_to_date(c: DateCandidate) -> date | None:
    try:
        y = int(c.year_token)
        da = int(c.day_token)
    except Exception:
        return None
    mo = _month_token_to_int(c.month_token)
    if not mo:
        return None
    try:
        d = date(y, mo, da)
    except ValueError:
        return None
    return _fix_date_by_dow(d, c.dow)


def repair_with_context(c: DateCandidate, *, prev: date, policy: DatePolicy) -> DateAssignment | None:
    """Attempt to repair a candidate using expected chronology.

    Handles common OCR mistakes:
    - wrong month token (JANUARY misread as JUNE)
    - day-of-month digit drop (27 misread as 7)

    We search for a date near (prev + 1 day) matching the candidate's weekday.
    """

    want = _dow_to_wanted(c.dow)
    if want is None:
        return None

    try:
        y = int(c.year_token)
        ocr_day = int(c.day_token)
    except Exception:
        return None

    parsed_month = _month_token_to_int(c.month_token)

    target = prev.fromordinal(prev.toordinal() + 1)
    best: tuple[float, date] | None = None

    for delta in range(-policy.max_window_days, policy.max_window_days + 1):
        cand = target.fromordinal(target.toordinal() + delta)
        if cand.year != y:
            continue
        if cand.weekday() != want:
            continue

        score = abs(delta)

        if parsed_month is not None and cand.month != parsed_month:
            score += 3.0

        if cand.day != ocr_day:
            if str(cand.day).endswith(str(ocr_day)):
                score += 0.5
            else:
                score += 2.0

        if best is None or score < best[0]:
            best = (score, cand)

    if not best:
        return None

    score, d = best
    if abs((d - target).days) > 7:
        return None

    return DateAssignment(d=d, method="repaired", confidence=max(0.2, 1.0 - (score / 10.0)))
