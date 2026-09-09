"""Phase 10 — Financial Consequence Engine + goal impact + alternatives.

Pure and deterministic: no DB, no LLM, no network. Every number here is produced
by the real ``decision`` package running on top of the real ``finance`` kernel.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import RecurringTransaction
from finance.projection import project_daily_balances
from finance.twin import TwinState
from decision import build_alternatives, evaluate_consequence, evaluate_goal_impact
from decision.consequence_engine import (
    DECISION_BUY, DECISION_WAIT, DECISION_SPEND_LESS, DECISION_AVOID,
    RISK_HEALTHY, RISK_CAUTION, RISK_AT_RISK,
)

AS_OF = date(2026, 9, 10)
D = Decimal


def make_twin(*, current_balance="50000.00", safety_buffer="2000.00", recurring=()):
    cb = D(current_balance)
    sb = D(safety_buffer)
    return TwinState(
        student_id=1, as_of=AS_OF, month="2026-09",
        opening_balance=D("0.00"), current_balance=cb,
        month_income=D("0.00"), month_spending=D("0.00"), month_net=D("0.00"),
        month_discretionary_spending=D("0.00"),
        spending_by_category={}, budgets={}, recurring=tuple(recurring),
        safety_buffer=sb, committed_upcoming=D("0.00"), committed_upcoming_horizon_days=30,
        discretionary_buffer=cb - sb,
    )


def rec(amount, direction, days_ahead):
    d = AS_OF + timedelta(days=days_ahead)
    return RecurringTransaction(
        id=1, student_id=1, label="Salary" if direction == "credit" else "Rent",
        merchant_name="X", amount=D(str(amount)), direction=direction, cadence="monthly",
        next_date=d, day_of_month=d.day, weekday=None, active=True,
    )


# --------------------------------------------------- affordable, no impact
def test_affordable_no_meaningful_impact():
    r = evaluate_consequence(make_twin(current_balance="50000.00"), amount="50")
    assert r.decision == DECISION_BUY
    assert r.risk_before == RISK_HEALTHY and r.risk_after == RISK_HEALTHY
    assert r.risk_change == "unchanged"
    assert r.buffer_breached_after is False
    assert r.affordable_today is True and r.safe_to_spend is True
    assert "no_meaningful_impact" in r.reason_codes


# ------------------------------------------------ affordable but damages buffer
def test_affordable_but_damages_buffer_recommends_spend_less():
    r = evaluate_consequence(make_twin(current_balance="3000.00", safety_buffer="2000.00"),
                             amount="700")
    assert r.buffer_breached_after is False            # min 2300 stays above 2000
    assert r.risk_before == RISK_HEALTHY and r.risk_after == RISK_CAUTION
    assert r.risk_change == "worsened"
    assert r.decision == DECISION_SPEND_LESS
    assert r.largest_safe_amount is not None
    assert "reduces_minimum_balance" in r.reason_codes


# ------------------------------------------- purchase pushes below safety buffer
def test_below_buffer_no_recovery_recommends_spend_less():
    r = evaluate_consequence(make_twin(current_balance="5500.00", safety_buffer="2000.00"),
                             amount="5000")
    assert r.minimum_balance_after == D("500.00")
    assert r.buffer_breached_after is True
    assert r.risk_after == RISK_AT_RISK
    assert r.risk_change == "worsened"
    assert r.recommended_wait_days is None             # no income -> nothing recovers it
    assert r.decision == DECISION_SPEND_LESS           # a smaller amount is still safe
    assert "breaches_safety_buffer" in r.reason_codes


def test_below_buffer_with_incoming_salary_recommends_wait():
    twin = make_twin(current_balance="5500.00", safety_buffer="2000.00",
                     recurring=[rec("5000", "credit", 8)])
    r = evaluate_consequence(twin, amount="5000")
    assert r.buffer_breached_after is True
    assert r.recommended_wait_days is not None and r.recommended_wait_days <= 10
    assert r.decision == DECISION_WAIT
    assert any(c.startswith("recovers_in_") for c in r.reason_codes)


def test_overdraft_is_avoid():
    r = evaluate_consequence(make_twin(current_balance="1000.00", safety_buffer="0.00"),
                             amount="1500")
    assert r.minimum_balance_after < 0
    assert r.safe_to_spend is False
    assert r.decision == DECISION_AVOID
    assert "projected_overdraft" in r.reason_codes


def test_not_affordable_today_is_avoid_even_if_it_recovers_later():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00",
                     recurring=[rec("9000", "credit", 3)])
    r = evaluate_consequence(twin, amount="1500")
    assert r.affordable_today is False
    assert r.decision == DECISION_AVOID


# --------------------------------------------------------- invalid inputs
@pytest.mark.parametrize("bad", ["0", "-5", "abc", "NaN", "Infinity", 1.5])
def test_invalid_amount_raises(bad):
    with pytest.raises(ValueError):
        evaluate_consequence(make_twin(), amount=bad)


def test_past_purchase_date_raises():
    with pytest.raises(ValueError):
        evaluate_consequence(make_twin(), amount="100", purchase_date=date(2026, 1, 1))


def test_future_purchase_date_is_allowed():
    r = evaluate_consequence(make_twin(), amount="100",
                             purchase_date=AS_OF + timedelta(days=5))
    assert r.purchase_date == AS_OF + timedelta(days=5)


def test_optional_category_and_description():
    r = evaluate_consequence(make_twin(), amount="100")
    assert r.category is None and r.description is None
    r2 = evaluate_consequence(make_twin(), amount="100",
                              category="electronics", description="headphones")
    assert r2.category == "electronics" and r2.description == "headphones"


# --------------------------------------------------- purity / determinism
def test_engine_module_has_no_db_or_network_path():
    import inspect
    import decision.consequence_engine as mod
    src = inspect.getsource(mod)
    for banned in ("execute_query", "commit", "import flask", "import requests",
                   "ollama", "openai", "anthropic"):
        assert banned not in src.lower()


def test_twin_not_mutated_and_baseline_is_a_plain_projection():
    twin = make_twin(current_balance="8000.00", safety_buffer="2000.00",
                     recurring=[rec("1500", "debit", 9)])
    snapshot = (twin.current_balance, twin.recurring, twin.safety_buffer, twin.as_of)

    r = evaluate_consequence(twin, amount="1000")

    assert (twin.current_balance, twin.recurring, twin.safety_buffer, twin.as_of) == snapshot
    # the BASELINE minimum is exactly what the shared kernel produces with no purchase
    plain = project_daily_balances(twin, horizon_days=30)
    assert r.minimum_balance_before == plain.min_balance == D("6500.00")
    # fully deterministic: identical inputs -> identical dict
    assert evaluate_consequence(twin, amount="1000").to_dict() == r.to_dict()


def test_scenario_projection_is_hypothetical_only():
    twin = make_twin(current_balance="4000.00", safety_buffer="2000.00")
    evaluate_consequence(twin, amount="1000")           # run a scenario
    r2 = evaluate_consequence(twin, amount="1")         # a later baseline is untouched
    assert r2.minimum_balance_before == D("4000.00")


def test_decimal_precision_two_places_everywhere():
    r = evaluate_consequence(make_twin(current_balance="1234.567", safety_buffer="2000.00"),
                             amount="33.333")
    d = r.to_dict()
    for key in ("amount", "current_balance", "buffer_impact", "minimum_balance_before",
                "minimum_balance_after", "month_end_balance_before", "month_end_balance_after",
                "safety_buffer", "buffer_headroom_before", "buffer_headroom_after"):
        assert isinstance(d[key], str) and len(d[key].split(".")[1]) == 2


def test_buffer_impact_is_negative_amount():
    r = evaluate_consequence(make_twin(), amount="4999")
    assert r.buffer_impact == D("-4999.00")


def test_to_dict_is_json_safe():
    import json
    d = evaluate_consequence(make_twin(), amount="100", category="c", description="d").to_dict()
    json.dumps(d)  # must not raise
    assert d["goal_delay_days"] is None
    assert d["goal_impact"] == {"available": False, "delay_days": None,
                                "reason": "no savings goal is configured for this account"}


# --------------------------------------------------------------- goal impact
def test_goal_impact_is_explicitly_unavailable_not_fabricated():
    gi = evaluate_goal_impact(make_twin(), amount=D("100.00"), purchase_date=AS_OF)
    assert gi.available is False
    assert gi.delay_days is None
    assert "no savings goal" in gi.reason
    r = evaluate_consequence(make_twin(), amount="100")
    assert r.goal_impact.available is False
    assert "goal_impact_unavailable" in r.reason_codes


# --------------------------------------------------------------- alternatives
def test_alternatives_always_include_buy_now():
    twin = make_twin(current_balance="50000.00")
    base = evaluate_consequence(twin, amount="500")
    alts = build_alternatives(twin, base=base, amount="500")
    assert alts[0].kind == "buy_now"
    assert alts[0].amount == D("500.00")


def test_alternatives_offer_wait_when_a_recovery_day_exists():
    twin = make_twin(current_balance="5500.00", safety_buffer="2000.00",
                     recurring=[rec("5000", "credit", 8)])
    base = evaluate_consequence(twin, amount="5000")
    alts = {a.kind: a for a in build_alternatives(twin, base=base, amount="5000")}
    assert "wait" in alts
    assert alts["wait"].wait_days == base.recommended_wait_days
    assert alts["wait"].safe is True                    # re-scored by the same engine
    assert alts["wait"].decision == DECISION_BUY


def test_alternatives_offer_spend_less_scored_by_the_engine():
    twin = make_twin(current_balance="5500.00", safety_buffer="2000.00")
    base = evaluate_consequence(twin, amount="5000")
    alts = {a.kind: a for a in build_alternatives(twin, base=base, amount="5000")}
    assert "spend_less" in alts
    assert alts["spend_less"].amount == base.largest_safe_amount
    assert alts["spend_less"].amount < D("5000.00")
    assert alts["spend_less"].safe is True


def test_alternatives_do_not_offer_an_impossible_wait():
    twin = make_twin(current_balance="5500.00", safety_buffer="2000.00")   # no income
    base = evaluate_consequence(twin, amount="5000")
    assert base.recommended_wait_days is None
    kinds = {a.kind for a in build_alternatives(twin, base=base, amount="5000")}
    assert "wait" not in kinds
