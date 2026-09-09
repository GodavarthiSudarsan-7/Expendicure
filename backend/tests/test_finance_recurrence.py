"""Shared recurrence-date arithmetic. Pure — no DB, no Flask."""

from datetime import date

import pytest

from finance.recurrence import (
    add_months,
    days_in_month,
    monthly_occurrences,
    weekly_occurrences,
    occurrences_for_recurring,
)


def test_days_in_month_february():
    assert days_in_month(2026, 2) == 28
    assert days_in_month(2028, 2) == 29  # leap


def test_add_months_basic():
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


def test_add_months_clamps_day_and_recovers():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)   # Feb clamp
    assert add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)   # recovers to 31
    assert add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)   # Apr clamp


def test_add_months_year_rollover_backwards_not_needed_but_forward_ok():
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_monthly_occurrences_spans_year_boundary():
    occ = monthly_occurrences(date(2026, 11, 19), date(2027, 2, 28))
    assert occ == [date(2026, 11, 19), date(2026, 12, 19), date(2027, 1, 19), date(2027, 2, 19)]


def test_monthly_occurrences_february_clamp():
    occ = monthly_occurrences(date(2026, 1, 31), date(2026, 4, 30))
    assert occ == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_weekly_occurrences_step_seven():
    occ = weekly_occurrences(date(2026, 9, 9), date(2026, 9, 30))
    assert occ == [date(2026, 9, 9), date(2026, 9, 16), date(2026, 9, 23), date(2026, 9, 30)]


def test_occurrence_on_exact_end_included():
    occ = weekly_occurrences(date(2026, 9, 9), date(2026, 9, 23))
    assert occ[-1] == date(2026, 9, 23)


class _Rec:
    def __init__(self, next_date, cadence, day_of_month=None, weekday=None):
        self.next_date = next_date
        self.cadence = cadence
        self.day_of_month = day_of_month
        self.weekday = weekday


def test_occurrences_for_recurring_monthly_from_stale_next_date():
    # next_date in the past -> past occurrence skipped, future ones kept
    rec = _Rec(date(2026, 8, 19), "monthly")
    occ = occurrences_for_recurring(rec, start=date(2026, 9, 9), end=date(2026, 11, 30))
    assert occ == [date(2026, 9, 19), date(2026, 10, 19), date(2026, 11, 19)]


def test_occurrences_for_recurring_next_date_beyond_end():
    rec = _Rec(date(2027, 1, 1), "monthly")
    assert occurrences_for_recurring(rec, start=date(2026, 9, 9), end=date(2026, 12, 31)) == []


def test_occurrences_for_recurring_weekly():
    rec = _Rec(date(2026, 9, 12), "weekly")
    occ = occurrences_for_recurring(rec, start=date(2026, 9, 9), end=date(2026, 10, 3))
    assert occ == [date(2026, 9, 12), date(2026, 9, 19), date(2026, 9, 26), date(2026, 10, 3)]
