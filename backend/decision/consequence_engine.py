"""The Financial Consequence Engine.

    BASELINE  = project_daily_balances(twin, horizon)                    (no purchase)
    SCENARIO  = project_daily_balances(twin, horizon, [the purchase])    (hypothetical)
    COMPARE   -> minimum / month-end balance before & after, safety-buffer impact,
                 risk-state change, a recommended DECISION and reason codes.

Deterministic. Reuses ``finance.projection`` (the single shared kernel) and
``finance.affordability`` (for the verdict/score) — no second projection
implementation, no LLM, no DB writes, ``Decimal`` throughout.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from finance.affordability import DEFAULT_HORIZON_DAYS, check_affordability
from finance.money import ZERO, money
from finance.projection import ProjectionEvent, project_daily_balances
from decision.goal_impact import GoalImpact, evaluate_goal_impact

DECISION_BUY = "BUY"
DECISION_WAIT = "WAIT"
DECISION_SPEND_LESS = "SPEND_LESS"
DECISION_AVOID = "AVOID"

RISK_HEALTHY = "healthy"
RISK_CAUTION = "caution"
RISK_AT_RISK = "at_risk"
_RISK_ORD = {RISK_HEALTHY: 0, RISK_CAUTION: 1, RISK_AT_RISK: 2}

# headroom (projected minimum minus safety buffer) below this fraction of the
# safety buffer counts as "caution".
CAUTION_BUFFER_FRACTION = Decimal("0.25")
# how many days ahead to search for a "wait N days" recommendation.
MAX_WAIT_SEARCH_DAYS = 21
# fractions of the requested amount to test for a "spend less" alternative.
_SPEND_LESS_FRACTIONS = (Decimal("0.75"), Decimal("0.50"), Decimal("0.34"), Decimal("0.25"))
# below this (relative to the safety buffer) the minimum-balance change is "not meaningful".
_TRIVIAL_FRACTION = Decimal("0.05")
# GOAL DECISION RULE (documented): a goal never changes the core decision, which
# is driven only by balance / safety buffer / risk. The ONE exception: if the
# decision would otherwise be BUY (buffer is fine, risk unchanged) but the
# purchase deterministically sets a real, funded savings goal back by at least
# this many whole months, the decision is escalated to SPEND_LESS. Nothing else
# about a goal alters the decision.
GOAL_ESCALATE_DELAY_MONTHS = 3


@dataclass(frozen=True)
class ConsequenceResult:
    decision: str
    amount: Decimal
    category: Optional[str]
    description: Optional[str]
    as_of: date
    purchase_date: date
    horizon_days: int

    affordable_today: bool
    safe_to_spend: bool
    affordability_verdict: str
    affordability_score: int

    current_balance: Decimal
    buffer_impact: Decimal            # signed: -amount

    minimum_balance_before: Decimal
    minimum_balance_after: Decimal
    minimum_balance_date_before: date
    minimum_balance_date_after: date
    month_end_balance_before: Decimal
    month_end_balance_after: Decimal

    safety_buffer: Decimal
    buffer_breached_before: bool
    buffer_breached_after: bool
    buffer_headroom_before: Decimal
    buffer_headroom_after: Decimal

    risk_before: str
    risk_after: str
    risk_change: str                  # "unchanged" | "worsened" | "improved"

    goal_impact: GoalImpact
    recommended_wait_days: Optional[int]
    largest_safe_amount: Optional[Decimal]
    reason_codes: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "amount": str(self.amount),
            "category": self.category,
            "description": self.description,
            "as_of": self.as_of.isoformat(),
            "purchase_date": self.purchase_date.isoformat(),
            "horizon_days": self.horizon_days,
            "affordable_today": self.affordable_today,
            "safe_to_spend": self.safe_to_spend,
            "affordability_verdict": self.affordability_verdict,
            "affordability_score": self.affordability_score,
            "current_balance": str(self.current_balance),
            "buffer_impact": str(self.buffer_impact),
            "minimum_balance_before": str(self.minimum_balance_before),
            "minimum_balance_after": str(self.minimum_balance_after),
            "minimum_balance_date_before": self.minimum_balance_date_before.isoformat(),
            "minimum_balance_date_after": self.minimum_balance_date_after.isoformat(),
            "month_end_balance_before": str(self.month_end_balance_before),
            "month_end_balance_after": str(self.month_end_balance_after),
            "safety_buffer": str(self.safety_buffer),
            "buffer_breached_before": self.buffer_breached_before,
            "buffer_breached_after": self.buffer_breached_after,
            "buffer_headroom_before": str(self.buffer_headroom_before),
            "buffer_headroom_after": str(self.buffer_headroom_after),
            "risk_before": self.risk_before,
            "risk_after": self.risk_after,
            "risk_change": self.risk_change,
            "goal_impact": self.goal_impact.to_dict(),
            "goal_delay_days": self.goal_impact.delay_days,
            "goal_delay_months": self.goal_impact.delay_months,
            "recommended_wait_days": self.recommended_wait_days,
            "largest_safe_amount": (str(self.largest_safe_amount)
                                    if self.largest_safe_amount is not None else None),
            "reason_codes": list(self.reason_codes),
        }


# --------------------------------------------------------------------- helpers

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _balance_on(projection, target: date) -> Decimal:
    """End-of-day balance on ``target`` (clamped to the projected range)."""
    pts = projection.points
    if target <= pts[0].date:
        return pts[0].balance
    if target >= pts[-1].date:
        return pts[-1].balance
    for p in pts:
        if p.date == target:
            return p.balance
    return pts[-1].balance  # unreachable (contiguous daily points)


def _risk(min_balance: Decimal, buffer: Decimal) -> str:
    if min_balance < buffer:
        return RISK_AT_RISK
    if (min_balance - buffer) < (buffer * CAUTION_BUFFER_FRACTION):
        return RISK_CAUTION
    return RISK_HEALTHY


def _scenario_projection(twin, amount: Decimal, purchase_date: date, span: int):
    return project_daily_balances(
        twin,
        horizon_days=span,
        extra_events=[ProjectionEvent(purchase_date, -amount, "purchase", "decision")],
    )


def _reason_codes(*, affordable_today, min_before, min_after, breached_before, breached_after,
                  risk_change, recommended_wait_days, decision, buffer, goal, goal_escalated):
    codes: List[str] = []
    codes.append("affordable_today" if affordable_today else "would_overdraft_today")
    if min_after < min_before:
        codes.append("reduces_minimum_balance")
    elif min_after == min_before:
        codes.append("minimum_balance_unchanged")
    if breached_after and not breached_before:
        codes.append("breaches_safety_buffer")
    if breached_before and breached_after and min_after < min_before:
        codes.append("deepens_buffer_shortfall")
    if min_after < ZERO:
        codes.append("projected_overdraft")
    codes.append(f"risk_{risk_change}")
    if recommended_wait_days is not None:
        codes.append(f"recovers_in_{recommended_wait_days}_days")
    if decision == DECISION_SPEND_LESS:
        codes.append("smaller_purchase_stays_safe")
    if (decision == DECISION_BUY and risk_change == "unchanged"
            and abs(min_before - min_after) < (buffer * _TRIVIAL_FRACTION if buffer > 0 else abs(min_before - min_after))):
        codes.append("no_meaningful_impact")
    # goal-impact reason codes
    if not goal.available:
        codes.append("goal_impact_unavailable")
    elif goal.delay_months and goal.delay_months > 0:
        codes.append(f"delays_goal_by_{goal.delay_months}_months")
        if goal_escalated:
            codes.append("delays_goal_significantly")
    else:
        codes.append("goal_unaffected")
    return tuple(codes)


# --------------------------------------------------------------------- engine

def evaluate_consequence(
    twin,
    *,
    amount,
    category: Optional[str] = None,
    description: Optional[str] = None,
    purchase_date: Optional[date] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    goals=None,
    goal_id: Optional[int] = None,
) -> ConsequenceResult:
    """Evaluate the future consequence of a hypothetical purchase against ``twin``.

    ``goals`` (optional) is a list of :class:`finance.models.SavingsGoal`. With
    no goals the goal-impact block is ``available=False`` and the decision is
    computed exactly as in Phase 10 — passing goals is purely additive.

    Raises ``ValueError`` for a non-positive amount or a past purchase date.
    Never mutates ``twin`` or anything else.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise ValueError("amount must be greater than 0")

    purchase_date = purchase_date or twin.as_of
    if purchase_date < twin.as_of:
        raise ValueError("purchase_date must not be before today")

    horizon_days = max(int(horizon_days), 0)
    month_end = _last_day_of_month(twin.as_of)
    # cover the 30-day (or requested) window, month-end, and a wait search past a
    # far-dated purchase.
    span = max(
        horizon_days,
        (month_end - twin.as_of).days,
        (purchase_date - twin.as_of).days + horizon_days,
        (purchase_date - twin.as_of).days + MAX_WAIT_SEARCH_DAYS,
    )

    baseline = project_daily_balances(twin, horizon_days=span)
    scenario = _scenario_projection(twin, amount, purchase_date, span)

    buffer = money(twin.safety_buffer)
    min_before = baseline.min_balance
    min_after = scenario.min_balance
    me_before = _balance_on(baseline, month_end)
    me_after = _balance_on(scenario, month_end)

    bal_on_pdate = _balance_on(baseline, purchase_date)
    affordable_today = (bal_on_pdate - amount) >= ZERO
    safe_to_spend = min_after >= ZERO

    breached_before = min_before < buffer
    breached_after = min_after < buffer

    risk_before = _risk(min_before, buffer)
    risk_after = _risk(min_after, buffer)
    if _RISK_ORD[risk_after] > _RISK_ORD[risk_before]:
        risk_change = "worsened"
    elif _RISK_ORD[risk_after] < _RISK_ORD[risk_before]:
        risk_change = "improved"
    else:
        risk_change = "unchanged"

    aff = check_affordability(twin, amount=amount, category=category,
                              purchase_date=purchase_date, horizon_days=horizon_days)

    recommended_wait_days = None
    if breached_after:
        for d in range(1, min(MAX_WAIT_SEARCH_DAYS, span) + 1):
            later = _scenario_projection(twin, amount, purchase_date + timedelta(days=d), span)
            if later.min_balance >= buffer:
                recommended_wait_days = d
                break

    largest_safe_amount = None
    for frac in _SPEND_LESS_FRACTIONS:
        cand = money(amount * frac)
        if cand <= ZERO:
            continue
        smaller = _scenario_projection(twin, cand, purchase_date, span)
        if smaller.min_balance >= buffer:
            largest_safe_amount = cand
            break

    if (min_after < ZERO) or (not affordable_today):
        decision = DECISION_AVOID
    elif breached_after:
        if recommended_wait_days is not None:
            decision = DECISION_WAIT
        elif largest_safe_amount is not None:
            decision = DECISION_SPEND_LESS
        else:
            decision = DECISION_AVOID
    elif risk_change == "worsened":
        decision = DECISION_SPEND_LESS
    else:
        decision = DECISION_BUY

    goal = evaluate_goal_impact(
        twin, amount=amount, purchase_date=purchase_date, goals=goals, goal_id=goal_id,
    )

    # goal escalation rule (see GOAL_ESCALATE_DELAY_MONTHS) — the only way a goal
    # touches the decision, and only from a clean BUY.
    goal_escalated = (
        decision == DECISION_BUY
        and goal.available
        and goal.delay_months is not None
        and goal.delay_months >= GOAL_ESCALATE_DELAY_MONTHS
    )
    if goal_escalated:
        decision = DECISION_SPEND_LESS
        if largest_safe_amount is None:
            # the buffer never forced a smaller amount; offer a goal-safe one
            for frac in _SPEND_LESS_FRACTIONS:
                cand = money(amount * frac)
                if cand <= ZERO:
                    continue
                gi = evaluate_goal_impact(
                    twin, amount=cand, purchase_date=purchase_date,
                    goals=goals, goal_id=goal_id,
                )
                if not gi.available or (gi.delay_months or 0) < GOAL_ESCALATE_DELAY_MONTHS:
                    largest_safe_amount = cand
                    break

    codes = _reason_codes(
        affordable_today=affordable_today, min_before=min_before, min_after=min_after,
        breached_before=breached_before, breached_after=breached_after,
        risk_change=risk_change, recommended_wait_days=recommended_wait_days,
        decision=decision, buffer=buffer, goal=goal, goal_escalated=goal_escalated,
    )

    return ConsequenceResult(
        decision=decision,
        amount=amount,
        category=category,
        description=description,
        as_of=twin.as_of,
        purchase_date=purchase_date,
        horizon_days=horizon_days,
        affordable_today=affordable_today,
        safe_to_spend=safe_to_spend,
        affordability_verdict=aff.verdict,
        affordability_score=aff.score,
        current_balance=money(twin.current_balance),
        buffer_impact=money(-amount),
        minimum_balance_before=money(min_before),
        minimum_balance_after=money(min_after),
        minimum_balance_date_before=baseline.min_date,
        minimum_balance_date_after=scenario.min_date,
        month_end_balance_before=money(me_before),
        month_end_balance_after=money(me_after),
        safety_buffer=buffer,
        buffer_breached_before=breached_before,
        buffer_breached_after=breached_after,
        buffer_headroom_before=money(min_before - buffer),
        buffer_headroom_after=money(min_after - buffer),
        risk_before=risk_before,
        risk_after=risk_after,
        risk_change=risk_change,
        goal_impact=goal,
        recommended_wait_days=recommended_wait_days,
        largest_safe_amount=largest_safe_amount,
        reason_codes=codes,
    )
