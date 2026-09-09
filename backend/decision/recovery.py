"""Recovery Mode — "I already spent the money, how do I get back on track?"

Deterministic. Given the current twin and an unexpected spend:

    CURRENT STATE  -> project_daily_balances(twin)                     (no shock)
    NEW BASELINE   -> project_daily_balances(twin, [the shock])        (shock, no recovery)
    RECOVERY OPT   -> project_daily_balances(twin, [shock, +recovery]) (shock + one option)
    COMPARE        -> min balance / risk with vs without the option; rank.

Every option is simulated through the SAME shared kernel (``finance.projection``)
— no second projection implementation. Recovery is read-only: nothing here
writes to the database or mutates the twin. Options never recommend negative
spending, impossible amounts, cutting essential expenses, or inventing income.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from typing import List, Optional

from finance.money import ZERO, money
from finance.projection import ProjectionEvent, project_daily_balances
from decision.consequence_engine import _risk, RISK_HEALTHY, RISK_CAUTION, RISK_AT_RISK
from decision.goal_impact import evaluate_goal_impact, select_primary_goal

RECOVERY_HORIZON_DAYS = 45
_SPREAD_WEEKS = (2, 4, 6, 8)
_REDUCE_MONTHS = (1, 2, 3)
_MAX_WAIT_DAYS = 45


@dataclass(frozen=True)
class RecoveryOption:
    action: str
    label: str
    amount: Optional[Decimal]           # total rupees this option frees / defers
    monthly_amount: Optional[Decimal]
    weekly_amount: Optional[Decimal]
    duration_days: Optional[int]
    projected_min_without_recovery: Decimal
    projected_min_with_recovery: Decimal
    buffer_restored: bool
    risk_after: str
    goal_delay_months: Optional[int]    # extra goal delay THIS option causes
    feasible: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "label": self.label,
            "amount": _s(self.amount),
            "monthly_amount": _s(self.monthly_amount),
            "weekly_amount": _s(self.weekly_amount),
            "duration_days": self.duration_days,
            "projected_min_without_recovery": _s(self.projected_min_without_recovery),
            "projected_min_with_recovery": _s(self.projected_min_with_recovery),
            "buffer_restored": self.buffer_restored,
            "risk_after": self.risk_after,
            "goal_delay_months": self.goal_delay_months,
            "feasible": self.feasible,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RecoveryResult:
    available: bool
    needed: bool
    amount: Decimal
    spent_date: date
    as_of: date
    category: Optional[str]
    description: Optional[str]

    current_balance: Decimal
    safety_buffer: Decimal
    projected_min_baseline: Decimal        # no shock
    projected_min_after_spend: Decimal     # shock, no recovery
    gap: Decimal                           # max(0, safety_buffer - projected_min_after_spend)
    risk_after_spend: str

    goal_impact: dict
    options: List[RecoveryOption]
    recommended: Optional[dict]
    reason_codes: List[str]

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "needed": self.needed,
            "amount": _s(self.amount),
            "spent_date": self.spent_date.isoformat(),
            "as_of": self.as_of.isoformat(),
            "category": self.category,
            "description": self.description,
            "current_balance": _s(self.current_balance),
            "safety_buffer": _s(self.safety_buffer),
            "projected_min_baseline": _s(self.projected_min_baseline),
            "projected_min_after_spend": _s(self.projected_min_after_spend),
            "gap": _s(self.gap),
            "risk_after_spend": self.risk_after_spend,
            "goal_impact": self.goal_impact,
            "goal_delay_days": self.goal_impact.get("delay_days"),
            "goal_delay_months": self.goal_impact.get("delay_months"),
            "options": [o.to_dict() for o in self.options],
            "recommended": self.recommended,
            "reason_codes": list(self.reason_codes),
        }


def _s(v):
    return None if v is None else str(v)


def _ceil_money(numer: Decimal, denom: int) -> Decimal:
    if denom <= 0:
        return money(numer)
    return (numer / denom).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


# --------------------------------------------------------------------- engine

def evaluate_recovery(
    twin,
    *,
    amount,
    category: Optional[str] = None,
    description: Optional[str] = None,
    spent_date: Optional[date] = None,
    goals=None,
    goal_id: Optional[int] = None,
    horizon_days: int = RECOVERY_HORIZON_DAYS,
) -> RecoveryResult:
    """Build and rank deterministic recovery options for an unexpected spend.

    The spend is modelled as a shock applied to the *current* twin at
    ``spent_date`` (default: today). Raises ``ValueError`` for a non-positive
    amount or a past ``spent_date``. Never mutates anything.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise ValueError("amount must be greater than 0")

    as_of = twin.as_of
    spent_date = spent_date or as_of
    if spent_date < as_of:
        raise ValueError("spent_date must not be before today")

    buffer = money(twin.safety_buffer)
    horizon_days = max(int(horizon_days), 1)
    span = max(horizon_days, (spent_date - as_of).days + horizon_days)

    baseline = project_daily_balances(twin, horizon_days=span)
    shock = ProjectionEvent(spent_date, -amount, "unexpected", "recovery")
    after_spend = project_daily_balances(twin, horizon_days=span, extra_events=[shock])

    min_baseline = money(baseline.min_balance)
    min_after_spend = money(after_spend.min_balance)
    gap = buffer - min_after_spend
    if gap < ZERO:
        gap = ZERO
    gap = money(gap)
    risk_after_spend = _risk(min_after_spend, buffer)

    goal_impact = evaluate_goal_impact(
        twin, amount=amount, purchase_date=spent_date, goals=goals, goal_id=goal_id,
    ).to_dict()

    reason_codes: List[str] = []
    if goal_impact.get("available") and (goal_impact.get("delay_months") or 0) > 0:
        reason_codes.append(f"spend_delays_goal_by_{goal_impact['delay_months']}_months")

    # ---- no recovery needed ------------------------------------------------
    if gap <= ZERO:
        reason_codes.insert(0, "buffer_not_breached")
        return RecoveryResult(
            available=True, needed=False, amount=amount, spent_date=spent_date, as_of=as_of,
            category=category, description=description,
            current_balance=money(twin.current_balance), safety_buffer=buffer,
            projected_min_baseline=min_baseline, projected_min_after_spend=min_after_spend,
            gap=gap, risk_after_spend=risk_after_spend, goal_impact=goal_impact,
            options=[], recommended=None, reason_codes=reason_codes,
        )

    reason_codes.insert(0, f"buffer_gap_{int(gap)}")

    def simulate(events) -> tuple:
        p = project_daily_balances(twin, horizon_days=span, extra_events=[shock, *events])
        m = money(p.min_balance)
        return m, _risk(m, buffer)

    options: List[RecoveryOption] = []
    options += _reduce_discretionary(twin, as_of, buffer, gap, min_after_spend, simulate)
    options += _spread_recovery(twin, as_of, buffer, gap, min_after_spend, simulate)
    options += _delay_planned_expense(twin, as_of, buffer, after_spend, simulate)
    options += _pause_goal_contribution(twin, as_of, buffer, min_after_spend, goals, goal_id, simulate)
    options += _wait_before_purchases(as_of, buffer, after_spend, span, min_after_spend)

    # rank: feasible & restoring first, then least goal disruption, least money,
    # shortest duration; feasible-but-partial next; infeasible last.
    def rank_key(o: RecoveryOption):
        return (
            0 if (o.feasible and o.buffer_restored) else (1 if o.feasible else 2),
            o.goal_delay_months or 0,
            o.amount if o.amount is not None else Decimal("1e12"),
            o.duration_days or 0,
        )

    options.sort(key=rank_key)
    best = next((o for o in options if o.feasible and o.buffer_restored), None)
    if best is None:
        best = next((o for o in options if o.feasible), None)
    recommended = best.to_dict() if best is not None else None
    if best is not None:
        reason_codes.append(f"recommend_{best.action}")

    return RecoveryResult(
        available=True, needed=True, amount=amount, spent_date=spent_date, as_of=as_of,
        category=category, description=description,
        current_balance=money(twin.current_balance), safety_buffer=buffer,
        projected_min_baseline=min_baseline, projected_min_after_spend=min_after_spend,
        gap=gap, risk_after_spend=risk_after_spend, goal_impact=goal_impact,
        options=options, recommended=recommended, reason_codes=reason_codes,
    )


# --------------------------------------------------------------------- options

def _reduce_discretionary(twin, as_of, buffer, gap, min_after_spend, simulate) -> List[RecoveryOption]:
    """Trim discretionary spending by a fixed amount each month for N months.
    The first month's saving is modelled as freed today (you decide now not to
    spend it); later months land at monthly intervals."""
    capacity = money(getattr(twin, "month_discretionary_spending", ZERO) or ZERO)
    if capacity <= ZERO:
        return [RecoveryOption(
            action="reduce_discretionary", label="Reduce discretionary spending",
            amount=None, monthly_amount=None, weekly_amount=None, duration_days=None,
            projected_min_without_recovery=money(min_after_spend),
            projected_min_with_recovery=money(min_after_spend),
            buffer_restored=False, risk_after=_risk(money(min_after_spend), buffer),
            goal_delay_months=None, feasible=False,
            reason="no discretionary spending recorded this month to trim",
        )]

    best = None
    for m in _REDUCE_MONTHS:
        monthly_cut = _ceil_money(gap, m)
        if monthly_cut > capacity:
            monthly_cut = capacity
        events = [
            ProjectionEvent(_add_months(as_of, k), monthly_cut, "recovery_reduce", "recovery")
            for k in range(0, m)
        ]
        min_with, risk = simulate(events)
        total = money(monthly_cut * m)
        opt = RecoveryOption(
            action="reduce_discretionary",
            label=f"Cut discretionary spending by {monthly_cut} / month for {m} month{'s' if m != 1 else ''}",
            amount=total, monthly_amount=monthly_cut, weekly_amount=None,
            duration_days=m * 30,
            projected_min_without_recovery=money(min_after_spend),
            projected_min_with_recovery=min_with,
            buffer_restored=min_with >= buffer, risk_after=risk,
            goal_delay_months=0, feasible=True,
            reason=(f"trim {monthly_cut}/month (within your {capacity} discretionary spend)"),
        )
        if opt.buffer_restored:
            return [opt]
        best = opt if best is None else best
    return [best] if best is not None else []


def _spread_recovery(twin, as_of, buffer, gap, min_after_spend, simulate) -> List[RecoveryOption]:
    """Set aside a smaller amount each week for a few weeks until the gap is covered.
    The first week's set-aside is modelled as freed today."""
    weekly_capacity = money((getattr(twin, "month_discretionary_spending", ZERO) or ZERO) / 4)
    best = None
    for w in _SPREAD_WEEKS:
        weekly = _ceil_money(gap, w)
        feasible = weekly_capacity > ZERO and weekly <= weekly_capacity
        events = [
            ProjectionEvent(as_of + timedelta(days=7 * k), weekly, "recovery_spread", "recovery")
            for k in range(0, w)
        ]
        min_with, risk = simulate(events)
        opt = RecoveryOption(
            action="spread_recovery",
            label=f"Set aside {weekly} / week for {w} weeks",
            amount=money(weekly * w), monthly_amount=None, weekly_amount=weekly,
            duration_days=w * 7,
            projected_min_without_recovery=money(min_after_spend),
            projected_min_with_recovery=min_with,
            buffer_restored=min_with >= buffer, risk_after=risk,
            goal_delay_months=0, feasible=feasible,
            reason=("weekly amount fits your discretionary room"
                    if feasible else
                    f"{weekly}/week exceeds your ~{weekly_capacity}/week discretionary room"),
        )
        if feasible and opt.buffer_restored:
            return [opt]
        if best is None or (opt.feasible and not best.feasible):
            best = opt
    return [best] if best is not None else []


def _delay_planned_expense(twin, as_of, buffer, after_spend, simulate) -> List[RecoveryOption]:
    """Push the soonest upcoming recurring debit out by a month so its outflow
    lands after the low point."""
    trough_date = after_spend.min_date
    candidates = [
        r for r in getattr(twin, "recurring", ())
        if getattr(r, "active", True) and getattr(r, "direction", "debit") == "debit"
        and as_of <= r.next_date <= trough_date
    ]
    if not candidates:
        return [RecoveryOption(
            action="delay_planned_expense", label="Delay a planned expense",
            amount=None, monthly_amount=None, weekly_amount=None, duration_days=None,
            projected_min_without_recovery=money(after_spend.min_balance),
            projected_min_with_recovery=money(after_spend.min_balance),
            buffer_restored=False, risk_after=_risk(money(after_spend.min_balance), buffer),
            goal_delay_months=None, feasible=False,
            reason="no upcoming bill falls before your projected low point",
        )]
    rec = min(candidates, key=lambda r: (r.next_date, getattr(r, "id", 0)))
    amt = money(rec.amount)
    events = [
        ProjectionEvent(rec.next_date, amt, "recovery_delay_in", "recovery"),
        ProjectionEvent(rec.next_date + timedelta(days=30), -amt, "recovery_delay_out", "recovery"),
    ]
    min_with, risk = simulate(events)
    return [RecoveryOption(
        action="delay_planned_expense",
        label=f"Delay '{rec.label}' ({amt}) by ~30 days",
        amount=amt, monthly_amount=None, weekly_amount=None, duration_days=30,
        projected_min_without_recovery=money(after_spend.min_balance),
        projected_min_with_recovery=min_with,
        buffer_restored=min_with >= buffer, risk_after=risk,
        goal_delay_months=0, feasible=True,
        reason=f"move '{rec.label}' past the low point; it is still paid, one cycle later",
    )]


def _pause_goal_contribution(twin, as_of, buffer, min_after_spend, goals, goal_id, simulate) -> List[RecoveryOption]:
    goal = select_primary_goal(goals, goal_id=goal_id)
    if goal is None or money(goal.monthly_contribution) <= ZERO:
        return []
    contribution = money(goal.monthly_contribution)
    events = [ProjectionEvent(as_of, contribution, "recovery_pause_goal", "recovery")]
    min_with, risk = simulate(events)
    return [RecoveryOption(
        action="pause_goal_contribution",
        label=f"Skip one {contribution} contribution to '{goal.name}'",
        amount=contribution, monthly_amount=contribution, weekly_amount=None,
        duration_days=30,
        projected_min_without_recovery=money(min_after_spend),
        projected_min_with_recovery=min_with,
        buffer_restored=min_with >= buffer, risk_after=risk,
        goal_delay_months=1, feasible=True,
        reason=f"redirect one month's goal contribution to rebuild the buffer (delays '{goal.name}' ~1 month)",
    )]


def _wait_before_purchases(as_of, buffer, after_spend, span, min_after_spend) -> List[RecoveryOption]:
    """No new discretionary spending — let time and known income restore the
    buffer. Adds no money; just finds how many days until the balance is back
    above the buffer and stays there."""
    pts = after_spend.points
    n = None
    for i, p in enumerate(pts):
        if all(q.balance >= buffer for q in pts[i:]):
            n = (p.date - as_of).days
            break
    if n is None or n > _MAX_WAIT_DAYS:
        return [RecoveryOption(
            action="wait_before_purchases", label="Hold off on discretionary spending",
            amount=None, monthly_amount=None, weekly_amount=None, duration_days=None,
            projected_min_without_recovery=money(min_after_spend),
            projected_min_with_recovery=money(min_after_spend),
            buffer_restored=False, risk_after=_risk(money(min_after_spend), buffer),
            goal_delay_months=None, feasible=False,
            reason="time and known income alone don't bring the buffer back within 45 days",
        )]
    tail_min = money(min(q.balance for q in pts if (q.date - as_of).days >= n))
    return [RecoveryOption(
        action="wait_before_purchases",
        label=f"Avoid discretionary spending for {n} day{'s' if n != 1 else ''}",
        amount=None, monthly_amount=None, weekly_amount=None, duration_days=n,
        projected_min_without_recovery=money(min_after_spend),
        projected_min_with_recovery=tail_min,
        buffer_restored=True, risk_after=_risk(tail_min, buffer),
        goal_delay_months=0, feasible=True,
        reason="known income and time restore the buffer if you pause discretionary spending",
    )]


def _add_months(anchor: date, n: int) -> date:
    from finance.recurrence import add_months
    return add_months(anchor, n)
