"""Phase 13 — goal-aware consequence engine + goal impact.

Backward compatibility: with no goals the goal-impact block and the decision
are exactly as in Phase 10.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import SavingsGoal
from finance.twin import TwinState
from decision import (
    evaluate_goal_impact, evaluate_consequence, select_primary_goal,
    DECISION_BUY, DECISION_SPEND_LESS, GOAL_ESCALATE_DELAY_MONTHS,
)

D = Decimal
AS_OF = date(2026, 9, 30)


def make_twin(*, current_balance="80000.00", safety_buffer="2000.00", disc="4000.00"):
    cb = D(current_balance)
    sb = D(safety_buffer)
    return TwinState(
        student_id=1, as_of=AS_OF, month="2026-09",
        opening_balance=D("0.00"), current_balance=cb,
        month_income=D("0.00"), month_spending=D("0.00"), month_net=D("0.00"),
        month_discretionary_spending=D(disc),
        spending_by_category={}, budgets={}, recurring=(),
        safety_buffer=sb, committed_upcoming=D("0.00"), committed_upcoming_horizon_days=30,
        discretionary_buffer=cb - sb,
    )


def goal(**kw):
    base = dict(id=1, student_id=1, name="Laptop", target_amount=D("50000.00"),
                current_amount=D("30000.00"), monthly_contribution=D("5000.00"),
                target_date=date(2027, 6, 30), status="active")
    base.update(kw)
    return SavingsGoal(**base)


# --------------------------------------------------- backward compatibility
def test_no_goals_keeps_the_phase10_contract_exactly():
    gi = evaluate_goal_impact(make_twin(), amount=D("4999"), purchase_date=AS_OF)
    assert gi.to_dict() == {
        "available": False, "delay_days": None,
        "reason": "no savings goal is configured for this account",
    }


def test_no_goals_decision_unchanged():
    r = evaluate_consequence(make_twin(), amount=D("4999"))
    assert r.goal_impact.available is False
    assert "goal_impact_unavailable" in r.reason_codes
    assert r.to_dict()["goal_delay_days"] is None
    assert r.to_dict()["goal_delay_months"] is None


# --------------------------------------------------- purchase does not affect goal
def test_small_purchase_that_does_not_cross_a_month_boundary_has_no_delay():
    # remaining 19000 -> ceil(19000/5000)=4 months; +500 -> 19500 -> still 4 months
    g = goal(current_amount=D("31000.00"))
    gi = evaluate_goal_impact(make_twin(), amount=D("500"), purchase_date=AS_OF, goals=[g])
    assert gi.available is True
    assert gi.delay_months == 0
    assert gi.delay_days == 0
    assert "unaffected" in gi.reason


# --------------------------------------------------- purchase delays goal
def test_purchase_delays_goal_by_whole_months_deterministically():
    # remaining_before 20000 -> 4 months; +6000 -> 26000 -> 6 months; delay 2
    gi = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF, goals=[goal()])
    assert gi.available is True
    assert gi.delay_months == 2
    assert gi.delay_days == (gi.estimated_completion_after - gi.estimated_completion_before).days
    assert gi.additional_contribution_required == D("6000.00")


def test_delay_reason_codes_flow_into_consequence():
    r = evaluate_consequence(make_twin(), amount=D("6000"), goals=[goal()])
    assert any(c.startswith("delays_goal_by_") for c in r.reason_codes)
    assert r.goal_impact.delay_months == 2


# --------------------------------------------------- no fabricated delay
def test_goal_without_contribution_is_unavailable_not_guessed():
    gi = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF,
                              goals=[goal(monthly_contribution=D("0.00"))])
    assert gi.available is False
    assert gi.delay_days is None
    assert "contribution" in gi.reason


def test_archived_goals_are_ignored():
    gi = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF,
                              goals=[goal(status="archived")])
    assert gi.available is False


# --------------------------------------------------- primary goal selection
def test_primary_goal_is_earliest_target_date_then_lowest_id():
    g_soon = goal(id=2, name="Trip", target_date=date(2027, 1, 31))
    g_late = goal(id=1, name="Laptop", target_date=date(2027, 12, 31))
    chosen = select_primary_goal([g_late, g_soon])
    assert chosen.name == "Trip"


def test_goal_id_overrides_primary_selection():
    g1 = goal(id=1, name="Laptop", target_date=date(2027, 1, 31))
    g2 = goal(id=2, name="Trip", target_date=date(2027, 12, 31))
    gi = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF,
                              goals=[g1, g2], goal_id=2)
    assert gi.goal_id == 2 and gi.goal_name == "Trip"


# --------------------------------------------------- decision escalation rule
def test_clean_buy_escalates_to_spend_less_on_a_big_goal_delay():
    # huge balance so the buffer is never the issue; 30000 spend delays a
    # 5000/month goal by >= 3 months -> documented escalation to SPEND_LESS
    r = evaluate_consequence(make_twin(current_balance="200000.00"),
                             amount=D("30000"), goals=[goal()])
    assert r.goal_impact.delay_months >= GOAL_ESCALATE_DELAY_MONTHS
    assert r.decision == DECISION_SPEND_LESS
    assert "delays_goal_significantly" in r.reason_codes
    assert r.largest_safe_amount is not None and r.largest_safe_amount < r.amount


def test_small_goal_delay_does_not_change_a_buy():
    r = evaluate_consequence(make_twin(current_balance="200000.00"),
                             amount=D("6000"), goals=[goal()])
    assert r.goal_impact.delay_months == 2            # < 3
    assert r.decision == DECISION_BUY                 # unchanged


def test_goal_never_rescues_an_unsafe_decision():
    # tiny balance -> AVOID regardless of goals
    r = evaluate_consequence(make_twin(current_balance="1000.00", safety_buffer="500.00"),
                             amount=D("5000"), goals=[goal()])
    assert r.decision == "AVOID"


# --------------------------------------------------- projections at target date
def test_projected_at_target_before_and_after():
    gi = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF, goals=[goal()])
    # both are capped at the target amount for display sanity
    assert gi.projected_at_target_before == D("50000.00")
    assert gi.projected_at_target_after <= D("50000.00")
    assert gi.shortfall_at_target >= D("0.00")


def test_to_dict_only_grows_when_available():
    unavailable = evaluate_goal_impact(make_twin(), amount=D("100"), purchase_date=AS_OF).to_dict()
    assert set(unavailable) == {"available", "delay_days", "reason"}
    available = evaluate_goal_impact(make_twin(), amount=D("6000"), purchase_date=AS_OF,
                                     goals=[goal()]).to_dict()
    assert {"goal_id", "goal_name", "delay_months", "target_amount"} <= set(available)
