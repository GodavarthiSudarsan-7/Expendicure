"""Deterministic savings-goal progress.

Given a :class:`finance.models.SavingsGoal` and a reference date, work out how
far along the goal is and whether the planned monthly contribution will hit the
target by the target date. Pure arithmetic on ``Decimal`` — no LLM, no DB, no
projection kernel needed (a goal is a simple linear top-up model).

Every field that cannot be computed safely is returned as ``None`` with a
reason string; nothing is fabricated.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Optional

from finance.money import ZERO, money
from finance.recurrence import add_months

STATUS_ACHIEVED = "achieved"
STATUS_ON_TRACK = "on_track"
STATUS_BEHIND = "behind"
STATUS_UNKNOWN = "unknown"

_PCT = Decimal("0.01")
# a goal whose planned finish is more than this many days past the target date
# is "behind"; within it (or earlier) is "on_track".
ON_TRACK_GRACE_DAYS = 15


@dataclass(frozen=True)
class GoalProgress:
    available: bool
    reason: str

    goal_id: Optional[int] = None
    name: Optional[str] = None
    target_amount: Optional[Decimal] = None
    current_amount: Optional[Decimal] = None
    remaining_amount: Optional[Decimal] = None
    percent_complete: Optional[Decimal] = None       # 0-100, 2dp
    target_date: Optional[date] = None
    monthly_contribution: Optional[Decimal] = None

    months_to_target: Optional[int] = None            # ceil(remaining / contribution)
    estimated_completion_date: Optional[date] = None
    months_until_target_date: Optional[int] = None
    required_monthly_contribution: Optional[Decimal] = None  # to hit target_date
    contribution_gap: Optional[Decimal] = None        # required - planned (>=0)

    on_track: Optional[bool] = None
    status: str = STATUS_UNKNOWN

    def to_dict(self) -> dict:
        d = {"available": self.available, "reason": self.reason, "status": self.status}
        if not self.available:
            return d
        d.update({
            "goal_id": self.goal_id,
            "name": self.name,
            "target_amount": _s(self.target_amount),
            "current_amount": _s(self.current_amount),
            "remaining_amount": _s(self.remaining_amount),
            "percent_complete": _s(self.percent_complete),
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "monthly_contribution": _s(self.monthly_contribution),
            "months_to_target": self.months_to_target,
            "estimated_completion_date": (
                self.estimated_completion_date.isoformat()
                if self.estimated_completion_date else None
            ),
            "months_until_target_date": self.months_until_target_date,
            "required_monthly_contribution": _s(self.required_monthly_contribution),
            "contribution_gap": _s(self.contribution_gap),
            "on_track": self.on_track,
        })
        return d


def _s(v: Optional[Decimal]) -> Optional[str]:
    return None if v is None else str(v)


def _months_between(start: date, end: date) -> int:
    """Whole calendar months from ``start`` to ``end`` (0 if ``end`` <= ``start``)."""
    if end <= start:
        return 0
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        m -= 1
    return max(0, m)


def compute_goal_progress(goal, *, as_of: Optional[date] = None) -> GoalProgress:
    """Deterministic progress for one goal."""
    as_of = as_of or date.today()

    target = money(goal.target_amount)
    current = money(goal.current_amount)
    contribution = money(goal.monthly_contribution)

    if target <= ZERO:
        return GoalProgress(available=False, reason="goal has no positive target amount")

    remaining = target - current
    if remaining < ZERO:
        remaining = ZERO
    percent = (current / target * 100).quantize(_PCT, rounding=ROUND_HALF_UP)
    if percent > 100:
        percent = Decimal("100.00")

    common = dict(
        available=True, reason="ok",
        goal_id=getattr(goal, "id", None), name=goal.name,
        target_amount=target, current_amount=current, remaining_amount=money(remaining),
        percent_complete=percent, target_date=goal.target_date,
        monthly_contribution=contribution,
    )

    # already there
    if remaining == ZERO or str(goal.status) == "achieved":
        return GoalProgress(**common, months_to_target=0,
                            estimated_completion_date=as_of, on_track=True,
                            status=STATUS_ACHIEVED)

    months_until_target = _months_between(as_of, goal.target_date)

    # required contribution to hit the target date
    required_monthly = None
    contribution_gap = None
    if months_until_target > 0:
        required_monthly = (remaining / months_until_target).quantize(_PCT, rounding=ROUND_CEILING)
        gap = required_monthly - contribution
        contribution_gap = money(gap if gap > ZERO else ZERO)

    # projected completion from the planned contribution
    months_to_target = None
    est_completion = None
    on_track = None
    status = STATUS_UNKNOWN
    if contribution > ZERO:
        months_to_target = int((remaining / contribution).to_integral_value(rounding=ROUND_CEILING))
        est_completion = add_months(as_of, months_to_target)
        slip_days = (est_completion - goal.target_date).days
        on_track = slip_days <= ON_TRACK_GRACE_DAYS
        status = STATUS_ON_TRACK if on_track else STATUS_BEHIND
    else:
        status = STATUS_BEHIND if months_until_target == 0 else STATUS_UNKNOWN

    return GoalProgress(
        **common,
        months_to_target=months_to_target,
        estimated_completion_date=est_completion,
        months_until_target_date=months_until_target,
        required_monthly_contribution=required_monthly,
        contribution_gap=contribution_gap,
        on_track=on_track,
        status=status,
    )
