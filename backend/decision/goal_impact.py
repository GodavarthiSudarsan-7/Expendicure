"""Deterministic goal impact.

Answers: "does this purchase (or unexpected spend) delay a savings goal, and by
how much?"

Model (documented, deterministic):
  A discretionary spend of ``amount`` is money that would otherwise have been
  available to put toward a goal. It does NOT reduce the goal's saved-so-far
  pot — it delays the *timeline*. So we re-run the simple linear top-up model
  with ``amount`` added back onto what still has to be saved:

    remaining_before = max(0, target - current)
    remaining_after  = remaining_before + amount
    months_before    = ceil(remaining_before / monthly_contribution)
    months_after     = ceil(remaining_after  / monthly_contribution)
    delay_months     = months_after - months_before
    delay_days       = est_completion_after - est_completion_before   (exact dates)

  We also report where the goal lands *by its target date* with vs without the
  spend (projected_at_target_before / _after, shortfall_at_target).

Primary goal (when no ``goal_id`` is given): among ``status='active'`` goals
that have a positive ``monthly_contribution``, the one with the earliest
``target_date`` (tie-break: lowest id). If none qualifies, impact is
``available=False`` — never a fabricated delay.

Pure ``Decimal`` arithmetic. No LLM, no DB, no projection kernel.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING
from typing import List, Optional

from finance.money import ZERO, money
from finance.recurrence import add_months

_NO_GOAL_REASON = "no savings goal is configured for this account"
_NO_CONTRIB_REASON = "no active savings goal has a monthly contribution set"


@dataclass(frozen=True)
class GoalImpact:
    available: bool
    delay_days: Optional[int]
    reason: str

    # rich fields — only meaningful (and only serialised) when available
    goal_id: Optional[int] = None
    goal_name: Optional[str] = None
    delay_months: Optional[int] = None
    target_amount: Optional[Decimal] = None
    current_amount: Optional[Decimal] = None
    remaining_before: Optional[Decimal] = None
    remaining_after: Optional[Decimal] = None
    monthly_contribution: Optional[Decimal] = None
    estimated_completion_before: Optional[date] = None
    estimated_completion_after: Optional[date] = None
    target_date: Optional[date] = None
    projected_at_target_before: Optional[Decimal] = None
    projected_at_target_after: Optional[Decimal] = None
    shortfall_at_target: Optional[Decimal] = None
    on_track_before: Optional[bool] = None
    on_track_after: Optional[bool] = None
    additional_contribution_required: Optional[Decimal] = None

    def to_dict(self) -> dict:
        d = {
            "available": self.available,
            "delay_days": self.delay_days,
            "reason": self.reason,
        }
        if not self.available:
            return d
        d.update({
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "delay_months": self.delay_months,
            "target_amount": _s(self.target_amount),
            "current_amount": _s(self.current_amount),
            "remaining_before": _s(self.remaining_before),
            "remaining_after": _s(self.remaining_after),
            "monthly_contribution": _s(self.monthly_contribution),
            "estimated_completion_before": _iso(self.estimated_completion_before),
            "estimated_completion_after": _iso(self.estimated_completion_after),
            "target_date": _iso(self.target_date),
            "projected_at_target_before": _s(self.projected_at_target_before),
            "projected_at_target_after": _s(self.projected_at_target_after),
            "shortfall_at_target": _s(self.shortfall_at_target),
            "on_track_before": self.on_track_before,
            "on_track_after": self.on_track_after,
            "additional_contribution_required": _s(self.additional_contribution_required),
        })
        return d


def _s(v):
    return None if v is None else str(v)


def _iso(v):
    return None if v is None else v.isoformat()


def _ceil_months(remaining: Decimal, contribution: Decimal) -> int:
    if remaining <= ZERO:
        return 0
    return int((remaining / contribution).to_integral_value(rounding=ROUND_CEILING))


def _months_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        m -= 1
    return max(0, m)


def select_primary_goal(goals, *, goal_id: Optional[int] = None):
    """Deterministic primary-goal choice. Returns a goal or ``None``."""
    active = [
        g for g in (goals or [])
        if str(getattr(g, "status", "active")) == "active"
    ]
    if goal_id is not None:
        for g in active:
            if getattr(g, "id", None) == goal_id:
                return g
        return None
    fundable = [g for g in active if money(g.monthly_contribution) > ZERO]
    if not fundable:
        return None
    return sorted(fundable, key=lambda g: (g.target_date, getattr(g, "id", 0)))[0]


def evaluate_goal_impact(
    twin,
    *,
    amount: Decimal,
    purchase_date: date,
    goals: Optional[List] = None,
    goal_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> GoalImpact:
    """How ``amount`` spent on ``purchase_date`` affects the primary savings goal.

    ``goals`` is a list of :class:`finance.models.SavingsGoal`. With no goals
    the result is ``available=False`` with the historical reason string, so
    callers that pass nothing keep the Phase 10 behaviour exactly.
    """
    as_of = as_of or getattr(twin, "as_of", None) or purchase_date
    amount = money(amount)

    if not goals:
        return GoalImpact(available=False, delay_days=None, reason=_NO_GOAL_REASON)

    goal = select_primary_goal(goals, goal_id=goal_id)
    if goal is None:
        return GoalImpact(available=False, delay_days=None, reason=_NO_CONTRIB_REASON)

    contribution = money(goal.monthly_contribution)
    if contribution <= ZERO:
        return GoalImpact(available=False, delay_days=None,
                          reason=f"goal '{goal.name}' has no monthly contribution set")

    target = money(goal.target_amount)
    current = money(goal.current_amount)
    remaining_before = target - current
    if remaining_before < ZERO:
        remaining_before = ZERO
    remaining_after = remaining_before + amount

    months_before = _ceil_months(remaining_before, contribution)
    months_after = _ceil_months(remaining_after, contribution)
    delay_months = months_after - months_before

    est_before = add_months(as_of, months_before)
    est_after = add_months(as_of, months_after)
    delay_days = (est_after - est_before).days

    months_left = _months_between(as_of, goal.target_date)
    proj_before = current + contribution * months_left
    if proj_before > target:
        proj_before = target
    proj_after = current + contribution * months_left - amount
    if proj_after > target:
        proj_after = target
    shortfall = target - proj_after
    if shortfall < ZERO:
        shortfall = ZERO

    reason = (
        f"goal '{goal.name}' is unaffected" if delay_months == 0 else
        f"buying this delays goal '{goal.name}' by about {delay_months} month"
        f"{'s' if delay_months != 1 else ''}"
    )

    return GoalImpact(
        available=True,
        delay_days=int(delay_days),
        reason=reason,
        goal_id=getattr(goal, "id", None),
        goal_name=goal.name,
        delay_months=int(delay_months),
        target_amount=target,
        current_amount=current,
        remaining_before=money(remaining_before),
        remaining_after=money(remaining_after),
        monthly_contribution=contribution,
        estimated_completion_before=est_before,
        estimated_completion_after=est_after,
        target_date=goal.target_date,
        projected_at_target_before=money(proj_before),
        projected_at_target_after=money(proj_after),
        shortfall_at_target=money(shortfall),
        on_track_before=est_before <= goal.target_date,
        on_track_after=est_after <= goal.target_date,
        additional_contribution_required=money(amount),
    )
