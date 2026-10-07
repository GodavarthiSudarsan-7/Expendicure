"""The deterministic Financial Decision Orchestrator.

    REQUEST UNDERSTANDING  (Herman / the route — NOT here)
            |
            v
    DecisionRequest        structured, already-parsed intent
            |
            v
    TwinState              the Financial Twin, the single source of truth
            |
            v
    >>> THIS MODULE <<<    composes the deterministic engines, decides nothing
            |               by itself
            v
    FinancialDecision      the ONE authoritative canonical result
            |
            v
    Number Guard -> Herman explains it

This module is **compositional only**. It contains no financial arithmetic of
its own: every figure it reports is produced by
``decision.safety`` / ``decision.payment_plans`` /
``decision.flexible_spending`` / ``decision.goal_impact``, which in turn all
run on the single projection kernel ``finance.projection``. If you find
yourself adding a ``+``, ``-`` or ``*`` on money here, it belongs in one of
those modules instead.

It is also the authority: the LLM never makes the financial decision, and
``decision_explanation`` is a tuple of structured FACTS, never prose, so the
engine can never become dependent on a language model to express itself.

Pure: ``Decimal`` + stdlib + ``finance`` + ``decision``. No Flask, DB,
repository, network or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from finance.money import ZERO, money

from decision.flexible_spending import flexible_candidates
from decision.goal_impact import GoalImpact, evaluate_goal_impact
from decision.consequence_engine import GOAL_ESCALATE_DELAY_MONTHS
from decision.payment_plans import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    METHOD_FULL,
    METHOD_NONE,
    METHOD_PARTIAL,
    METHOD_INSTALLMENTS,
    METHOD_WAIT,
    NOT_AFFORDABLE,
    CandidatePlan,
    InstallmentOption,
    affordability_status,
    build_candidates,
    select_plan,
)
from decision.safety import (
    SAFETY_HORIZON_DAYS,
    Baseline,
    SafetyCheck,
    SpendingChange,
    amount_safe_to_pay,
    build_baseline,
    earliest_date_for_full_payment,
    next_inflow,
)

CURRENCY = "INR"

# --- S1-S6 violation codes (the canonical invariant, verified post-selection) --
V_MIN_BALANCE = "s1_minimum_balance_violated"
V_OUTSIDE_HORIZON = "s2_payment_outside_horizon"
V_AMOUNT_INCOMPLETE = "s3_amount_not_completed"
V_DEADLINE = "s4_completion_deadline_missed"
V_METHOD_NOT_ALLOWED = "s5_payment_method_not_allowed"
V_NON_FLEXIBLE_CHANGED = "s6_non_flexible_expense_changed"


# ------------------------------------------------------------------- request

@dataclass(frozen=True)
class DecisionRequest:
    """A structured purchase request. Natural language has already been
    understood by the time this exists — this type is the contract between the
    request-understanding layer and the deterministic engine."""
    amount: Decimal
    description: Optional[str] = None
    category: Optional[str] = None
    request_date: Optional[date] = None             # default: the twin's as_of
    desired_completion_date: Optional[date] = None
    installment_options: Tuple[InstallmentOption, ...] = ()
    goal_id: Optional[int] = None
    horizon_days: int = SAFETY_HORIZON_DAYS
    minimum_balance: Optional[Decimal] = None       # default: twin.safety_buffer

    def to_dict(self) -> dict:
        return {
            "amount": str(money(self.amount)),
            "description": self.description,
            "category": self.category,
            "request_date": self.request_date.isoformat() if self.request_date else None,
            "desired_completion_date": (self.desired_completion_date.isoformat()
                                        if self.desired_completion_date else None),
            "installment_options": [o.to_dict() for o in self.installment_options],
            "goal_id": self.goal_id,
            "horizon_days": self.horizon_days,
        }


# -------------------------------------------------------- explanation facts

FACT_MONEY = "money"
FACT_DATE = "date"
FACT_INT = "int"
FACT_TEXT = "text"
FACT_BOOL = "bool"


@dataclass(frozen=True)
class ExplanationFact:
    """One structured, machine-checkable fact. Herman renders these into
    language; the engine never produces a sentence of its own."""
    code: str
    label: str
    value: Optional[str]
    kind: str = FACT_TEXT

    def to_dict(self) -> dict:
        return {"code": self.code, "label": self.label,
                "value": self.value, "kind": self.kind}


def _fact(code, label, value, kind=FACT_TEXT) -> ExplanationFact:
    if value is None:
        return ExplanationFact(code, label, None, kind)
    if isinstance(value, date):
        return ExplanationFact(code, label, value.isoformat(), FACT_DATE)
    if isinstance(value, Decimal):
        return ExplanationFact(code, label, str(money(value)), FACT_MONEY)
    if isinstance(value, bool):
        return ExplanationFact(code, label, "true" if value else "false", FACT_BOOL)
    if isinstance(value, int):
        return ExplanationFact(code, label, str(value), FACT_INT)
    return ExplanationFact(code, label, str(value), kind)


# ------------------------------------------------------- canonical decision

@dataclass(frozen=True)
class FinancialDecision:
    """THE canonical, authoritative result of one financial decision request."""

    # --- the headline answer -------------------------------------------------
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: Optional[CandidatePlan]
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: Tuple[SpendingChange, ...]
    decision_explanation: Tuple[ExplanationFact, ...]

    # --- structured internals ------------------------------------------------
    requested_amount: Decimal
    request_date: date
    desired_completion_date: Optional[date]
    currency: str
    minimum_balance_required: Decimal
    minimum_projected_balance: Decimal
    minimum_projected_balance_date: date
    forecast_horizon_days: int
    safety_check_passed: bool
    safety_failure_reasons: Tuple[str, ...]
    candidate_plans: Tuple[CandidatePlan, ...]
    selected_plan: Optional[CandidatePlan]
    goal_impact: GoalImpact
    baseline_check: SafetyCheck
    invariant_violations: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            # headline
            "amount_safe_to_pay": str(money(self.amount_safe_to_pay)),
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan.to_dict() if self.payment_plan else None,
            "earliest_date_for_full_payment": (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment else None),
            "spending_changes_needed": [c.to_dict() for c in self.spending_changes_needed],
            "decision_explanation": [f.to_dict() for f in self.decision_explanation],
            # internals
            "requested_amount": str(money(self.requested_amount)),
            "request_date": self.request_date.isoformat(),
            "desired_completion_date": (self.desired_completion_date.isoformat()
                                        if self.desired_completion_date else None),
            "currency": self.currency,
            "minimum_balance_required": str(money(self.minimum_balance_required)),
            "minimum_projected_balance": str(money(self.minimum_projected_balance)),
            "minimum_projected_balance_date": self.minimum_projected_balance_date.isoformat(),
            "forecast_horizon_days": self.forecast_horizon_days,
            "safety_check_passed": self.safety_check_passed,
            "safety_failure_reasons": list(self.safety_failure_reasons),
            "candidate_plans": [p.to_dict() for p in self.candidate_plans],
            "selected_plan": self.selected_plan.to_dict() if self.selected_plan else None,
            "goal_impact": self.goal_impact.to_dict(),
            "baseline_check": self.baseline_check.to_dict(),
            "invariant_violations": list(self.invariant_violations),
        }


# --------------------------------------------------- S1-S6 invariant verifier

def verify_invariants(
    plan: CandidatePlan,
    twin,
    *,
    baseline: Baseline,
    requested_amount: Decimal,
    deadline: Optional[date],
) -> Tuple[str, ...]:
    """Re-check the FULL invariant on a plan that is about to be recommended.

    S1-S4 are re-read from the plan's own proven ``SafetyCheck``; S5 and S6 are
    checked here because they are about permission rather than cash flow. This
    is a deliberate belt-and-braces post-condition: ``build_candidates``
    already constructs only compliant plans, but a financial recommendation
    should never rest on that being true by construction alone.
    """
    out: List[str] = []
    chk = plan.safety

    if chk.minimum_projected_balance < baseline.minimum_balance_required:
        out.append(V_MIN_BALANCE)
    for p in plan.payments:
        if not (baseline.as_of <= p.date <= baseline.horizon_end):
            out.append(V_OUTSIDE_HORIZON)
            break
    if plan.payments_total != money(plan.total_payable):
        out.append(V_AMOUNT_INCOMPLETE)
    if plan.method != METHOD_INSTALLMENTS and plan.payments_total != money(requested_amount):
        out.append(V_AMOUNT_INCOMPLETE)
    if deadline is not None and plan.completion_date is not None \
            and plan.completion_date > deadline:
        out.append(V_DEADLINE)
    if not plan.eligible:
        out.append(V_METHOD_NOT_ALLOWED)

    allowed_labels = {r.label for r in flexible_candidates(twin)}
    if plan.changes and not getattr(twin, "allows_flexible_cuts", True):
        out.append(V_METHOD_NOT_ALLOWED)
    for ch in plan.changes:
        if ch.label not in allowed_labels:
            out.append(V_NON_FLEXIBLE_CHANGED)
            break

    return tuple(dict.fromkeys(out))


# ------------------------------------------------------------- orchestration

def _goal_impact_for(plan: Optional[CandidatePlan], twin, *, request, goals):
    """Goal impact for a plan, measured at the moment money starts leaving.

    A goal is modelled as a lump-sum setback by ``decision.goal_impact``, so a
    multi-payment plan is assessed on its TOTAL payable (installment fees
    included) dated at its FIRST payment — the earliest point the goal starts
    being affected.
    """
    if plan is None or not plan.payments:
        amount = money(request.amount)
        when = request.request_date or twin.as_of
    else:
        amount = money(plan.total_payable)
        when = min(p.date for p in plan.payments)
    return evaluate_goal_impact(
        twin, amount=amount, purchase_date=when, goals=goals, goal_id=request.goal_id,
    )


def _facts(
    *,
    request: DecisionRequest,
    baseline: Baseline,
    safe_today: Decimal,
    status: str,
    plan: Optional[CandidatePlan],
    earliest_full: Optional[date],
    goal: GoalImpact,
) -> Tuple[ExplanationFact, ...]:
    """Structured facts only — no sentences, no LLM."""
    out: List[ExplanationFact] = [
        _fact("requested_amount", "Requested", money(request.amount)),
        _fact("safe_today", "Safe to pay today", safe_today),
        _fact("minimum_balance", "Minimum balance to keep",
              baseline.minimum_balance_required),
        _fact("forecast_horizon_days", "Forecast horizon (days)", baseline.horizon_days),
        _fact("affordability_status", "Status", status),
        _fact("recommended_payment_method", "Recommended",
              plan.method if plan else METHOD_NONE),
    ]

    chk = plan.safety if plan is not None else baseline.check
    out.append(_fact("minimum_projected_balance", "Lowest projected balance",
                     chk.minimum_projected_balance))
    out.append(_fact("minimum_projected_balance_date", "Lowest balance on",
                     chk.minimum_projected_balance_date))

    out.append(_fact("earliest_full_payment", "Earliest full payment", earliest_full))

    inflow = next_inflow(baseline)
    if inflow is not None:
        out.append(_fact("confirmed_income_date", "Next confirmed income", inflow[0]))
        out.append(_fact("confirmed_income_amount", "Next confirmed income amount",
                         inflow[1]))

    if plan is not None:
        out.append(_fact("completion_date", "Purchase completed on", plan.completion_date))
        out.append(_fact("payment_count", "Number of payments", len(plan.payments)))
        out.append(_fact("total_payable", "Total payable", money(plan.total_payable)))
        if plan.financing_cost > ZERO:
            out.append(_fact("financing_cost", "Financing cost",
                             money(plan.financing_cost)))

    changes = plan.changes if plan is not None else ()
    if changes:
        out.append(_fact("spending_changes", "Spending changes needed", len(changes)))
        for ch in changes:
            out.append(_fact(f"spending_change_{ch.action}", ch.label,
                             money(ch.monthly_saving)))
    else:
        out.append(_fact("spending_changes", "Spending changes needed", "none"))

    if goal.available:
        out.append(_fact("goal_name", "Savings goal", goal.goal_name))
        out.append(_fact("goal_delay_days", "Goal delayed by (days)", goal.delay_days))
        out.append(_fact("goal_delay_months", "Goal delayed by (months)",
                         goal.delay_months))
        if goal.delay_months is not None \
                and goal.delay_months >= GOAL_ESCALATE_DELAY_MONTHS:
            out.append(_fact("goal_setback_significant",
                             "Goal setback is significant", True))

    if plan is None:
        out.append(_fact("no_viable_plan_reason", "Why not affordable",
                         "; ".join(baseline.check.failure_reasons) or
                         "no safe and permitted plan completes this amount"))
    return tuple(out)


def decide(
    twin,
    request: DecisionRequest,
    *,
    history=None,
    goals=None,
) -> FinancialDecision:
    """Produce the ONE authoritative decision for ``request`` against ``twin``.

    Composes, in order:
      1. the 90-day baseline (reusing ``finance.forecast``'s event stream)
      2. ``amount_safe_to_pay`` on the request date
      3. ``earliest_date_for_full_payment`` (method-independent)
      4-10. every candidate plan — full / partial / supplied installments /
            wait, each retried with flexible-spending changes when needed
      11. goal impact for the chosen plan
      12. deterministic selection, then an S1-S6 post-condition re-check
      13. the canonical object, with structured explanation facts

    Raises ``ValueError`` for a non-positive amount or a request dated before
    the twin's ``as_of``.
    """
    amount = money(request.amount)
    if amount <= ZERO:
        raise ValueError("amount must be greater than 0")

    request_date = request.request_date or twin.as_of
    if request_date < twin.as_of:
        raise ValueError("request_date must not be before the twin's as_of date")

    deadline = request.desired_completion_date

    # 1. baseline
    baseline = build_baseline(
        twin, history,
        horizon_days=request.horizon_days,
        minimum_balance=request.minimum_balance,
    )

    # 2/3. the two headline figures
    safe_today = amount_safe_to_pay(baseline, requested=amount, on_date=request_date)
    earliest_full = earliest_date_for_full_payment(
        baseline, requested=amount, from_date=request_date)

    # 4-10. candidates (each already proven against S1-S4)
    candidates = build_candidates(
        baseline, twin, requested=amount, on_date=request_date, deadline=deadline,
        installment_options=tuple(request.installment_options),
    )

    # 12. selection, then the S1-S6 post-condition. A plan that somehow fails
    #     verification is DISCARDED, not reported — we re-select without it.
    remaining = list(candidates)
    selected: Optional[CandidatePlan] = None
    violations: Tuple[str, ...] = ()
    while True:
        picked = select_plan(remaining)
        if picked is None:
            break
        bad = verify_invariants(
            picked, twin, baseline=baseline,
            requested_amount=amount, deadline=deadline,
        )
        if not bad:
            selected = picked
            break
        remaining = [c for c in remaining if c is not picked]
        violations = tuple(dict.fromkeys(violations + bad))

    # 11. goal impact — informs the explanation, never the selection
    goal = _goal_impact_for(selected, twin, request=request, goals=goals)

    status = affordability_status(selected, as_of=request_date)
    chk = selected.safety if selected is not None else baseline.check

    return FinancialDecision(
        amount_safe_to_pay=safe_today,
        affordability_status=status,
        recommended_payment_method=(selected.method if selected else METHOD_NONE),
        payment_plan=selected,
        earliest_date_for_full_payment=earliest_full,
        spending_changes_needed=(selected.changes if selected else ()),
        decision_explanation=_facts(
            request=request, baseline=baseline, safe_today=safe_today,
            status=status, plan=selected, earliest_full=earliest_full, goal=goal,
        ),
        requested_amount=amount,
        request_date=request_date,
        desired_completion_date=deadline,
        currency=CURRENCY,
        minimum_balance_required=baseline.minimum_balance_required,
        minimum_projected_balance=chk.minimum_projected_balance,
        minimum_projected_balance_date=chk.minimum_projected_balance_date,
        forecast_horizon_days=baseline.horizon_days,
        safety_check_passed=(selected is not None),
        safety_failure_reasons=(() if selected is not None
                                else baseline.check.failure_reasons),
        candidate_plans=candidates,
        selected_plan=selected,
        goal_impact=goal,
        baseline_check=baseline.check,
        invariant_violations=violations,
    )
