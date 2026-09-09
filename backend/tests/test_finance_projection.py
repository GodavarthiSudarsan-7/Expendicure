"""Unit tests for the shared projection kernel. Pure — no DB, no Flask."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import RecurringTransaction
from finance.projection import (
    ProjectionEvent,
    project_daily_balances,
    recurring_events,
)

AS_OF = date(2026, 4, 15)


class FakeTwin:
    """Only the attributes the kernel reads: as_of, current_balance, recurring."""

    def __init__(self, current_balance="1000.00", recurring=()):
        self.as_of = AS_OF
        self.current_balance = Decimal(current_balance)
        self.recurring = tuple(recurring)


def rec(amount, direction, next_date, *, rid=1, cadence="monthly"):
    return RecurringTransaction(
        id=rid, student_id=1, label=f"rec{rid}", merchant_name="M",
        amount=Decimal(str(amount)), direction=direction, cadence=cadence,
        next_date=next_date, day_of_month=next_date.day, active=True,
    )


def test_flat_line_when_no_events():
    p = project_daily_balances(FakeTwin("500.00"), horizon_days=30)
    assert len(p.points) == 31                      # as_of .. as_of+30 inclusive
    assert p.points[0].date == AS_OF
    assert p.points[-1].date == AS_OF + timedelta(days=30)
    assert all(bp.balance == Decimal("500.00") for bp in p.points)
    assert p.start_balance == Decimal("500.00")
    assert p.min_balance == Decimal("500.00")
    assert p.min_date == AS_OF
    assert p.end_balance == Decimal("500.00")


def test_horizon_zero_gives_single_point():
    p = project_daily_balances(FakeTwin("100.00"), horizon_days=0)
    assert len(p.points) == 1
    assert p.points[0].date == AS_OF


def test_points_are_contiguous_daily_dates():
    p = project_daily_balances(FakeTwin(), horizon_days=10)
    for i, bp in enumerate(p.points):
        assert bp.date == AS_OF + timedelta(days=i)


def test_recurring_debit_steps_down_on_its_date():
    twin = FakeTwin("1000.00", [rec("300", "debit", AS_OF + timedelta(days=5))])
    p = project_daily_balances(twin, horizon_days=30)
    assert p.points[4].balance == Decimal("1000.00")   # day before
    assert p.points[5].balance == Decimal("700.00")    # on the date
    assert p.points[-1].balance == Decimal("700.00")   # stays
    assert p.min_balance == Decimal("700.00")
    assert p.min_date == AS_OF + timedelta(days=5)


def test_recurring_credit_steps_up():
    twin = FakeTwin("100.00", [rec("500", "credit", AS_OF + timedelta(days=3))])
    p = project_daily_balances(twin, horizon_days=10)
    assert p.points[2].balance == Decimal("100.00")
    assert p.points[3].balance == Decimal("600.00")


def test_recurring_outside_horizon_ignored():
    twin = FakeTwin("1000.00", [rec("300", "debit", AS_OF + timedelta(days=45))])
    p = project_daily_balances(twin, horizon_days=30)
    assert all(bp.balance == Decimal("1000.00") for bp in p.points)
    assert p.events == ()


def test_recurring_before_as_of_ignored():
    twin = FakeTwin("1000.00", [rec("300", "debit", AS_OF - timedelta(days=2))])
    p = project_daily_balances(twin, horizon_days=30)
    assert all(bp.balance == Decimal("1000.00") for bp in p.points)


def test_extra_event_beyond_horizon_extends_projection():
    twin = FakeTwin("1000.00")
    ev = ProjectionEvent(date=AS_OF + timedelta(days=60), amount=Decimal("-400"),
                         kind="purchase", label="laptop")
    p = project_daily_balances(twin, horizon_days=30, extra_events=[ev])
    assert p.points[-1].date == AS_OF + timedelta(days=60)
    assert p.points[-1].balance == Decimal("600.00")
    assert p.min_balance == Decimal("600.00")


def test_same_date_events_sum_order_independent():
    twin = FakeTwin("1000.00")
    d = AS_OF + timedelta(days=5)
    evs_a = [ProjectionEvent(d, Decimal("-100"), "purchase", "a"),
             ProjectionEvent(d, Decimal("200"), "recurring", "b")]
    evs_b = list(reversed(evs_a))
    pa = project_daily_balances(twin, horizon_days=10, extra_events=evs_a)
    pb = project_daily_balances(twin, horizon_days=10, extra_events=evs_b)
    assert [bp.balance for bp in pa.points] == [bp.balance for bp in pb.points]
    assert pa.points[5].balance == Decimal("1100.00")


def test_min_date_is_earliest_occurrence_of_minimum():
    twin = FakeTwin("1000.00", [
        rec("500", "debit", AS_OF + timedelta(days=5), rid=1),
        rec("500", "credit", AS_OF + timedelta(days=10), rid=2),
        rec("500", "debit", AS_OF + timedelta(days=15), rid=3),
    ])
    p = project_daily_balances(twin, horizon_days=30)
    # balance dips to 500 on day 5, back to 1000 on day 10, back to 500 on day 15
    assert p.min_balance == Decimal("500.00")
    assert p.min_date == AS_OF + timedelta(days=5)


def test_all_balances_are_two_places():
    twin = FakeTwin("1000.00", [rec("33.33", "debit", AS_OF + timedelta(days=2))])
    p = project_daily_balances(twin, horizon_days=5)
    for bp in p.points:
        assert bp.balance == bp.balance.quantize(Decimal("0.01"))


def test_recurring_events_helper_bounds():
    twin = FakeTwin("0", [
        rec("10", "debit", AS_OF, rid=1),                       # on as_of -> in
        rec("10", "debit", AS_OF + timedelta(days=30), rid=2),  # on horizon_end -> in
        rec("10", "debit", AS_OF + timedelta(days=31), rid=3),  # past -> out
    ])
    evs = recurring_events(twin, horizon_end=AS_OF + timedelta(days=30))
    assert {e.label for e in evs} == {"rec1", "rec2"}
