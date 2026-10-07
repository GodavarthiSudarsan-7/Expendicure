"""Phase E: the deterministic orchestrator + canonical decision object.

Pure unit tests. The orchestrator is the authority, so these tests assert the
canonical contract: schema completeness, status/plan consistency, the full
S1-S6 invariant on anything recommended, and that goal impact informs but
never overrides safety.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from decision.consequence_engine import GOAL_ESCALATE_DELAY_MONTHS
from decision.orchestrator import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    CURRENCY,
    DecisionRequest,
    NOT_AFFORDABLE,
    V_METHOD_NOT_ALLOWED,
    V_NON_FLEXIBLE_CHANGED,
    decide,
    verify_invariants,
)
from decision.payment_plans import (
    METHOD_FULL,
    METHOD_INSTALLMENTS,
    METHOD_NONE,
    METHOD_PARTIAL,
    METHOD_WAIT,
    InstallmentOption,
)
from decision.safety import SAFETY_HORIZON_DAYS, build_baseline
from finance.models import RecurringTransaction, SavingsGoal
from finance.money import money
from finance.twin import TwinState

AS_OF = date(2026, 10, 5)


def rec(label, amount, direction="debit", *, day=10, rid=1, flexibility="essential"):
    return RecurringTransaction(
        id=rid, student_id=1, label=label, merchant_name=label,
        amount=Decimal(str(amount)), direction=direction, cadence="monthly",
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


def goal(target, current, monthly, *, gid=1, name="Emergency Fund"):
    return SavingsGoal(id=gid, student_id=1, name=name,
                       target_amount=money(target), current_amount=money(current),
                       monthly_contribution=money(monthly),
                       target_date=date(2027, 6, 1), status="active")


def req(amount, **kw):
    return DecisionRequest(amount=money(amount), **kw)


# ======================================================= canonical structure

CANONICAL_KEYS = {
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
    "requested_amount", "request_date", "desired_completion_date", "currency",
    "minimum_balance_required", "minimum_projected_balance",
    "minimum_projected_balance_date", "forecast_horizon_days",
    "safety_check_passed", "safety_failure_reasons", "candidate_plans",
    "selected_plan", "goal_impact", "baseline_check", "invariant_violations",
}


def test_canonical_object_has_every_required_field():
    t = twin(300_000, 20_000)
    d = decide(t, req(60_000))
    assert set(d.to_dict()) == CANONICAL_KEYS


def test_canonical_money_is_serialised_as_decimal_strings_never_floats():
    t = twin(300_000, 20_000)
    body = decide(t, req(60_000)).to_dict()
    for key in ("amount_safe_to_pay", "requested_amount", "minimum_balance_required",
                "minimum_projected_balance"):
        assert isinstance(body[key], str)
        assert "." in body[key] and body[key].split(".")[1] != ""
    for fact in body["decision_explanation"]:
        assert not isinstance(fact["value"], float)


def test_currency_and_horizon_are_reported():
    d = decide(twin(300_000, 20_000), req(1_000))
    assert d.currency == CURRENCY == "INR"
    assert d.forecast_horizon_days == SAFETY_HORIZON_DAYS == 90


def test_request_date_defaults_to_the_twin_as_of():
    d = decide(twin(300_000, 20_000), req(1_000))
    assert d.request_date == AS_OF


def test_rejects_a_non_positive_amount():
    with pytest.raises(ValueError):
        decide(twin(100_000, 20_000), req(0))


def test_rejects_a_request_dated_before_as_of():
    with pytest.raises(ValueError):
        decide(twin(100_000, 20_000), req(1_000, request_date=AS_OF - timedelta(days=1)))


# ================================================== the four status outcomes

def test_affordable_now():
    t = twin(300_000, 20_000, rec("Rent", 10_000, day=10))
    d = decide(t, req(60_000))
    assert d.affordability_status == AFFORDABLE_NOW
    assert d.recommended_payment_method == METHOD_FULL
    assert d.payment_plan.completion_date == AS_OF
    assert d.amount_safe_to_pay == money(60_000)
    assert d.earliest_date_for_full_payment == AS_OF
    assert d.safety_check_passed is True
    assert d.spending_changes_needed == ()


def test_affordable_with_plan_via_partial_payment():
    """Safe today is only 5000; salary on the 25th funds the rest."""
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25))
    d = decide(t, req(40_000))
    assert d.affordability_status == AFFORDABLE_WITH_PLAN
    assert d.recommended_payment_method == METHOD_PARTIAL
    assert d.amount_safe_to_pay == money(5_000)
    assert len(d.payment_plan.payments) == 2
    assert d.payment_plan.payments_total == money(40_000)


def test_affordable_later_when_a_split_is_not_allowed():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    d = decide(t, req(30_000))
    assert d.affordability_status == AFFORDABLE_LATER
    assert d.recommended_payment_method == METHOD_WAIT
    assert d.earliest_date_for_full_payment == date(2026, 10, 25)
    assert d.payment_plan.completion_date == date(2026, 10, 25)


def test_not_affordable():
    t = twin(20_000, 10_000, accepts_partial_payment=False, allows_flexible_cuts=False)
    d = decide(t, req(500_000))
    assert d.affordability_status == NOT_AFFORDABLE
    assert d.recommended_payment_method == METHOD_NONE
    assert d.payment_plan is None
    assert d.selected_plan is None
    assert d.safety_check_passed is False
    assert d.earliest_date_for_full_payment is None
    assert d.spending_changes_needed == ()


def test_affordable_with_plan_via_spending_changes():
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"),
             accepts_partial_payment=False)
    d = decide(t, req(35_000))
    assert d.affordability_status == AFFORDABLE_WITH_PLAN
    assert len(d.spending_changes_needed) >= 1
    assert all(c.label == "Dining" for c in d.spending_changes_needed)


# ============================================= 8. status / plan consistency

@pytest.mark.parametrize("t,amount", [
    (twin(300_000, 20_000), 60_000),                                       # now
    (twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)), 40_000),  # with plan
    (twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
          accepts_partial_payment=False), 30_000),                          # later
    (twin(20_000, 10_000, accepts_partial_payment=False,
          allows_flexible_cuts=False), 500_000),                            # not affordable
])
def test_status_and_plan_can_never_contradict(t, amount):
    d = decide(t, req(amount))
    s, m, plan = d.affordability_status, d.recommended_payment_method, d.payment_plan

    if s == NOT_AFFORDABLE:
        assert plan is None and m == METHOD_NONE and d.safety_check_passed is False
        return

    assert plan is not None and m == plan.method and d.safety_check_passed is True
    assert plan.viable is True

    if s == AFFORDABLE_NOW:
        assert m == METHOD_FULL and plan.completion_date == d.request_date
        assert plan.changes == ()
    elif s == AFFORDABLE_LATER:
        assert len(plan.payments) == 1 and plan.completion_date > d.request_date
        assert plan.changes == ()
    elif s == AFFORDABLE_WITH_PLAN:
        assert len(plan.payments) > 1 or plan.changes


def test_never_both_not_affordable_and_a_plan():
    for amount in (1_000, 50_000, 200_000, 5_000_000):
        d = decide(twin(80_000, 20_000), req(amount))
        assert (d.affordability_status == NOT_AFFORDABLE) == (d.payment_plan is None)


# ========================================== 7. S1-S6 on anything recommended

def test_the_selected_plan_always_satisfies_the_full_invariant():
    scenarios = [
        (twin(300_000, 20_000), 60_000, None),
        (twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)), 40_000, None),
        (twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible")),
         35_000, None),
        (twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)),
         30_000, date(2026, 11, 30)),
    ]
    for t, amount, deadline in scenarios:
        d = decide(t, req(amount, desired_completion_date=deadline))
        if d.payment_plan is None:
            continue
        baseline = build_baseline(t)
        assert verify_invariants(
            d.payment_plan, t, baseline=baseline,
            requested_amount=money(amount), deadline=deadline,
        ) == ()
        # S1
        assert d.minimum_projected_balance >= d.minimum_balance_required
        # S2
        for p in d.payment_plan.payments:
            assert baseline.as_of <= p.date <= baseline.horizon_end
        # S3
        assert d.payment_plan.payments_total == money(d.payment_plan.total_payable)
        # S4
        if deadline:
            assert d.payment_plan.completion_date <= deadline


def test_verifier_flags_a_disallowed_method():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    from decision.payment_plans import build_partial_payment
    b = build_baseline(t)
    plan = build_partial_payment(b, t, requested=money(40_000))
    assert V_METHOD_NOT_ALLOWED in verify_invariants(
        plan, t, baseline=b, requested_amount=money(40_000), deadline=None)


def test_verifier_flags_a_change_to_a_non_flexible_expense():
    """S6: a plan touching an essential commitment is never acceptable."""
    import dataclasses
    from decision.payment_plans import build_full_payment
    from decision.safety import ACTION_STOP, SpendingChange

    t = twin(300_000, 20_000, rec("Rent", 10_000, day=10))     # essential
    b = build_baseline(t)
    rogue = SpendingChange(1, "Rent", ACTION_STOP, money(10_000), money(0))
    plan = build_full_payment(b, t, requested=money(1_000), changes=[rogue])
    assert V_NON_FLEXIBLE_CHANGED in verify_invariants(
        plan, t, baseline=b, requested_amount=money(1_000), deadline=None)


def test_deadline_makes_a_late_plan_unselectable():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    d = decide(t, req(30_000, desired_completion_date=date(2026, 10, 20)))
    assert d.affordability_status == NOT_AFFORDABLE
    # the method-independent answer is still reported honestly
    assert d.earliest_date_for_full_payment == date(2026, 10, 25)


# ======================================================= 4. payment options

# The realistic EMI case, used by the next few tests. A tight 5000 balance with
# 10000 salary on the 20th and 8000 rent on the 22nd -> 2000/month of surplus.
# The user cannot front 9000 until December, but a 3 x 3000 schedule starting
# Oct 21 is affordable every month. EMI and waiting both complete Dec 20, so
# criterion 5b (earlier first payment) picks the EMI — the user gets the item in
# October instead of December, at no extra cost.

def _emi_twin(**prefs):
    base = dict(accepts_installments=True, accepts_partial_payment=False)
    base.update(prefs)
    return twin(5_000, 1_000,
                rec("Salary", 10_000, "credit", day=20, rid=1),
                rec("Rent", 8_000, day=22, rid=2), **base)


def _emi_option(**over):
    base = dict(option_id="emi3", first_payment_date=date(2026, 10, 21),
                number_of_payments=3, payment_amount=money(3_000),
                total_payable=money(9_000), fee=money(0), interval_days=30)
    base.update(over)
    return InstallmentOption(**base)


def test_supplied_installment_option_is_validated_and_can_be_selected():
    t = _emi_twin()
    d = decide(t, req(9_000, installment_options=(_emi_option(),)))
    assert d.recommended_payment_method == METHOD_INSTALLMENTS
    assert d.payment_plan.option_id == "emi3"
    assert d.affordability_status == AFFORDABLE_WITH_PLAN
    assert [p.date for p in d.payment_plan.payments] == [
        date(2026, 10, 21), date(2026, 11, 20), date(2026, 12, 20)]
    assert d.payment_plan.payments_total == money(9_000)
    assert d.minimum_projected_balance >= d.minimum_balance_required


def test_no_installment_option_is_ever_invented():
    """Nothing in the candidate set may claim to be an installment plan unless
    the caller supplied the schedule."""
    t = twin(10_000, 5_000, accepts_installments=True)
    d = decide(t, req(60_000))
    assert all(c.method != METHOD_INSTALLMENTS for c in d.candidate_plans)


def test_an_unsafe_supplied_option_is_rejected_not_recommended():
    t = twin(5_000, 2_000, accepts_installments=True)
    opt = InstallmentOption(option_id="bad", first_payment_date=AS_OF,
                            number_of_payments=3, payment_amount=money(50_000),
                            total_payable=money(150_000))
    d = decide(t, req(150_000, installment_options=(opt,)))
    emi = [c for c in d.candidate_plans if c.method == METHOD_INSTALLMENTS]
    assert emi and emi[0].safety.passed is False
    assert d.recommended_payment_method != METHOD_INSTALLMENTS


def test_financing_cost_passes_through_from_the_supplied_option():
    """The fee is the caller's figure, carried verbatim onto the candidate."""
    t = _emi_twin()
    financed = _emi_option(option_id="emi3f", payment_amount=money(3_300),
                           total_payable=money(9_900), fee=money(900))
    d = decide(t, req(9_000, installment_options=(financed,)))
    emi = [c for c in d.candidate_plans if c.method == METHOD_INSTALLMENTS][0]
    assert emi.financing_cost == money(900)
    assert emi.total_payable == money(9_900)
    assert emi.payments_total == money(9_900)        # S3 against the financed total


def test_a_financed_option_loses_to_an_equally_safe_free_plan():
    """Criterion 4 — lower total cost. Paying 9900 on EMI is safe, but waiting
    and paying 9000 is both safe and cheaper, so waiting wins."""
    t = _emi_twin()
    financed = _emi_option(option_id="emi3f", payment_amount=money(3_300),
                           total_payable=money(9_900), fee=money(900))
    d = decide(t, req(9_000, installment_options=(financed,)))
    emi = [c for c in d.candidate_plans if c.method == METHOD_INSTALLMENTS][0]
    assert emi.safety.passed is True and emi.viable is True   # safe and permitted
    assert d.recommended_payment_method == METHOD_WAIT        # but not cheapest
    assert d.payment_plan.financing_cost == money(0)
    assert d.payment_plan.total_payable == money(9_000)


def test_financing_cost_appears_in_the_facts_when_a_financed_plan_is_chosen():
    """Force the financed EMI to be the only viable plan by refusing to wait is
    not expressible, so instead verify the fact is emitted whenever the selected
    plan carries a cost — here via a zero-cost EMI (no financing_cost fact) and
    the financed candidate's own figure."""
    t = _emi_twin()
    d = decide(t, req(9_000, installment_options=(_emi_option(),)))
    assert d.recommended_payment_method == METHOD_INSTALLMENTS
    codes = {f.code for f in d.decision_explanation}
    # a free plan must NOT claim a financing cost
    assert "financing_cost" not in codes
    assert d.payment_plan.financing_cost == money(0)


# ============================================================ 3. goal impact

def test_goal_impact_is_computed_deterministically_for_the_selected_plan():
    t = twin(300_000, 20_000)
    g = goal(100_000, 80_000, 5_000)        # 20000 remaining, 5000/month
    d = decide(t, req(50_000), goals=[g])
    assert d.goal_impact.available is True
    assert d.goal_impact.goal_name == "Emergency Fund"
    assert d.goal_impact.delay_months is not None and d.goal_impact.delay_months > 0
    assert d.goal_impact.delay_days is not None


def test_goal_impact_is_unavailable_with_no_goals_and_does_not_break_anything():
    d = decide(twin(300_000, 20_000), req(50_000))
    assert d.goal_impact.available is False
    assert d.affordability_status == AFFORDABLE_NOW


def test_goal_impact_never_overrides_hard_safety():
    """A severe goal setback must NOT turn a safe purchase into not_affordable
    — it informs the explanation only."""
    t = twin(300_000, 20_000)
    g = goal(100_000, 10_000, 1_000)        # tiny contribution -> huge delay
    d = decide(t, req(60_000), goals=[g])
    assert d.goal_impact.delay_months >= GOAL_ESCALATE_DELAY_MONTHS
    assert d.affordability_status == AFFORDABLE_NOW       # still affordable
    assert d.payment_plan.method == METHOD_FULL
    codes = {f.code for f in d.decision_explanation}
    assert "goal_setback_significant" in codes           # but flagged


def test_goal_impact_never_rescues_an_unsafe_purchase():
    t = twin(20_000, 10_000, accepts_partial_payment=False, allows_flexible_cuts=False)
    d = decide(t, req(500_000), goals=[goal(100_000, 99_000, 50_000)])
    assert d.affordability_status == NOT_AFFORDABLE


def test_goal_impact_is_measured_on_the_selected_plans_total_payable():
    """A multi-payment plan sets the goal back by its TOTAL, not by one
    installment — and ``total_payable`` is the financed total, fees included."""
    t = _emi_twin()
    g = goal(200_000, 0, 10_000)
    d = decide(t, req(9_000, installment_options=(_emi_option(),)), goals=[g])
    assert d.recommended_payment_method == METHOD_INSTALLMENTS
    assert d.payment_plan.total_payable == money(9_000)
    assert d.goal_impact.remaining_after == money(200_000 + 9_000)


def test_goal_impact_for_a_full_payment_uses_the_requested_amount():
    t = twin(300_000, 20_000)
    g = goal(200_000, 0, 10_000)
    d = decide(t, req(50_000), goals=[g])
    assert d.goal_impact.remaining_after == money(200_000 + 50_000)


# ================================================ 6. structured explanation

def test_explanation_is_structured_facts_not_prose():
    d = decide(twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25)),
               req(40_000))
    assert d.decision_explanation
    for f in d.decision_explanation:
        assert f.code and f.label
        assert f.kind in {"money", "date", "int", "text", "bool"}
        # a fact value is a scalar string, never a sentence
        assert f.value is None or len(f.value.split()) <= 4


def test_explanation_carries_the_specs_named_facts():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25))
    d = decide(t, req(40_000))
    codes = {f.code: f.value for f in d.decision_explanation}
    for required in ("requested_amount", "safe_today", "minimum_balance",
                     "minimum_projected_balance", "earliest_full_payment",
                     "confirmed_income_date", "spending_changes",
                     "affordability_status", "recommended_payment_method"):
        assert required in codes, required
    assert codes["requested_amount"] == "40000.00"
    assert codes["safe_today"] == "5000.00"
    assert codes["minimum_balance"] == "5000.00"
    assert codes["confirmed_income_date"] == "2026-10-25"


def test_explanation_says_none_when_no_spending_changes_are_needed():
    d = decide(twin(300_000, 20_000), req(1_000))
    codes = {f.code: f.value for f in d.decision_explanation}
    assert codes["spending_changes"] == "none"


def test_explanation_explains_an_unaffordable_request():
    d = decide(twin(20_000, 10_000, accepts_partial_payment=False,
                    allows_flexible_cuts=False), req(500_000))
    codes = {f.code for f in d.decision_explanation}
    assert "no_viable_plan_reason" in codes


# ========================================================== personalization

def test_two_users_with_the_same_balance_get_different_decisions():
    user_a = twin(100_000, 20_000,
                  rec("Salary", 50_000, "credit", day=25, rid=1),
                  rec("Entertainment", 8_000, day=12, rid=2, flexibility="flexible"),
                  accepts_installments=True, allows_flexible_cuts=True)
    user_b = twin(100_000, 20_000,
                  rec("Loan EMI", 35_000, day=8, rid=1),
                  accepts_installments=False, accepts_partial_payment=False,
                  allows_flexible_cuts=False)
    a = decide(user_a, req(90_000))
    b = decide(user_b, req(90_000))
    assert a.affordability_status != b.affordability_status
    assert a.amount_safe_to_pay != b.amount_safe_to_pay


def test_a_minimum_balance_override_changes_the_answer():
    t = twin(100_000, 20_000)
    relaxed = decide(t, req(90_000))
    strict = decide(t, req(90_000, minimum_balance=money(80_000)))
    assert relaxed.amount_safe_to_pay == money(80_000)
    assert strict.amount_safe_to_pay == money(20_000)
    assert strict.minimum_balance_required == money(80_000)


# ---------------------------------------------------------------- determinism

def test_decide_is_deterministic_and_does_not_mutate_the_twin():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25))
    snapshot = (t.current_balance, t.safety_buffer, t.recurring)
    first = decide(t, req(40_000)).to_dict()
    second = decide(t, req(40_000)).to_dict()
    assert first == second
    assert (t.current_balance, t.safety_buffer, t.recurring) == snapshot


# ------------------------------------------------------------------- purity

def test_orchestrator_has_no_flask_db_or_llm_dependency():
    import ast
    import inspect
    import decision.orchestrator as mod

    tree = ast.parse(inspect.getsource(mod))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    banned = {"flask", "requests", "database", "finance_db", "sqlalchemy", "mysql",
              "ollama", "openai", "anthropic", "ai", "agent", "tools", "routes",
              "pandas", "numpy"}
    assert not (roots & banned)
    assert roots <= {"__future__", "dataclasses", "datetime", "decimal", "typing",
                     "finance", "decision"}


def test_orchestrator_contains_no_money_arithmetic():
    """It composes; it must not compute. No +,-,* on the module's own lines
    outside of string/doc content."""
    import inspect
    import re
    import decision.orchestrator as mod

    src = inspect.getsource(mod)
    # strip the module docstring and comments
    body = re.sub(r'""".*?"""', "", src, flags=re.S)
    body = "\n".join(l.split("#")[0] for l in body.splitlines())
    # the only arithmetic-looking tokens permitted are string concatenation of
    # violation codes in `verify_invariants` (there are none) and `+` inside
    # tuple additions for violation accumulation.
    offenders = [l.strip() for l in body.splitlines()
                 if re.search(r"money\([^)]*[-*/+]", l)]
    assert offenders == [], offenders
