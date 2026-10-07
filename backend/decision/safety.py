"""The 90-day Financial Safety Engine.

Answers ONE question, deterministically:

    "If the user makes these payments (optionally after these flexible-spending
     changes), does their balance stay at or above their minimum balance on
     every single day of the forecast horizon?"

------------------------------------------------------------------------------
Why this module exists, and what it deliberately does NOT do
------------------------------------------------------------------------------
"Current balance" is not "safe to spend". A user with Rs.80,000 today whose
rent, EMI and school fee land over the next 90 days may only be able to safely
part with Rs.12,000. The only way to know is to roll the balance forward over
every known future money movement and look at the WORST day.

There is exactly one projection algorithm in Expendicure
(``finance.projection.project_daily_balances``) and exactly one place that
decides WHICH future events exist (``finance.forecast.forecast``). This module
creates neither. It:

  1. asks ``finance.forecast.forecast`` for the baseline event stream over the
     horizon — which already expands EVERY occurrence of every user recurring
     item and every conservatively-detected recurring pattern via
     ``finance.recurrence.occurrences_for_recurring`` (so rent over 90 days is
     three charges, not one);
  2. optionally rewrites that stream to model flexible-spending changes;
  3. appends the proposed payments as outflows;
  4. pushes the whole stream through the SAME kernel on a twin copy with
     ``recurring=()`` — exactly the technique ``forecast()`` itself uses to
     avoid double-counting the kernel's single-occurrence handling.

Pure: ``Decimal`` + stdlib + ``finance``. No Flask, no DB, no repository, no
requests, no LLM, no Ollama. Nothing here mutates its inputs.

------------------------------------------------------------------------------
The safety invariant (authoritative)
------------------------------------------------------------------------------
A plan is SAFE if and only if ALL of:

  S1  minimum over the horizon of the projected end-of-day balance
          >= minimum_balance_required
      (``minimum_balance_required`` is ``twin.safety_buffer`` — the user's
       stated minimum balance to keep)
  S2  every payment in the plan falls inside the horizon
  S3  the payments sum EXACTLY to the requested amount (the purchase is
      actually completed, not partially abandoned)
  S4  the final payment lands on or before the user's completion deadline
      (when one is given)

S1 is what makes essential spending and confirmed obligations "remain
covered": they are all in the baseline event stream, so any plan that would
starve them drives the projected minimum below the floor and fails S1.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from finance.forecast import MAX_HORIZON_DAYS, forecast
from finance.models import CREDIT, DEBIT
from finance.money import ZERO, money
from finance.projection import ProjectionEvent, project_daily_balances

#: The spec's forecast window for a spending decision.
SAFETY_HORIZON_DAYS = 90

#: Failure reason codes (stable, machine-readable).
FAIL_MIN_BALANCE = "minimum_balance_violated"
FAIL_PAYMENT_OUTSIDE_HORIZON = "payment_outside_horizon"
FAIL_AMOUNT_INCOMPLETE = "requested_amount_not_completed"
FAIL_DEADLINE_MISSED = "completion_deadline_missed"

ACTION_STOP = "stop"
ACTION_REDUCE = "reduce"


# --------------------------------------------------------------------- inputs

@dataclass(frozen=True)
class PlanPayment:
    """One outflow in a candidate plan. ``amount`` is a positive magnitude."""
    date: date
    amount: Decimal
    label: str = "purchase payment"

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "amount": str(money(self.amount)),
                "label": self.label}


@dataclass(frozen=True)
class SpendingChange:
    """A proposed change to ONE flexible recurring commitment.

    ``recurring_id`` / ``label`` identify the commitment; the engine matches
    baseline events by ``label`` because that is what ``forecast()`` stamps on
    each generated occurrence.
    """
    recurring_id: Optional[int]
    label: str
    action: str                 # "stop" | "reduce"
    from_amount: Decimal
    to_amount: Decimal          # ZERO for a stop

    @property
    def monthly_saving(self) -> Decimal:
        return money(self.from_amount - self.to_amount)

    def to_dict(self) -> dict:
        return {
            "recurring_id": self.recurring_id,
            "label": self.label,
            "action": self.action,
            "from_amount": str(money(self.from_amount)),
            "to_amount": str(money(self.to_amount)),
            "monthly_saving": str(self.monthly_saving),
        }


# -------------------------------------------------------------------- results

@dataclass(frozen=True)
class SafetyCheck:
    """The verdict of one 90-day simulation."""
    passed: bool
    horizon_days: int
    as_of: date
    minimum_balance_required: Decimal
    minimum_projected_balance: Decimal
    minimum_projected_balance_date: date
    end_balance: Decimal
    failure_reasons: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "horizon_days": self.horizon_days,
            "as_of": self.as_of.isoformat(),
            "minimum_balance_required": str(self.minimum_balance_required),
            "minimum_projected_balance": str(self.minimum_projected_balance),
            "minimum_projected_balance_date": self.minimum_projected_balance_date.isoformat(),
            "end_balance": str(self.end_balance),
            "failure_reasons": list(self.failure_reasons),
        }


@dataclass(frozen=True)
class Baseline:
    """The horizon's event stream, computed ONCE and reused by every candidate
    plan evaluated for the same request. This is the memoisation point that
    keeps plan search cheap (see module note on performance)."""
    as_of: date
    horizon_days: int
    horizon_end: date
    minimum_balance_required: Decimal
    events: Tuple[ProjectionEvent, ...]
    flat_twin: object = field(repr=False)
    #: the untouched baseline safety picture, with no purchase applied
    check: SafetyCheck = None  # type: ignore[assignment]


# ------------------------------------------------------------ A. simulation

def build_baseline(
    twin,
    history=None,
    *,
    horizon_days: int = SAFETY_HORIZON_DAYS,
    minimum_balance: Optional[Decimal] = None,
) -> Baseline:
    """Expand the horizon's full event stream by REUSING ``finance.forecast``.

    ``forecast()`` is the single owner of "which future events exist": user
    recurring items expanded to every occurrence in the horizon, plus
    conservatively-detected recurring patterns from ``history``. We take its
    events verbatim and convert them to kernel ``ProjectionEvent``s.
    """
    horizon_days = max(1, min(int(horizon_days), MAX_HORIZON_DAYS))
    fc = forecast(twin, history, horizon_days=horizon_days)

    events = tuple(
        ProjectionEvent(
            date=e.date,
            amount=e.amount if e.direction == CREDIT else -e.amount,
            kind=e.source,
            label=e.label,
        )
        for e in fc.events
    )
    floor = money(minimum_balance if minimum_balance is not None else twin.safety_buffer)
    # recurring=() because every occurrence is already an explicit event — the
    # same guard forecast() applies, so nothing is counted twice.
    flat_twin = dataclasses.replace(twin, recurring=())

    base = Baseline(
        as_of=twin.as_of,
        horizon_days=horizon_days,
        horizon_end=twin.as_of + timedelta(days=horizon_days),
        minimum_balance_required=floor,
        events=events,
        flat_twin=flat_twin,
    )
    return dataclasses.replace(base, check=evaluate_plan(base, payments=()))


def _apply_changes(
    events: Sequence[ProjectionEvent],
    changes: Iterable[SpendingChange],
) -> List[ProjectionEvent]:
    """Rewrite the baseline stream to model flexible-spending changes.

    A ``stop`` drops every outflow occurrence of that commitment; a ``reduce``
    rescales each to the new amount. Inflows are never touched, and a label
    that matches nothing changes nothing — so an invented commitment cannot
    manufacture headroom.
    """
    by_label = {c.label: c for c in changes}
    if not by_label:
        return list(events)

    out: List[ProjectionEvent] = []
    for e in events:
        change = by_label.get(e.label)
        if change is None or e.amount >= ZERO:   # untouched, or an inflow
            out.append(e)
            continue
        if change.action == ACTION_STOP:
            continue                              # occurrence removed entirely
        out.append(dataclasses.replace(e, amount=-money(change.to_amount)))
    return out


def simulate(
    baseline: Baseline,
    *,
    payments: Sequence[PlanPayment] = (),
    changes: Sequence[SpendingChange] = (),
):
    """Project the baseline + changes + payments through the ONE kernel."""
    events = _apply_changes(baseline.events, changes)
    events.extend(
        ProjectionEvent(date=p.date, amount=-money(p.amount), kind="purchase", label=p.label)
        for p in payments
    )
    return project_daily_balances(
        baseline.flat_twin, horizon_days=baseline.horizon_days, extra_events=events
    )


def evaluate_plan(
    baseline: Baseline,
    *,
    payments: Sequence[PlanPayment] = (),
    changes: Sequence[SpendingChange] = (),
    requested_amount: Optional[Decimal] = None,
    deadline: Optional[date] = None,
) -> SafetyCheck:
    """Run the full safety invariant (S1-S4) over one candidate plan."""
    proj = simulate(baseline, payments=payments, changes=changes)
    reasons: List[str] = []

    min_bal = money(proj.min_balance)
    if min_bal < baseline.minimum_balance_required:
        reasons.append(FAIL_MIN_BALANCE)

    for p in payments:
        if not (baseline.as_of <= p.date <= baseline.horizon_end):
            reasons.append(FAIL_PAYMENT_OUTSIDE_HORIZON)
            break

    if requested_amount is not None:
        total = money(sum((money(p.amount) for p in payments), ZERO))
        if total != money(requested_amount):
            reasons.append(FAIL_AMOUNT_INCOMPLETE)

    if deadline is not None and payments:
        if max(p.date for p in payments) > deadline:
            reasons.append(FAIL_DEADLINE_MISSED)

    return SafetyCheck(
        passed=not reasons,
        horizon_days=proj.horizon_days,
        as_of=baseline.as_of,
        minimum_balance_required=baseline.minimum_balance_required,
        minimum_projected_balance=min_bal,
        minimum_projected_balance_date=proj.min_date,
        end_balance=money(proj.end_balance),
        failure_reasons=tuple(dict.fromkeys(reasons)),
    )


def is_safe(
    baseline: Baseline,
    *,
    payments: Sequence[PlanPayment] = (),
    changes: Sequence[SpendingChange] = (),
) -> bool:
    """S1 only — "does the floor hold?". Used by the search routines below,
    which construct their own payments and so cannot violate S2-S4."""
    return money(simulate(baseline, payments=payments, changes=changes).min_balance) \
        >= baseline.minimum_balance_required


# ----------------------------------------------------- B. amount_safe_to_pay

def amount_safe_to_pay(
    baseline: Baseline,
    *,
    requested: Decimal,
    on_date: Optional[date] = None,
    changes: Sequence[SpendingChange] = (),
) -> Decimal:
    """The largest amount payable on ``on_date`` that still satisfies S1.

    Exact to the rupee by binary search on the safety predicate, which is
    monotonic: if paying X keeps the floor, so does paying anything < X (every
    smaller outflow leaves every daily balance >= the X case). That
    monotonicity is what makes bisection correct here.

    Invariant: ``0 <= amount_safe_to_pay <= requested``.

    Rupee granularity (not paise) is deliberate: it keeps the figure
    presentable, bounds the search to ~17 projections for a Rs.1,00,000
    request, and errs downward — never recommending more than is safe.
    """
    requested = money(requested)
    if requested <= ZERO:
        return ZERO
    pay_on = on_date or baseline.as_of

    def safe(amount: Decimal) -> bool:
        if amount <= ZERO:
            return True
        return is_safe(
            baseline,
            payments=[PlanPayment(date=pay_on, amount=amount)],
            changes=changes,
        )

    if safe(requested):
        return requested
    if not safe(money(1)):
        return ZERO

    lo, hi = 1, int(requested)          # lo is known safe, hi known unsafe
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if safe(money(mid)):
            lo = mid
        else:
            hi = mid
    return money(lo)


# --------------------------------------------- C. earliest safe full payment

def next_inflow(baseline: Baseline, *, after: Optional[date] = None):
    """The next confirmed money-IN event in the horizon, as ``(date, amount)``,
    or ``None``. A lookup over the baseline stream — no arithmetic.

    Used only to explain *why* a purchase becomes affordable later ("after your
    salary on the 25th"); it never participates in the safety decision.
    """
    floor_date = after or baseline.as_of
    best = None
    for e in baseline.events:
        if e.amount > ZERO and e.date >= floor_date:
            if best is None or e.date < best.date:
                best = e
    return (best.date, money(best.amount)) if best is not None else None


def earliest_safe_date_for(
    baseline: Baseline,
    *,
    amount: Decimal,
    from_date: Optional[date] = None,
    also_pay: Sequence[PlanPayment] = (),
    changes: Sequence[SpendingChange] = (),
) -> Optional[date]:
    """The earliest day in ``[from_date, horizon_end]`` on which paying
    ``amount`` as ONE payment — on top of ``also_pay``, which is already
    committed — satisfies S1. ``None`` if it never becomes safe.

    Scanned forward day by day rather than bisected: safety is NOT monotonic in
    the date (income raises the floor, a large outflow lowers it), so the first
    safe day must be found by inspection.

    ``also_pay`` is what lets a partial plan ask "given I pay X today, when can
    I safely pay the rest?".
    """
    amount = money(amount)
    if amount <= ZERO:
        return None
    start = from_date or baseline.as_of
    if start < baseline.as_of:
        start = baseline.as_of

    day = start
    while day <= baseline.horizon_end:
        if is_safe(
            baseline,
            payments=list(also_pay) + [PlanPayment(date=day, amount=amount)],
            changes=changes,
        ):
            return day
        day += timedelta(days=1)
    return None


def earliest_date_for_full_payment(
    baseline: Baseline,
    *,
    requested: Decimal,
    from_date: Optional[date] = None,
    changes: Sequence[SpendingChange] = (),
) -> Optional[date]:
    """The earliest day on which paying ``requested`` in ONE payment is safe.

    Deliberately independent of the user's preferred payment method, exactly as
    specified: it answers "when does the full amount become affordable?" even
    for a user who would never use installments.
    """
    return earliest_safe_date_for(
        baseline, amount=requested, from_date=from_date, changes=changes
    )
