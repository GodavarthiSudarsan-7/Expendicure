"""Phase D pieces A-C: the 90-day safety engine.

Pure unit tests — a FakeRepo-free TwinState is built directly, no DB, no Flask.
Every expectation is hand-computed from the event stream so the test proves the
arithmetic rather than echoing it.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from decision.safety import (
    ACTION_REDUCE,
    ACTION_STOP,
    FAIL_AMOUNT_INCOMPLETE,
    FAIL_DEADLINE_MISSED,
    FAIL_MIN_BALANCE,
    FAIL_PAYMENT_OUTSIDE_HORIZON,
    PlanPayment,
    SAFETY_HORIZON_DAYS,
    SpendingChange,
    amount_safe_to_pay,
    build_baseline,
    earliest_date_for_full_payment,
    evaluate_plan,
    is_safe,
    simulate,
)
from finance.models import RecurringTransaction
from finance.money import money
from finance.twin import TwinState

AS_OF = date(2026, 10, 5)


def rec(label, amount, direction="debit", *, day=10, rid=1, cadence="monthly", flexibility="essential"):
    return RecurringTransaction(
        id=rid, student_id=1, label=label, merchant_name=label,
        amount=Decimal(str(amount)), direction=direction, cadence=cadence,
        next_date=date(2026, 10, day), day_of_month=day, weekday=None,
        active=True, flexibility=flexibility,
    )


def twin(balance, buffer, *recurring, **prefs):
    return TwinState(
        student_id=1, as_of=AS_OF, month="2026-10",
        opening_balance=money(balance), current_balance=money(balance),
        month_income=money(0), month_spending=money(0), month_net=money(0),
        month_discretionary_spending=money(0),
        spending_by_category={}, budgets={}, recurring=tuple(recurring),
        safety_buffer=money(buffer), committed_upcoming=money(0),
        committed_upcoming_horizon_days=30, discretionary_buffer=money(balance),
        **prefs,
    )


# ====================================================== A. safety simulation

def test_baseline_expands_every_recurring_occurrence_over_90_days():
    """The whole point of reusing forecast(): rent must be charged 3x in 90
    days, not once (the raw projection kernel applies a single occurrence)."""
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    assert b.horizon_days == SAFETY_HORIZON_DAYS
    rent_events = [e for e in b.events if e.label == "Rent"]
    assert [e.date for e in rent_events] == [
        date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)
    ]
    assert all(e.amount == money(-10_000) for e in rent_events)
    # 100000 - 3*10000 = 70000 at the end, and that is also the minimum
    assert b.check.end_balance == money(70_000)
    assert b.check.minimum_projected_balance == money(70_000)
    assert b.check.passed is True


def test_credits_are_inflows_and_raise_the_floor():
    b = build_baseline(twin(10_000, 5_000, rec("Salary", 30_000, "credit", day=25)))
    assert b.check.end_balance == money(10_000 + 90_000)   # 3 salary months
    # minimum is day 0, before the first salary lands
    assert b.check.minimum_projected_balance == money(10_000)


def test_baseline_itself_can_fail_the_floor():
    b = build_baseline(twin(25_000, 20_000, rec("Rent", 10_000, day=10)))
    assert b.check.passed is False
    assert FAIL_MIN_BALANCE in b.check.failure_reasons


def test_simulate_does_not_mutate_the_baseline():
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    before = tuple(b.events)
    simulate(b, payments=[PlanPayment(AS_OF, money(5_000))])
    assert tuple(b.events) == before


def test_minimum_balance_floor_defaults_to_the_safety_buffer_and_is_overridable():
    t = twin(100_000, 20_000)
    assert build_baseline(t).minimum_balance_required == money(20_000)
    assert build_baseline(t, minimum_balance=money(50_000)).minimum_balance_required == money(50_000)


# -------------------------------------------- S1-S4 invariant enforcement

def test_s1_minimum_balance_violation_is_detected():
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    # headroom is 70000; paying 75000 breaks the floor
    chk = evaluate_plan(b, payments=[PlanPayment(AS_OF, money(75_000))],
                        requested_amount=money(75_000))
    assert chk.passed is False and FAIL_MIN_BALANCE in chk.failure_reasons


def test_s2_payment_outside_the_horizon_is_rejected():
    b = build_baseline(twin(500_000, 20_000))
    beyond = AS_OF + timedelta(days=SAFETY_HORIZON_DAYS + 1)
    chk = evaluate_plan(b, payments=[PlanPayment(beyond, money(1_000))],
                        requested_amount=money(1_000))
    assert FAIL_PAYMENT_OUTSIDE_HORIZON in chk.failure_reasons


def test_s3_payments_must_sum_to_the_requested_amount():
    b = build_baseline(twin(500_000, 20_000))
    short = evaluate_plan(b, payments=[PlanPayment(AS_OF, money(30_000))],
                          requested_amount=money(60_000))
    assert FAIL_AMOUNT_INCOMPLETE in short.failure_reasons
    exact = evaluate_plan(
        b,
        payments=[PlanPayment(AS_OF, money(30_000)),
                  PlanPayment(AS_OF + timedelta(days=20), money(30_000))],
        requested_amount=money(60_000),
    )
    assert exact.passed is True


def test_s4_completion_deadline_is_enforced():
    b = build_baseline(twin(500_000, 20_000))
    late = AS_OF + timedelta(days=40)
    chk = evaluate_plan(b, payments=[PlanPayment(late, money(1_000))],
                        requested_amount=money(1_000),
                        deadline=AS_OF + timedelta(days=30))
    assert FAIL_DEADLINE_MISSED in chk.failure_reasons


def test_essential_spending_stays_covered_is_enforced_through_s1():
    """A plan that would starve a future essential payment fails S1 — there is
    no separate rule to forget.

    200000 balance, 10000 floor, a 40000 monthly fee -> 3 occurrences in 90
    days (Oct/Nov/Dec 20) = 120000 out, so the baseline bottoms out at 80000.
    Paying 75000 today drags that trough to 5000, under the floor.
    """
    b = build_baseline(twin(200_000, 10_000, rec("School fee", 40_000, day=20)))
    assert b.check.minimum_projected_balance == money(80_000)
    chk = evaluate_plan(b, payments=[PlanPayment(AS_OF, money(75_000))],
                        requested_amount=money(75_000))
    assert chk.passed is False
    assert chk.minimum_projected_balance == money(5_000)
    assert FAIL_MIN_BALANCE in chk.failure_reasons


# ======================================================= B. amount_safe_to_pay

def test_amount_safe_to_pay_returns_the_full_request_when_safe():
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    assert amount_safe_to_pay(b, requested=money(50_000)) == money(50_000)


def test_amount_safe_to_pay_is_exact_to_the_rupee():
    """100000 balance, 3 x 10000 rent over the horizon -> trough 70000.
    The floor is 20000, so exactly 50000 is payable — not a coarse fraction of
    the 90000 request, and not the 70000 trough.
    """
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    assert b.check.minimum_projected_balance == money(70_000)
    assert amount_safe_to_pay(b, requested=money(90_000)) == money(50_000)
    # and the boundary itself is safe while one rupee more is not
    assert is_safe(b, payments=[PlanPayment(AS_OF, money(50_000))]) is True
    assert is_safe(b, payments=[PlanPayment(AS_OF, money(50_001))]) is False


def test_amount_safe_to_pay_respects_the_spec_invariant():
    b = build_baseline(twin(100_000, 20_000, rec("Rent", 10_000, day=10)))
    for requested in (1, 500, 50_000, 50_001, 200_000):
        got = amount_safe_to_pay(b, requested=money(requested))
        assert money(0) <= got <= money(requested)


def test_amount_safe_to_pay_is_zero_when_already_below_the_floor():
    b = build_baseline(twin(15_000, 20_000))
    assert amount_safe_to_pay(b, requested=money(5_000)) == money(0)


def test_amount_safe_to_pay_zero_for_non_positive_request():
    b = build_baseline(twin(100_000, 20_000))
    assert amount_safe_to_pay(b, requested=money(0)) == money(0)


def test_amount_safe_to_pay_accounts_for_future_outflows_not_just_today():
    """THE headline behaviour — "current balance" is not "safe to spend".

    200000 balance with a 30000 monthly insurance premium. Naive
    balance-minus-floor maths would offer 180000. The 90-day view charges the
    premium three times (Oct/Nov/Dec 25), bottoming out at 110000, so only
    90000 is actually safe.
    """
    b = build_baseline(twin(200_000, 20_000, rec("Insurance", 30_000, day=25)))
    naive_today_only = money(200_000) - money(20_000)
    assert naive_today_only == money(180_000)
    assert b.check.minimum_projected_balance == money(110_000)
    assert amount_safe_to_pay(b, requested=money(150_000)) == money(90_000)


def test_amount_safe_to_pay_on_a_later_date_can_be_larger():
    b = build_baseline(twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)))
    today = amount_safe_to_pay(b, requested=money(40_000))
    later = amount_safe_to_pay(b, requested=money(40_000),
                               on_date=date(2026, 10, 26))
    assert today == money(5_000)
    assert later > today


# ============================================= C. earliest_date_for_full_payment

def test_earliest_date_is_today_when_already_safe():
    b = build_baseline(twin(100_000, 20_000))
    assert earliest_date_for_full_payment(b, requested=money(10_000)) == AS_OF


def test_earliest_date_waits_for_confirmed_income():
    b = build_baseline(twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)))
    # 10000 - 30000 is unsafe until the 25th tops the account up
    assert earliest_date_for_full_payment(b, requested=money(30_000)) == date(2026, 10, 25)


def test_earliest_date_is_none_when_it_never_becomes_safe():
    b = build_baseline(twin(30_000, 20_000))
    assert earliest_date_for_full_payment(b, requested=money(100_000)) is None


def test_earliest_date_never_precedes_as_of():
    b = build_baseline(twin(100_000, 20_000))
    got = earliest_date_for_full_payment(
        b, requested=money(1_000), from_date=AS_OF - timedelta(days=30))
    assert got == AS_OF


def test_earliest_date_skips_a_day_made_unsafe_by_an_outflow():
    """Safety is not monotonic in the date, which is why this is a forward scan
    and not a bisection: the 20th is unsafe, later days are safe again."""
    b = build_baseline(twin(60_000, 10_000,
                            rec("Fee", 40_000, day=20),
                            rec("Salary", 50_000, "credit", day=28, rid=2)))
    got = earliest_date_for_full_payment(b, requested=money(45_000))
    assert got is not None and got >= date(2026, 10, 28)


# ============================================ flexible-change stream rewriting

def test_stop_removes_every_occurrence_of_that_commitment():
    b = build_baseline(twin(40_000, 20_000, rec("Netflix", 1_000, day=15, flexibility="flexible")))
    stop = SpendingChange(1, "Netflix", ACTION_STOP, money(1_000), money(0))
    assert b.check.end_balance == money(37_000)              # 3 charges
    assert simulate(b, changes=[stop]).end_balance == money(40_000)


def test_reduce_rescales_every_occurrence():
    b = build_baseline(twin(40_000, 20_000, rec("Dining", 5_000, day=15, flexibility="flexible")))
    cut = SpendingChange(1, "Dining", ACTION_REDUCE, money(5_000), money(2_500))
    assert b.check.end_balance == money(25_000)              # 3 x 5000
    assert simulate(b, changes=[cut]).end_balance == money(32_500)   # 3 x 2500


def test_a_change_naming_an_unknown_commitment_changes_nothing():
    """An invented expense cannot manufacture headroom."""
    b = build_baseline(twin(40_000, 20_000, rec("Rent", 10_000, day=10)))
    bogus = SpendingChange(99, "Imaginary Gym", ACTION_STOP, money(9_000), money(0))
    assert simulate(b, changes=[bogus]).min_balance == \
        simulate(b).min_balance


def test_changes_never_touch_an_inflow():
    b = build_baseline(twin(10_000, 5_000, rec("Salary", 30_000, "credit", day=25)))
    sneaky = SpendingChange(1, "Salary", ACTION_STOP, money(30_000), money(0))
    assert simulate(b, changes=[sneaky]).end_balance == b.check.end_balance


def test_a_cut_can_turn_an_unsafe_plan_safe():
    b = build_baseline(twin(60_000, 20_000,
                            rec("Dining", 6_000, day=15, flexibility="flexible")))
    pay = [PlanPayment(AS_OF, money(25_000))]
    assert is_safe(b, payments=pay) is False                 # 60000-18000-25000 = 17000
    cut = SpendingChange(1, "Dining", ACTION_REDUCE, money(6_000), money(1_000))
    assert is_safe(b, payments=pay, changes=[cut]) is True    # 60000-3000-25000 = 32000


# ------------------------------------------------------------------- purity

def test_safety_module_imports_nothing_impure():
    """Inspect the real import graph via the AST — not the prose, which
    legitimately says "no Flask, no DB"."""
    import ast
    import inspect
    import decision.safety as mod

    tree = ast.parse(inspect.getsource(mod))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])

    banned = {"flask", "requests", "database", "finance_db", "sqlalchemy",
              "mysql", "ollama", "openai", "anthropic", "ai", "agent",
              "tools", "routes", "pandas", "numpy"}
    assert not (roots & banned), f"decision.safety must not import {roots & banned}"
    # it may only reach for stdlib + the finance layer
    assert roots <= {"__future__", "dataclasses", "datetime", "decimal", "typing", "finance"}
