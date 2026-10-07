"""Phase D pieces D-H: payment-plan construction, flexible spending, selection.

Pure unit tests. Every number is hand-derived from the 90-day event stream, so
a wrong engine cannot make these pass.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from decision.flexible_spending import (
    MAX_CHANGES,
    find_adjustments,
    flexible_candidates,
    total_monthly_saving,
)
from decision.payment_plans import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    INELIGIBLE_NO_CUTS,
    INELIGIBLE_NO_INSTALLMENTS,
    INELIGIBLE_NO_PARTIAL,
    METHOD_FULL,
    METHOD_INSTALLMENTS,
    METHOD_PARTIAL,
    METHOD_WAIT,
    NOT_AFFORDABLE,
    InstallmentOption,
    affordability_status,
    build_candidates,
    build_full_payment,
    build_installment_plan,
    build_partial_payment,
    build_wait_plan,
    select_plan,
)
from decision.safety import ACTION_REDUCE, ACTION_STOP, PlanPayment, build_baseline
from finance.models import RecurringTransaction
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


# ================================================== D. full payment evaluation

def test_full_payment_safe_is_marked_safe_and_complete():
    t = twin(100_000, 20_000, rec("Rent", 10_000, day=10))   # trough 70000
    b = build_baseline(t)
    plan = build_full_payment(b, t, requested=money(40_000))
    assert plan.method == METHOD_FULL
    assert plan.safety.passed is True
    assert plan.payments_total == money(40_000)
    assert plan.completion_date == AS_OF
    assert plan.financing_cost == money(0)


def test_full_payment_unsafe_reports_the_floor_violation():
    t = twin(100_000, 20_000, rec("Rent", 10_000, day=10))
    b = build_baseline(t)
    plan = build_full_payment(b, t, requested=money(60_000))  # only 50000 safe
    assert plan.safety.passed is False
    assert plan.safety.minimum_projected_balance == money(10_000)


# ============================================== E. partial payment evaluation

def test_partial_payment_splits_exactly_and_completes_the_amount():
    """Balance 10000, floor 5000, salary 40000 on the 25th.
    Safe today = 5000; the 35000 remainder becomes safe once salary lands."""
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25))
    b = build_baseline(t)
    plan = build_partial_payment(b, t, requested=money(40_000))
    assert plan is not None
    assert len(plan.payments) == 2
    assert plan.payments[0].date == AS_OF
    assert plan.payments[0].amount == money(5_000)
    assert plan.payments[1].amount == money(35_000)
    # the two payments sum to EXACTLY the request (S3)
    assert plan.payments_total == money(40_000)
    assert plan.payments[1].date > plan.payments[0].date
    assert plan.safety.passed is True


def test_partial_payment_is_none_when_nothing_is_safe_today():
    t = twin(4_000, 5_000)                       # already under the floor
    b = build_baseline(t)
    assert build_partial_payment(b, t, requested=money(10_000)) is None


def test_partial_payment_is_none_when_no_split_is_needed():
    t = twin(500_000, 20_000)
    b = build_baseline(t)
    assert build_partial_payment(b, t, requested=money(10_000)) is None


def test_partial_payment_is_none_when_the_remainder_never_becomes_safe():
    t = twin(60_000, 20_000)                     # no income at all
    b = build_baseline(t)
    assert build_partial_payment(b, t, requested=money(100_000)) is None


def test_partial_payment_is_ineligible_when_the_user_refuses_it():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    b = build_baseline(t)
    plan = build_partial_payment(b, t, requested=money(40_000))
    assert plan is not None
    assert plan.safety.passed is True            # mathematically fine
    assert plan.eligible is False                # but not permitted
    assert plan.ineligible_reason == INELIGIBLE_NO_PARTIAL
    assert plan.viable is False


# ================================================ F. installment evaluation

def _option(**over):
    base = dict(option_id="emi12", first_payment_date=AS_OF,
                number_of_payments=12, payment_amount=money(5_000),
                total_payable=money(60_000), fee=money(0))
    base.update(over)
    return InstallmentOption(**base)


def test_installment_schedule_is_expanded_monthly_as_supplied():
    opt = _option(number_of_payments=3, payment_amount=money(20_000))
    sched = opt.schedule()
    assert [p.date for p in sched] == [date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)]
    assert all(p.amount == money(20_000) for p in sched)


def test_installment_schedule_honours_an_explicit_interval():
    opt = _option(number_of_payments=3, interval_days=7, payment_amount=money(1_000))
    assert [p.date for p in opt.schedule()] == [
        date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)
    ]


def test_installment_plan_uses_the_supplied_total_and_fee_not_an_invented_one():
    t = twin(100_000, 20_000, accepts_installments=True)
    b = build_baseline(t)
    opt = _option(number_of_payments=3, payment_amount=money(21_000),
                  total_payable=money(63_000), fee=money(3_000))
    plan = build_installment_plan(b, t, option=opt)
    assert plan.total_payable == money(63_000)
    assert plan.financing_cost == money(3_000)
    assert plan.payments_total == money(63_000)      # S3 against total_payable
    assert plan.option_id == "emi12"
    assert plan.safety.passed is True


def test_installments_are_ineligible_by_default():
    """accepts_installments defaults to False — the engine must not assume it."""
    t = twin(100_000, 20_000)
    b = build_baseline(t)
    plan = build_installment_plan(b, t, option=_option(number_of_payments=3,
                                                       payment_amount=money(20_000)))
    assert plan.safety.passed is True
    assert plan.eligible is False
    assert plan.ineligible_reason == INELIGIBLE_NO_INSTALLMENTS


def test_installments_outside_the_horizon_fail_safety():
    t = twin(500_000, 20_000, accepts_installments=True)
    b = build_baseline(t)
    # 24 monthly payments run far past the 90-day horizon
    opt = _option(number_of_payments=24, payment_amount=money(2_500),
                  total_payable=money(60_000))
    assert build_installment_plan(b, t, option=opt).safety.passed is False


# ===================================== G. flexible spending adjustment search

def test_only_flexible_outflows_are_candidates():
    t = twin(50_000, 10_000,
             rec("Rent", 15_000, day=10, rid=1),                               # essential
             rec("Dining", 5_000, day=12, rid=2, flexibility="flexible"),
             rec("Gym", 2_000, day=14, rid=3, flexibility="flexible"),
             rec("Salary", 40_000, "credit", day=25, rid=4, flexibility="flexible"))
    labels = [r.label for r in flexible_candidates(t)]
    assert labels == ["Dining", "Gym"]        # no Rent (essential), no Salary (inflow)


def test_candidates_are_ordered_largest_first_then_label():
    t = twin(50_000, 10_000,
             rec("B", 3_000, day=12, rid=2, flexibility="flexible"),
             rec("A", 3_000, day=13, rid=3, flexibility="flexible"),
             rec("C", 9_000, day=14, rid=4, flexibility="flexible"))
    assert [r.label for r in flexible_candidates(t)] == ["C", "A", "B"]


def test_no_adjustment_is_proposed_when_the_plan_is_already_safe():
    t = twin(100_000, 10_000, rec("Dining", 5_000, day=12, flexibility="flexible"))
    b = build_baseline(t)
    assert find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(1_000))]) == ()


# Scenario shared by the next two tests. Balance 60000, floor 20000, a flexible
# Dining commitment of 6000/month -> 3 occurrences (Oct/Nov/Dec 15) = 18000, so
# the baseline trough is 42000. Exact payable thresholds:
#     no change  -> up to 22000   (42000 - X >= 20000)
#     halved     -> up to 31000   (frees  9000)
#     stopped    -> up to 40000   (frees 18000)

def test_a_halving_is_preferred_over_a_stop_when_it_suffices():
    """28000 needs a cut but sits inside the halving band — the engine must not
    reach for the harsher full stop."""
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"))
    b = build_baseline(t)
    changes = find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(28_000))])
    assert len(changes) == 1
    assert changes[0].action == ACTION_REDUCE
    assert changes[0].to_amount == money(3_000)


def test_the_halving_band_boundary_is_inclusive():
    """31000 is the last amount halving can cover, so halving is still chosen."""
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"))
    b = build_baseline(t)
    changes = find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(31_000))])
    assert [c.action for c in changes] == [ACTION_REDUCE]


def test_a_stop_is_used_when_halving_is_not_enough():
    """32000 is past the halving band; only stopping the commitment works."""
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"))
    b = build_baseline(t)
    changes = find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(35_000))])
    assert len(changes) == 1
    assert changes[0].action == ACTION_STOP
    assert changes[0].to_amount == money(0)


def test_multiple_changes_are_combined_and_capped_at_three():
    t = twin(60_000, 10_000,
             rec("A", 4_000, day=11, rid=1, flexibility="flexible"),
             rec("B", 4_000, day=12, rid=2, flexibility="flexible"),
             rec("C", 4_000, day=13, rid=3, flexibility="flexible"),
             rec("D", 4_000, day=14, rid=4, flexibility="flexible"))
    b = build_baseline(t)
    changes = find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(38_000))])
    assert 0 < len(changes) <= MAX_CHANGES
    assert total_monthly_saving(changes) > money(0)


def test_adjustments_are_empty_when_even_every_cut_is_insufficient():
    """No false hope: if the cuts cannot make it safe, nothing is proposed."""
    t = twin(30_000, 10_000, rec("Dining", 1_000, day=15, flexibility="flexible"))
    b = build_baseline(t)
    assert find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(100_000))]) == ()


def test_no_adjustment_when_the_user_forbids_cuts():
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"),
             allows_flexible_cuts=False)
    b = build_baseline(t)
    assert find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(31_000))]) == ()


def test_essential_commitments_are_never_proposed_for_change():
    t = twin(60_000, 20_000, rec("Rent", 20_000, day=15))     # essential, large
    b = build_baseline(t)
    assert find_adjustments(b, t, payments=[PlanPayment(AS_OF, money(50_000))]) == ()


# ============================================ H. deterministic plan selection

def test_full_payment_today_wins_when_it_is_safe():
    t = twin(300_000, 20_000, accepts_installments=True)
    b = build_baseline(t)
    cands = build_candidates(b, t, requested=money(60_000),
                             installment_options=[_option(number_of_payments=3,
                                                          payment_amount=money(20_000))])
    chosen = select_plan(cands)
    assert chosen.method == METHOD_FULL
    assert affordability_status(chosen, as_of=AS_OF) == AFFORDABLE_NOW


def test_a_plan_with_no_spending_changes_beats_one_that_needs_cuts():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             rec("Dining", 3_000, day=12, rid=2, flexibility="flexible"))
    b = build_baseline(t)
    chosen = select_plan(build_candidates(b, t, requested=money(40_000)))
    assert chosen is not None
    assert chosen.changes == ()
    assert chosen.method in (METHOD_PARTIAL, METHOD_WAIT)


def test_cheaper_total_beats_a_financed_option():
    t = twin(300_000, 20_000, accepts_installments=True)
    b = build_baseline(t)
    financed = _option(option_id="emi3", number_of_payments=3,
                       payment_amount=money(22_000), total_payable=money(66_000),
                       fee=money(6_000))
    chosen = select_plan(build_candidates(b, t, requested=money(60_000),
                                          installment_options=[financed]))
    assert chosen.total_payable == money(60_000)
    assert chosen.financing_cost == money(0)


def test_installments_are_never_chosen_when_the_user_refuses_them():
    """Mathematically safe but not permitted: the engine must pick something
    else or nothing — never the forbidden method."""
    t = twin(40_000, 20_000, accepts_installments=False, accepts_partial_payment=False)
    b = build_baseline(t)
    opt = _option(number_of_payments=3, payment_amount=money(5_000),
                  total_payable=money(15_000))
    cands = build_candidates(b, t, requested=money(15_000), installment_options=[opt])
    emi = [c for c in cands if c.method == METHOD_INSTALLMENTS]
    assert emi and emi[0].safety.passed is True and emi[0].viable is False
    chosen = select_plan(cands)
    assert chosen is None or chosen.method != METHOD_INSTALLMENTS


def test_wait_is_selected_when_today_is_impossible_and_no_split_allowed():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    b = build_baseline(t)
    chosen = select_plan(build_candidates(b, t, requested=money(30_000)))
    assert chosen is not None and chosen.method == METHOD_WAIT
    assert chosen.completion_date == date(2026, 10, 25)
    assert affordability_status(chosen, as_of=AS_OF) == AFFORDABLE_LATER


def test_not_affordable_when_nothing_safe_and_permitted_exists():
    t = twin(20_000, 10_000, accepts_partial_payment=False, allows_flexible_cuts=False)
    b = build_baseline(t)
    chosen = select_plan(build_candidates(b, t, requested=money(500_000)))
    assert chosen is None
    assert affordability_status(chosen, as_of=AS_OF) == NOT_AFFORDABLE


def test_a_cuts_plan_is_marked_ineligible_when_the_user_forbids_cuts():
    t = twin(60_000, 20_000, rec("Dining", 6_000, day=15, flexibility="flexible"),
             allows_flexible_cuts=False, accepts_partial_payment=False)
    b = build_baseline(t)
    cands = build_candidates(b, t, requested=money(31_000))
    for c in cands:
        if c.changes:
            assert c.eligible is False and c.ineligible_reason == INELIGIBLE_NO_CUTS


def test_selection_is_deterministic_across_candidate_ordering():
    t = twin(300_000, 20_000, accepts_installments=True)
    b = build_baseline(t)
    opts = [_option(option_id="b", number_of_payments=3, payment_amount=money(20_000)),
            _option(option_id="a", number_of_payments=3, payment_amount=money(20_000))]
    first = select_plan(build_candidates(b, t, requested=money(60_000), installment_options=opts))
    second = select_plan(build_candidates(b, t, requested=money(60_000),
                                          installment_options=list(reversed(opts))))
    assert (first.method, first.option_id) == (second.method, second.option_id)


def test_every_viable_candidate_satisfies_the_full_invariant():
    """The contract the spec asks us to prove, asserted over all candidates."""
    t = twin(50_000, 10_000, rec("Salary", 30_000, "credit", day=25),
             rec("Dining", 4_000, day=12, rid=2, flexibility="flexible"),
             accepts_installments=True, accepts_partial_payment=True)
    b = build_baseline(t)
    requested = money(45_000)
    cands = build_candidates(
        b, t, requested=requested,
        installment_options=[_option(number_of_payments=3, payment_amount=money(15_000),
                                     total_payable=money(45_000))],
    )
    assert cands
    for c in cands:
        if not c.viable:
            continue
        assert c.payments_total == c.total_payable                   # amount completed
        assert c.safety.minimum_projected_balance >= money(10_000)   # floor held
        for p in c.payments:                                         # inside horizon
            assert b.as_of <= p.date <= b.horizon_end
        for ch in c.changes:                                         # only flexible
            assert ch.label in [r.label for r in flexible_candidates(t)]


def test_deadline_filters_out_late_plans():
    t = twin(10_000, 5_000, rec("Salary", 40_000, "credit", day=25),
             accepts_partial_payment=False)
    b = build_baseline(t)
    # the only safe day is Oct 25; a deadline of Oct 20 makes it impossible
    assert select_plan(build_candidates(b, t, requested=money(30_000),
                                        deadline=date(2026, 10, 20))) is None
    ok = select_plan(build_candidates(b, t, requested=money(30_000),
                                      deadline=date(2026, 10, 31)))
    assert ok is not None and ok.completion_date <= date(2026, 10, 31)


# ---------------------------------------------------------------- personalization

def test_same_balance_different_user_state_yields_different_recommendations():
    """The spec's headline personalization requirement."""
    shared = dict(balance=100_000, buffer=20_000)

    user_a = twin(shared["balance"], shared["buffer"],
                  rec("Salary", 50_000, "credit", day=25, rid=1),
                  rec("Entertainment", 8_000, day=12, rid=2, flexibility="flexible"),
                  accepts_installments=True, allows_flexible_cuts=True)
    user_b = twin(shared["balance"], shared["buffer"],
                  rec("Loan EMI", 35_000, day=8, rid=1),
                  accepts_installments=False, accepts_partial_payment=False,
                  allows_flexible_cuts=False)

    a = select_plan(build_candidates(build_baseline(user_a), user_a, requested=money(90_000)))
    b_ = select_plan(build_candidates(build_baseline(user_b), user_b, requested=money(90_000)))

    assert a is not None                 # A has income + flexibility
    assert b_ is None                    # B's EMIs consume the headroom
    assert a != b_


# ------------------------------------------------------------------- purity

@pytest.mark.parametrize("module_name", ["decision.payment_plans", "decision.flexible_spending"])
def test_new_decision_modules_are_pure(module_name):
    import ast
    import importlib
    import inspect

    mod = importlib.import_module(module_name)
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
