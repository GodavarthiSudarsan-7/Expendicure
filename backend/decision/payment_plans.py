"""Payment-plan construction, evaluation and deterministic selection.

The engine — never the LLM — decides HOW a purchase should be paid for. It
builds a small set of candidate plans, proves each one against the 90-day
safety invariant in :mod:`decision.safety`, discards any the user is unwilling
to use, and then picks a winner by a fixed, documented ranking.

Plans considered
----------------
  full_payment    the whole amount, in one payment, today
  partial_payment amount_safe_to_pay today + the exact remainder on the
                  earliest later day that is safe GIVEN the first payment
  installments    a schedule the CALLER supplied (merchant / bank offer).
                  Never invented, never estimated — fees included as given.
  wait            the whole amount, in one payment, on the earliest safe day
  not_recommended nothing safe and permitted exists

Each of the above is additionally retried with flexible-spending changes when
it fails on its own, so "affordable if you trim two things" is discoverable.

Pure: ``Decimal`` + stdlib + ``finance`` + ``decision.*``. No Flask, DB,
repository, network or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from finance.money import ZERO, money

from decision.flexible_spending import find_adjustments
from decision.safety import (
    Baseline,
    PlanPayment,
    SafetyCheck,
    SpendingChange,
    amount_safe_to_pay,
    earliest_safe_date_for,
    evaluate_plan,
)

# ----------------------------------------------------------- affordability states
AFFORDABLE_NOW = "affordable_now"
AFFORDABLE_WITH_PLAN = "affordable_with_plan"
AFFORDABLE_LATER = "affordable_later"
NOT_AFFORDABLE = "not_affordable"

# ------------------------------------------------------------- payment methods
METHOD_FULL = "full_payment"
METHOD_PARTIAL = "partial_payment"
METHOD_INSTALLMENTS = "installments"
METHOD_WAIT = "wait"
METHOD_NONE = "not_recommended"

#: Final, purely deterministic tie-break order between otherwise equal plans.
_METHOD_RANK = {
    METHOD_FULL: 0,
    METHOD_PARTIAL: 1,
    METHOD_INSTALLMENTS: 2,
    METHOD_WAIT: 3,
}

# ------------------------------------------------------- ineligibility reasons
INELIGIBLE_NO_PARTIAL = "user does not accept partial payment"
INELIGIBLE_NO_INSTALLMENTS = "user does not accept installments"
INELIGIBLE_NO_CUTS = "user does not want to change flexible spending"


@dataclass(frozen=True)
class InstallmentOption:
    """A schedule SUPPLIED to the engine — a merchant or bank offer.

    The engine simulates exactly this schedule. It never invents an option, and
    never estimates interest: ``total_payable`` and ``fee`` are the caller's
    figures.
    """
    option_id: str
    first_payment_date: date
    number_of_payments: int
    payment_amount: Decimal
    total_payable: Decimal
    interval_days: Optional[int] = None    # None => monthly on the same day
    fee: Decimal = ZERO
    label: str = "installment"

    def schedule(self) -> List[PlanPayment]:
        """Expand to concrete payments. Monthly steps reuse the shared
        recurrence arithmetic so month-length clamping matches the rest of
        Expendicure."""
        from finance.recurrence import add_months

        out: List[PlanPayment] = []
        for i in range(max(0, int(self.number_of_payments))):
            if self.interval_days:
                when = self.first_payment_date + timedelta(days=self.interval_days * i)
            else:
                when = add_months(self.first_payment_date, i,
                                  day=self.first_payment_date.day)
            out.append(PlanPayment(date=when, amount=money(self.payment_amount),
                                   label=f"{self.label} {i + 1}/{self.number_of_payments}"))
        return out

    def to_dict(self) -> dict:
        return {
            "option_id": self.option_id,
            "first_payment_date": self.first_payment_date.isoformat(),
            "number_of_payments": self.number_of_payments,
            "payment_amount": str(money(self.payment_amount)),
            "total_payable": str(money(self.total_payable)),
            "interval_days": self.interval_days,
            "fee": str(money(self.fee)),
            "label": self.label,
        }


@dataclass(frozen=True)
class CandidatePlan:
    method: str
    payments: Tuple[PlanPayment, ...]
    changes: Tuple[SpendingChange, ...]
    safety: SafetyCheck
    total_payable: Decimal
    financing_cost: Decimal
    completion_date: Optional[date]
    eligible: bool
    ineligible_reason: Optional[str] = None
    option_id: Optional[str] = None

    @property
    def viable(self) -> bool:
        """Safe AND permitted — the only plans that may be recommended."""
        return self.safety.passed and self.eligible

    @property
    def payments_total(self) -> Decimal:
        return money(sum((money(p.amount) for p in self.payments), ZERO))

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "option_id": self.option_id,
            "payments": [p.to_dict() for p in self.payments],
            "spending_changes": [c.to_dict() for c in self.changes],
            "total_payable": str(money(self.total_payable)),
            "financing_cost": str(money(self.financing_cost)),
            "completion_date": self.completion_date.isoformat() if self.completion_date else None,
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "safe": self.safety.passed,
            "safety": self.safety.to_dict(),
        }


# ----------------------------------------------------------------- D/E/F builders

def _finish(payments: Sequence[PlanPayment]) -> Optional[date]:
    return max((p.date for p in payments), default=None)


def _make(
    baseline: Baseline,
    *,
    method: str,
    payments: Sequence[PlanPayment],
    requested: Decimal,
    changes: Sequence[SpendingChange] = (),
    deadline: Optional[date] = None,
    total_payable: Optional[Decimal] = None,
    financing_cost: Decimal = ZERO,
    eligible: bool = True,
    ineligible_reason: Optional[str] = None,
    option_id: Optional[str] = None,
) -> CandidatePlan:
    """Build a candidate and prove it against the full S1-S4 invariant."""
    payments = tuple(payments)
    changes = tuple(changes)
    check = evaluate_plan(
        baseline, payments=payments, changes=changes,
        requested_amount=(total_payable if total_payable is not None else requested),
        deadline=deadline,
    )
    return CandidatePlan(
        method=method,
        payments=payments,
        changes=changes,
        safety=check,
        total_payable=money(total_payable if total_payable is not None else requested),
        financing_cost=money(financing_cost),
        completion_date=_finish(payments),
        eligible=eligible,
        ineligible_reason=ineligible_reason,
        option_id=option_id,
    )


def build_full_payment(
    baseline: Baseline, twin, *, requested: Decimal,
    on_date: Optional[date] = None, deadline: Optional[date] = None,
    changes: Sequence[SpendingChange] = (),
) -> CandidatePlan:
    """D. The whole amount in one payment on ``on_date`` (default: today)."""
    when = on_date or baseline.as_of
    return _make(
        baseline, method=METHOD_FULL, requested=requested, deadline=deadline,
        payments=[PlanPayment(date=when, amount=money(requested), label="full payment")],
        changes=changes,
    )


def build_partial_payment(
    baseline: Baseline, twin, *, requested: Decimal,
    on_date: Optional[date] = None, deadline: Optional[date] = None,
    changes: Sequence[SpendingChange] = (),
) -> Optional[CandidatePlan]:
    """E. ``amount_safe_to_pay`` today + the exact remainder on the earliest
    later day that is safe *given* the first payment.

    The two payments always sum to exactly ``requested`` (S3). Returns ``None``
    when no split exists — e.g. nothing is safe today, or the remainder never
    becomes safe inside the horizon.
    """
    requested = money(requested)
    when = on_date or baseline.as_of
    first = amount_safe_to_pay(baseline, requested=requested, on_date=when, changes=changes)
    if first <= ZERO or first >= requested:
        return None                      # nothing to split, or no split needed

    remainder = money(requested - first)
    p1 = PlanPayment(date=when, amount=first, label="payment 1 of 2")
    second_date = earliest_safe_date_for(
        baseline, amount=remainder, from_date=when + timedelta(days=1),
        also_pay=[p1], changes=changes,
    )
    if second_date is None:
        return None

    eligible = bool(getattr(twin, "accepts_partial_payment", True))
    return _make(
        baseline, method=METHOD_PARTIAL, requested=requested, deadline=deadline,
        payments=[p1, PlanPayment(date=second_date, amount=remainder, label="payment 2 of 2")],
        changes=changes,
        eligible=eligible,
        ineligible_reason=None if eligible else INELIGIBLE_NO_PARTIAL,
    )


def build_installment_plan(
    baseline: Baseline, twin, *, option: InstallmentOption,
    deadline: Optional[date] = None, changes: Sequence[SpendingChange] = (),
) -> CandidatePlan:
    """F. Simulate exactly the supplied schedule, fees included."""
    payments = option.schedule()
    eligible = bool(getattr(twin, "accepts_installments", False))
    return _make(
        baseline, method=METHOD_INSTALLMENTS,
        requested=money(option.total_payable), payments=payments, changes=changes,
        deadline=deadline,
        total_payable=money(option.total_payable),
        financing_cost=money(option.fee),
        eligible=eligible,
        ineligible_reason=None if eligible else INELIGIBLE_NO_INSTALLMENTS,
        option_id=option.option_id,
    )


def build_wait_plan(
    baseline: Baseline, twin, *, requested: Decimal,
    deadline: Optional[date] = None, changes: Sequence[SpendingChange] = (),
) -> Optional[CandidatePlan]:
    """The whole amount, once, on the earliest safe day after today."""
    when = earliest_safe_date_for(
        baseline, amount=money(requested),
        from_date=baseline.as_of + timedelta(days=1), changes=changes,
    )
    if when is None:
        return None
    return _make(
        baseline, method=METHOD_WAIT, requested=requested, deadline=deadline,
        payments=[PlanPayment(date=when, amount=money(requested), label="full payment")],
        changes=changes,
    )


# -------------------------------------------------------- candidate generation

def build_candidates(
    baseline: Baseline, twin, *, requested: Decimal,
    on_date: Optional[date] = None,
    deadline: Optional[date] = None,
    installment_options: Sequence[InstallmentOption] = (),
) -> Tuple[CandidatePlan, ...]:
    """Every plan worth evaluating, each already proven or disproven.

    Each shape is tried first with NO spending changes. Only if that fails is
    the flexible-spending engine asked for the smallest proven-sufficient set
    of cuts, and the shape retried — so a plan that needs no sacrifice is
    always discovered first.
    """
    requested = money(requested)
    out: List[CandidatePlan] = []
    if requested <= ZERO:
        return ()

    def with_fallback(plan: Optional[CandidatePlan], rebuild):
        if plan is not None:
            out.append(plan)
        if plan is not None and plan.safety.passed:
            return
        probe = plan.payments if plan is not None else ()
        if not probe:
            return
        changes = find_adjustments(baseline, twin, payments=probe)
        if not changes:
            return
        adjusted = rebuild(changes)
        if adjusted is not None:
            out.append(adjusted)

    with_fallback(
        build_full_payment(baseline, twin, requested=requested, on_date=on_date, deadline=deadline),
        lambda ch: build_full_payment(baseline, twin, requested=requested,
                                      on_date=on_date, deadline=deadline, changes=ch),
    )
    with_fallback(
        build_partial_payment(baseline, twin, requested=requested, on_date=on_date, deadline=deadline),
        lambda ch: build_partial_payment(baseline, twin, requested=requested,
                                         on_date=on_date, deadline=deadline, changes=ch),
    )
    for option in installment_options:
        with_fallback(
            build_installment_plan(baseline, twin, option=option, deadline=deadline),
            lambda ch, o=option: build_installment_plan(baseline, twin, option=o,
                                                        deadline=deadline, changes=ch),
        )
    with_fallback(
        build_wait_plan(baseline, twin, requested=requested, deadline=deadline),
        lambda ch: build_wait_plan(baseline, twin, requested=requested,
                                   deadline=deadline, changes=ch),
    )

    # A cuts-bearing plan is not permitted at all if the user refuses cuts.
    final: List[CandidatePlan] = []
    allows_cuts = bool(getattr(twin, "allows_flexible_cuts", True))
    for p in out:
        if p.changes and not allows_cuts:
            p = CandidatePlan(**{**p.__dict__, "eligible": False,
                                 "ineligible_reason": INELIGIBLE_NO_CUTS})
        final.append(p)
    return tuple(final)


# ------------------------------------------------------- H. deterministic choice

def _rank_key(plan: CandidatePlan):
    """The published preference order. Deadline compliance is already enforced
    by S4 inside ``plan.safety.passed``, and eligibility by ``plan.viable``, so
    the remaining criteria are:

        3. no unnecessary spending changes  (fewer changes first)
        4. lower total cost
        5. earlier completion
        5b. earlier FIRST payment — start delivering the purchase sooner
        6. fewer payments
        7. deterministic tie-break: method rank, then option id

    Criterion 5b exists because completion date alone leaves real ties. A
    partial plan ("pay part today, the rest on the 25th") and a wait plan ("pay
    it all on the 25th") finish on the same day, cost the same and are equally
    safe — but the partial plan gets the purchase under way now. Ranking the
    earlier first payment ahead of "fewer payments" is what makes the engine
    prefer it, and matches the worked example in the specification.
    """
    return (
        len(plan.changes),
        plan.total_payable,
        plan.completion_date or date.max,
        plan.payments[0].date if plan.payments else date.max,
        len(plan.payments),
        _METHOD_RANK.get(plan.method, 99),
        plan.option_id or "",
    )


def select_plan(candidates: Sequence[CandidatePlan]) -> Optional[CandidatePlan]:
    """The recommended plan: the best VIABLE candidate, or ``None``."""
    viable = [c for c in candidates if c.viable]
    if not viable:
        return None
    return sorted(viable, key=_rank_key)[0]


def affordability_status(plan: Optional[CandidatePlan], *, as_of: date) -> str:
    """Map the selected plan onto the four published states.

    Derived from the SELECTED plan so the status and the recommendation can
    never disagree:
      * one full payment, today            -> affordable_now
      * split / installments / needs cuts  -> affordable_with_plan
      * one full payment, but later        -> affordable_later
      * nothing safe and permitted         -> not_affordable
    """
    if plan is None:
        return NOT_AFFORDABLE
    if plan.changes:
        return AFFORDABLE_WITH_PLAN
    if plan.method == METHOD_FULL:
        return AFFORDABLE_NOW if plan.completion_date == as_of else AFFORDABLE_LATER
    if plan.method == METHOD_WAIT:
        return AFFORDABLE_LATER
    return AFFORDABLE_WITH_PLAN
