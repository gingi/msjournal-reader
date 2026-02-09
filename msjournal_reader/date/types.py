from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

DateMethod = Literal["parsed", "repaired", "inferred", "none"]


@dataclass(frozen=True)
class DateCandidate:
    """A parsed date header candidate from a single page."""

    dow: str
    month_token: str
    day_token: str
    year_token: str
    source: str  # the line(s) used to parse


@dataclass(frozen=True)
class DateAssignment:
    """Final assigned date for a page (or None if unassigned)."""

    d: date | None
    method: DateMethod
    confidence: float = 1.0
    note: str | None = None


@dataclass(frozen=True)
class DatePolicy:
    """Controls optional date heuristics.

    - parse-only is always attempted when date grouping is enabled.
    - repair and inference are optional.
    """

    allow_repair: bool = True
    allow_infer_continuations: bool = True

    # For repairing/inference: how far from the expected next-day we are willing to search.
    max_window_days: int = 14

    # AUTO mode detection: require at least N parseable dates within the first M pages.
    auto_min_hits: int = 3
    auto_scan_pages: int = 20
