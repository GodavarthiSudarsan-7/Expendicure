"""Unit tests for the deterministic affordability engine. Pure — no DB, no LLM."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import RecurringTransaction
from finance.twin import TwinState
from finance.affordability import (
    check_affordability,
    AffordabilityResult,
    TOOL_SPEC,
    VERDICT_AFFORDABLE,
    VERDICT_TIGHT,
    VERDICT_NOT_AFFORDABLE,
)

AS_OF = date(2026, 9, 9)
D = Decimal


def make_twin(*, current_balance="10000.00", safety_buffer="2000.00",
              recurring=(), budgets=None, spending_by_category=None,
              committed_upcoming="0.00", discretionary_buffer=None, as_of=AS_OF):
    cb = D(current_balance)
    sb = D(safety_buffer)
    if discretionary_buffer is None:
        discretionary_buffer = cb - D(committed_upcoming) - sb
    return TwinState(
        student_id=1,
        as_of=as_of,
        month=f"{as_of.year:04d}-{as_of.month:02d}",
        opening_balance=D("0.00"),
        current_balance=cb,
        month_income=D("0.00"),
        month_spending=D("0.00"),
        month_net=D("0.00"),
        month_discretionary_spending=D("0.00"),
        spending_by_category=dict(spending_by_category or {}),
        budgets=dict(budgets or {}),
        recurring=tuple(recurring),
        safety_buffer=sb,
        committed_upcoming=D(committed_upcoming),
        committed_upcoming_horizon_days=30,
        discretionary_buffer=D(discretionary_buffer),
    )


def rec(amount, direction, next_date, *, rid=1):
    return RecurringTransaction(
        id=rid, student_id=1, label=f"rec{rid}", merchant_name="M",
        amount=D(str(amount)), direction=direction, cadence="monthly",
        next_date=next_date, day_of_month=next_date.day, active=True,
    )


# --------------------------------------------------------------------- verdict

def test_clearly_affordable():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=100)
    assert r.verdict == VERDICT_AFFORDABLE
    assert r.projected_min_balance == D("9900.00")
    assert r.breaches == ()
    assert r.score == 100  # margin hugely exceeds 10% of amount


def test_not_affordable_when_min_below_buffer_even_if_positive():
    # min balance 1500 > 0 but < 2000 buffer -> not_affordable
    twin = make_twin(current_balance="3000.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=1500)
    assert r.projected_min_balance == D("1500.00")
    assert r.verdict == VERDICT_NOT_AFFORDABLE
    assert "safety_buffer" in r.breaches
    assert "overdraft" not in r.breaches


def test_overdraft_breach_and_reason():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00")
    r = check_affordability(twin, amount=1500)
    assert r.projected_min_balance == D("-500.00")
    assert r.verdict == VERDICT_NOT_AFFORDABLE
    assert "overdraft" in r.breaches
    assert any(x.code == "negative_balance" for x in r.reasons)


def test_tight_when_margin_below_ten_percent_of_amount():
    # min balance 2050, buffer 2000, margin 50 < 0.10 * 1000 = 100 -> tight
    twin = make_twin(current_balance="3050.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=1000)
    assert r.projected_min_balance == D("2050.00")
    assert r.verdict == VERDICT_TIGHT
    assert r.breaches == ()
    assert any(x.code == "thin_margin" for x in r.reasons)


def test_affordable_when_margin_at_or_above_ten_percent():
    # min balance 2100, buffer 2000, margin 100 == 0.10 * 1000 -> affordable
    twin = make_twin(current_balance="3100.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=1000)
    assert r.verdict == VERDICT_AFFORDABLE


# ----------------------------------------------------------------------- score

def test_score_matches_exact_formula_example():
    # amount=4000, projected_min_balance=0, safety_buffer=2000  ->  score 25
    twin = make_twin(current_balance="4000.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=4000)
    assert r.projected_min_balance == D("0.00")
    assert r.score == 25
    assert r.verdict == VERDICT_NOT_AFFORDABLE


def test_score_clamps_to_zero():
    twin = make_twin(current_balance="1000.00", safety_buffer="5000.00")
    r = check_affordability(twin, amount=1000)   # min = 0, buffer 5000, amount 1000
    # raw = 50 + 50*(0-5000)/1000 = 50 - 250 = -200 -> clamp 0
    assert r.score == 0


def test_score_clamps_to_hundred():
    twin = make_twin(current_balance="1000000.00", safety_buffer="0.00")
    r = check_affordability(twin, amount=10)
    assert r.score == 100


def test_score_monotonic_in_projected_min_balance():
    scores = []
    for cb in ("2500.00", "3000.00", "3500.00", "4000.00", "5000.00"):
        twin = make_twin(current_balance=cb, safety_buffer="2000.00")
        scores.append(check_affordability(twin, amount=1000).score)
    assert scores == sorted(scores)


def test_score_monotonic_decreasing_in_safety_buffer():
    scores = []
    for sb in ("0.00", "1000.00", "2000.00", "3000.00"):
        twin = make_twin(current_balance="5000.00", safety_buffer=sb)
        scores.append(check_affordability(twin, amount=1000).score)
    assert scores == sorted(scores, reverse=True)


def test_score_uses_max_amount_one_denominator():
    # amount 0.50 -> denominator clamps to 1
    twin = make_twin(current_balance="10.50", safety_buffer="0.00")
    r = check_affordability(twin, amount="0.50")
    # min = 10.00, buffer 0, denom 1 -> raw = 50 + 50*10 = 550 -> clamp 100
    assert r.score == 100


# --------------------------------------------------- category budget (no penalty)

def test_category_budget_breach_is_reported_but_does_not_change_verdict_or_score():
    base = make_twin(current_balance="10000.00", safety_buffer="2000.00")
    without = check_affordability(base, amount=500)

    budgeted = make_twin(
        current_balance="10000.00", safety_buffer="2000.00",
        budgets={"Electronics": D("100.00")},
        spending_by_category={"Electronics": D("0.00")},
    )
    with_cat = check_affordability(budgeted, amount=500, category="Electronics")

    assert "category_budget" in with_cat.breaches
    assert any(x.code == "category_over_budget" for x in with_cat.reasons)
    # identical financial situation -> identical verdict and score
    assert with_cat.verdict == without.verdict
    assert with_cat.score == without.score


def test_no_category_budget_breach_when_within_remaining():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00",
                     budgets={"Food": D("300.00")},
                     spending_by_category={"Food": D("50.00")})
    r = check_affordability(twin, amount=100, category="Food")  # 100 <= 250 remaining
    assert "category_budget" not in r.breaches


def test_no_category_breach_when_no_budget_for_category():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=9999, category="Yacht")
    assert "category_budget" not in r.breaches


def test_category_budget_lookup_is_case_insensitive():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00",
                     budgets={"Electronics": D("100.00")})
    r = check_affordability(twin, amount=500, category="electronics")
    assert "category_budget" in r.breaches


# ----------------------------------------------------------------- projection

def test_recurring_income_before_dip_lifts_the_minimum():
    twin = make_twin(current_balance="1000.00", safety_buffer="500.00",
                     recurring=[rec("5000", "credit", AS_OF + timedelta(days=2))])
    # purchase 4000 today -> dips to -3000 today (before the income) -> not_affordable
    r_today = check_affordability(twin, amount=4000)
    assert r_today.projected_min_balance == D("-3000.00")
    assert r_today.verdict == VERDICT_NOT_AFFORDABLE
    # same purchase dated after the income arrives -> min is 1000 (day 0), then rises
    r_later = check_affordability(twin, amount=4000, purchase_date=AS_OF + timedelta(days=5))
    assert r_later.projected_min_balance == D("1000.00")


def test_pre_existing_shortfall_reason():
    twin = make_twin(current_balance="1000.00", safety_buffer="2000.00")
    r = check_affordability(twin, amount=10)
    # baseline already below buffer
    assert any(x.code == "pre_existing_shortfall" for x in r.reasons)


def test_future_purchase_within_horizon_applied_on_its_date():
    twin = make_twin(current_balance="5000.00", safety_buffer="1000.00",
                     recurring=[rec("2000", "debit", AS_OF + timedelta(days=10))])
    r = check_affordability(twin, amount=1000, purchase_date=AS_OF + timedelta(days=20),
                            horizon_days=30)
    # 5000 -> 3000 (day10 rent) -> 2000 (day20 purchase)
    assert r.projected_min_balance == D("2000.00")
    assert r.projected_min_date == AS_OF + timedelta(days=20)


def test_purchase_beyond_horizon_extends_projection():
    twin = make_twin(current_balance="5000.00", safety_buffer="1000.00")
    r = check_affordability(twin, amount=1000, purchase_date=AS_OF + timedelta(days=90),
                            horizon_days=30)
    assert r.horizon_days == 90
    assert r.projected_min_balance == D("4000.00")


# --------------------------------------------------------------------- errors

def test_zero_amount_raises():
    with pytest.raises(ValueError):
        check_affordability(make_twin(), amount=0)


def test_negative_amount_raises():
    with pytest.raises(ValueError):
        check_affordability(make_twin(), amount="-5")


def test_past_purchase_date_raises():
    with pytest.raises(ValueError):
        check_affordability(make_twin(), amount=100, purchase_date=AS_OF - timedelta(days=1))


def test_float_amount_rejected():
    with pytest.raises(ValueError):
        check_affordability(make_twin(), amount=100.5)


# -------------------------------------------------------------- result / schema

def test_to_dict_schema_and_types():
    twin = make_twin(current_balance="3000.00", safety_buffer="2000.00",
                     committed_upcoming="150.00")
    d = check_affordability(twin, amount=1500, category="Food").to_dict()
    expected_keys = {
        "verdict", "score", "amount", "category", "as_of", "purchase_date",
        "horizon_days", "current_balance", "baseline_min_balance",
        "projected_min_balance", "projected_min_date", "safety_buffer",
        "committed_upcoming", "discretionary_buffer_before",
        "discretionary_buffer_after", "breaches", "reasons",
    }
    assert set(d) == expected_keys
    assert isinstance(d["score"], int)
    assert d["verdict"] in {"affordable", "tight", "not_affordable"}
    for k in ("amount", "current_balance", "projected_min_balance", "safety_buffer",
              "baseline_min_balance", "committed_upcoming",
              "discretionary_buffer_before", "discretionary_buffer_after"):
        assert isinstance(d[k], str) and len(d[k].split(".")[1]) == 2
    assert d["as_of"] == "2026-09-09"
    assert isinstance(d["breaches"], list)
    assert all(set(r) == {"code", "severity", "message"} for r in d["reasons"])


def test_discretionary_buffer_after_is_before_minus_amount():
    twin = make_twin(current_balance="5000.00", safety_buffer="1000.00",
                     committed_upcoming="500.00")
    r = check_affordability(twin, amount=800)
    assert r.discretionary_buffer_before == D("3500.00")   # 5000 - 500 - 1000
    assert r.discretionary_buffer_after == D("2700.00")    # - 800


def test_deterministic_repeat_calls():
    twin = make_twin(current_balance="3333.33", safety_buffer="1234.56",
                     recurring=[rec("777.77", "debit", AS_OF + timedelta(days=3))])
    a = check_affordability(twin, amount="456.78", category="Food").to_dict()
    b = check_affordability(twin, amount="456.78", category="Food").to_dict()
    assert a == b


def test_tool_spec_shape():
    assert TOOL_SPEC["name"] == "check_affordability"
    assert TOOL_SPEC["parameters"]["required"] == ["amount"]
    assert set(TOOL_SPEC["parameters"]["properties"]) == {
        "amount", "category", "date", "horizon_days"
    }
