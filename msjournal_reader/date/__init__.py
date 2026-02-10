"""Date parsing/assignment utilities (optional).

Core philosophy: journals may not have dates (or may have dates in different formats).
The exporter/indexer should work page-first, with date-aware grouping as an optional layer.
"""

from .types import DateAssignment, DateCandidate, DatePolicy
from .assign import assign_dates, auto_detect_date_mode
