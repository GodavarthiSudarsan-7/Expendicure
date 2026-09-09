"""Phase 13 — deterministic savings-goal progress engine."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import SavingsGoal
from decision.goal_progress import (
    compute_goal_progress, STATUS_ACHIEVED, STATUS_ON_TRACK, STATUS_BEHIND, STATUS_UNKNOWN,
)

D = Decimal
AS_OF = date(2026, 9, 30)


def goal(**kw):
    base = dict(id=1, student_id=1, name="Laptop", target_amount=D("50000.00"),
                current_amount=D("30000.00"), monthly_contribution=D("5000.00"),
                target_date=date(2027, 3, 31), status="active")
    base.update(kw)
    return SavingsGoal(**base)


def test_basic_progress_numbers():
    p = compute_goal_progress(goal(), as_of=AS_OF).to_dict()
    assert p["available"] is True
    assert p["target_amount"] == "50000.00"
    assert p["current_amount"] == "30000.00"
    assert p["remaining_amount"] == "20000.00"
    assert p["percent_complete"] == "60.00"


def test_percentage_rounds_two_places():
    p = compute_goal_progress(goal(current_amount=D("10000.00"), target_amount=D("30000.00")), as_of=AS_OF)
    assert p.percent_complete == D("33.33")


def test_on_track_when_contribution_finishes_before_target_date():
    # 20000 remaining / 5000 per month = 4 months -> ~2027-01, before 2027-03-31
    p = compute_goal_progress(goal(), as_of=AS_OF).to_dict()
    assert p["months_to_target"] == 4
    assert p["on_track"] is True
    assert p["status"] == STATUS_ON_TRACK


def test_behind_when_contribution_too_small():
    # 20000 remaining / 1000 per month = 20 months -> long past 2027-03-31
    p = compute_goal_progress(goal(monthly_contribution=D("1000.00")), as_of=AS_OF).to_dict()
    assert p["months_to_target"] == 20
    assert p["on_track"] is False
    assert p["status"] == STATUS_BEHIND


def test_required_monthly_contribution_to_hit_target_date():
    # 20000 remaining over 6 whole months -> ceil(3333.33..) = 3333.34
    p = compute_goal_progress(goal(), as_of=AS_OF).to_dict()
    assert p["months_until_target_date"] == 6
    assert p["required_monthly_contribution"] == "3333.34"
    assert p["contribution_gap"] == "0.00"          # planned 5000 >= required 3333.34


def test_contribution_gap_when_planned_is_short():
    p = compute_goal_progress(goal(monthly_contribution=D("2000.00")), as_of=AS_OF).to_dict()
    assert Decimal(p["contribution_gap"]) > 0


def test_achieved_goal():
    p = compute_goal_progress(goal(current_amount=D("50000.00")), as_of=AS_OF).to_dict()
    assert p["status"] == STATUS_ACHIEVED
    assert p["remaining_amount"] == "0.00"
    assert p["percent_complete"] == "100.00"
    assert p["on_track"] is True


def test_overfunded_is_clamped_not_negative():
    p = compute_goal_progress(goal(current_amount=D("60000.00")), as_of=AS_OF).to_dict()
    assert p["remaining_amount"] == "0.00"
    assert p["percent_complete"] == "100.00"


def test_zero_contribution_is_unknown_not_fabricated():
    p = compute_goal_progress(goal(monthly_contribution=D("0.00")), as_of=AS_OF).to_dict()
    assert p["monthly_contribution"] == "0.00"
    assert p["months_to_target"] is None
    assert p["estimated_completion_date"] is None
    assert p["on_track"] is None
    assert p["status"] in (STATUS_UNKNOWN, STATUS_BEHIND)


def test_zero_target_amount_is_unavailable():
    p = compute_goal_progress(goal(target_amount=D("0.00")), as_of=AS_OF)
    assert p.available is False
    assert "target" in p.reason


def test_target_date_in_the_past_no_negative_months():
    p = compute_goal_progress(goal(target_date=date(2026, 1, 1)), as_of=AS_OF).to_dict()
    assert p["months_until_target_date"] == 0
    assert p["required_monthly_contribution"] is None   # can't spread over 0 months


def test_pure_and_deterministic():
    import inspect
    import decision.goal_progress as mod
    src = inspect.getsource(mod)
    for banned in ("import flask", "import requests", "execute_query", "from finance_db", "ollama"):
        assert banned not in src
    a = compute_goal_progress(goal(), as_of=AS_OF).to_dict()
    b = compute_goal_progress(goal(), as_of=AS_OF).to_dict()
    assert a == b
