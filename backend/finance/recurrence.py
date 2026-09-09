"""Deterministic recurrence-date arithmetic.

Shared by ``finance.simulate`` (hypothetical recurring scenarios) and
``finance.forecast`` (projecting stored / detected recurring items). Pure
stdlib + ``datetime``; no Flask, no DB, no LLM.

Month/year/February/day-of-month handling is explicit:
- a monthly series anchored on day D lands on ``min(D, days_in_month)`` each
  month and *recovers* to D in months that are long enough (e.g. Jan 31 -> Feb
  28 -> Mar 31), because D is re-clamped from the original value every month;
- month arithmetic rolls the year over (Dec -> Jan);
- a weekly series simply steps 7 days.
"""

import calendar
import re
from datetime import date, timedelta
from typing import List, Optional

__all__ = [
    "days_in_month",
    "add_months",
    "monthly_occurrences",
    "weekly_occurrences",
    "occurrences_for_recurring",
    "normalise_merchant",
    "MERCHANT_KEY_LEN",
]

# Deterministic merchant-name normalisation, shared by recurrence detection
# (finance.forecast) and duplicate / new-merchant detection (finance.anomaly):
# lower-case, drop every non-alphanumeric character, keep the first
# MERCHANT_KEY_LEN characters.
MERCHANT_KEY_LEN = 24


def normalise_merchant(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())[:MERCHANT_KEY_LEN]


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(anchor: date, n: int, *, day: Optional[int] = None) -> date:
    """``anchor`` shifted ``n`` months, landing on ``day`` (default ``anchor.day``),
    clamped to the target month's length. Year rolls over."""
    target_day = day if day is not None else anchor.day
    total = (anchor.year * 12 + (anchor.month - 1)) + n
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(target_day, days_in_month(year, month)))


def monthly_occurrences(anchor: date, end: date, *, day_of_month: Optional[int] = None) -> List[date]:
    """Every monthly occurrence in ``[anchor, end]``. Occurrence 0 is ``anchor``
    itself (unless a mismatched ``day_of_month`` pushes it earlier, in which case
    it is skipped)."""
    dom = day_of_month or anchor.day
    year, month = anchor.year, anchor.month
    out: List[date] = []
    while True:
        occ = date(year, month, min(dom, days_in_month(year, month)))
        if occ > end:
            break
        if occ >= anchor:
            out.append(occ)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def weekly_occurrences(anchor: date, end: date, *, weekday: Optional[int] = None) -> List[date]:
    """Every weekly occurrence in ``[anchor, end]``, stepping 7 days. If
    ``weekday`` (0=Mon..6=Sun) is given, the first occurrence is shifted forward
    to that weekday."""
    first = anchor
    if weekday is not None:
        first = anchor + timedelta(days=(weekday - anchor.weekday()) % 7)
    out: List[date] = []
    occ = first
    while occ <= end:
        if occ >= anchor:
            out.append(occ)
        occ += timedelta(days=7)
    return out


def occurrences_for_recurring(rec, *, start: date, end: date) -> List[date]:
    """All occurrence dates of a ``RecurringTransaction`` in ``[start, end]``.

    Anchored on ``rec.next_date`` (authoritative). Monthly series follow
    ``rec.day_of_month`` when set, else ``rec.next_date.day``. Weekly series
    step 7 days from ``rec.next_date`` (``rec.weekday`` is not re-enforced —
    ``next_date`` wins). Occurrences before ``start`` (e.g. a stale
    ``next_date``) are skipped, not rolled — the future ones still project.
    """
    if rec.next_date > end:
        return []
    if rec.cadence == "monthly":
        occ = monthly_occurrences(rec.next_date, end, day_of_month=rec.day_of_month)
    elif rec.cadence == "weekly":
        occ = weekly_occurrences(rec.next_date, end, weekday=None)
    else:
        occ = [rec.next_date] if rec.next_date <= end else []
    return [d for d in occ if d >= start]
