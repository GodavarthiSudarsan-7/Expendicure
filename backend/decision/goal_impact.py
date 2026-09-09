"""Deterministic goal impact.

Answers: "does this purchase delay a savings goal, and by how many days?"

STATUS: the current data model has **no** savings-goal / target concept
(inspected: ``TwinState`` has no goal fields; no ``savings_goals`` table in
``database/migrations/``). So goal impact is reported as *unavailable* rather
than fabricated.

To make this real, a future phase needs, per student:
  - ``target_amount``     (Decimal)  — how much they're saving toward
  - ``target_date``       (date)     — when they want it by
  - a contribution rate   (Decimal per month) OR a start balance for the goal

Given those, the delay is deterministic:
  months_needed_baseline = ceil((target_amount - saved_so_far) / monthly_contribution)
  months_needed_after    = ceil((target_amount - (saved_so_far - purchase_amount)) / monthly_contribution)
  delay_days = (months_needed_after - months_needed_baseline) * 30   (or exact date math)

Until then this returns ``available=False`` and ``delay_days=None``.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class GoalImpact:
    available: bool
    delay_days: Optional[int]
    reason: str

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "delay_days": self.delay_days,
            "reason": self.reason,
        }


def evaluate_goal_impact(twin, *, amount: Decimal, purchase_date: date) -> GoalImpact:
    """Return a :class:`GoalImpact`. Currently always unavailable — see module docstring."""
    if getattr(twin, "savings_goal", None):  # forward-compatible hook; not set today
        return _delay_from_goal(twin.savings_goal, amount)
    return GoalImpact(
        available=False,
        delay_days=None,
        reason="no savings goal is configured for this account",
    )


def _delay_from_goal(goal, amount):  # pragma: no cover - reserved for a later phase
    from decimal import ROUND_CEILING
    contribution = goal.get("monthly_contribution")
    if not contribution or contribution <= 0:
        return GoalImpact(False, None, "goal has no contribution rate")
    remaining_before = max(Decimal("0"), goal["target_amount"] - goal.get("saved_so_far", Decimal("0")))
    remaining_after = remaining_before + amount
    months_before = (remaining_before / contribution).to_integral_value(rounding=ROUND_CEILING)
    months_after = (remaining_after / contribution).to_integral_value(rounding=ROUND_CEILING)
    delay_days = int((months_after - months_before) * 30)
    return GoalImpact(True, delay_days, f"purchase adds ~{delay_days} days to the goal")
