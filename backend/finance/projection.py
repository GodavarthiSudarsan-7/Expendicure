"""The single deterministic cash-flow projection kernel.

Everything that needs a forward view of the balance — affordability (Phase 4),
what-if simulation (Phase 5), forecasting (Phase 6) — goes through
``project_daily_balances``. There is exactly one implementation of "roll the
balance forward day by day"; callers only differ in which ``extra_events`` they
inject.

No Flask, no DB, no LLM. Pure ``Decimal`` arithmetic.

------------------------------------------------------------------------------
Definitions (authoritative)
------------------------------------------------------------------------------
starting balance
    ``twin.current_balance`` — the balance as of ``twin.as_of``, which already
    reflects every transaction dated on or before ``as_of``. The projection
    begins on ``as_of`` from this value. It is exposed as
    ``Projection.start_balance``.

horizon boundaries
    The projection produces one ``BalancePoint`` per calendar day from
    ``as_of`` through ``as_of + horizon_days`` **inclusive** — i.e.
    ``horizon_days + 1`` points, the first dated ``as_of``. If an injected
    event is dated later than ``as_of + horizon_days``, the horizon is
    automatically extended so that day is the last point (a purchase is always
    modelled). Events dated before ``as_of`` are dropped.

recurring events
    For each active recurring item on the twin, the kernel applies **one**
    occurrence, on its ``next_date``, if ``as_of <= next_date <= horizon_end``.
    Amount is ``+amount`` for a credit, ``-amount`` for a debit
    (``RecurringTransaction.signed_amount``). Repeating occurrences within the
    horizon are deliberately NOT expanded here — multi-occurrence expansion is
    Phase 6 forecasting.

purchase / extra events
    Callers pass ``extra_events`` (an iterable of ``ProjectionEvent``). Each has
    a ``date``, a **signed** ``amount`` (negative = outflow), a ``kind`` and a
    ``label``. Phase 4 affordability injects exactly one: the purchase, as a
    negative-amount event of kind ``"purchase"``.

event ordering on the same date
    A day's end-of-day balance is ``previous end-of-day balance + sum of that
    day's event amounts``. Because that sum is order-independent, the order of
    events within a day never affects any balance or the projected minimum. A
    stable order (by ``date``, then ``kind`` rank recurring < purchase <
    other, then ``label``, then ``amount``) is applied only so the returned
    ``events`` tuple is reproducible.

projected minimum balance / date
    ``Projection.min_balance`` is the smallest end-of-day balance across all
    points. ``Projection.min_date`` is the **earliest** day achieving it.
    Because ``points[0]`` already includes any events dated ``as_of``, a dip on
    day zero is captured.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Tuple

from finance.money import ZERO, money

# Same-date ordering rank (does not affect balances; see module docstring).
_KIND_RANK = {"recurring": 0, "purchase": 1}
_DEFAULT_RANK = 2


@dataclass(frozen=True)
class ProjectionEvent:
    date: date
    amount: Decimal  # signed: negative = outflow, positive = inflow
    kind: str = "adjustment"
    label: str = ""


@dataclass(frozen=True)
class BalancePoint:
    date: date
    balance: Decimal  # end-of-day balance, quantized to 2 places


@dataclass(frozen=True)
class Projection:
    as_of: date
    horizon_days: int          # the *effective* horizon (may exceed the request)
    start_balance: Decimal
    points: Tuple[BalancePoint, ...]
    events: Tuple[ProjectionEvent, ...]

    @property
    def end_balance(self) -> Decimal:
        return self.points[-1].balance

    @property
    def min_balance(self) -> Decimal:
        return min(p.balance for p in self.points)

    @property
    def min_date(self) -> date:
        target = self.min_balance
        for p in self.points:
            if p.balance == target:
                return p.date
        return self.points[-1].date  # unreachable


def recurring_events(twin, *, horizon_end: date) -> List[ProjectionEvent]:
    """One ``ProjectionEvent`` per active recurring item whose next occurrence
    falls in ``[twin.as_of, horizon_end]``."""
    out: List[ProjectionEvent] = []
    for rec in twin.recurring:
        if twin.as_of <= rec.next_date <= horizon_end:
            out.append(
                ProjectionEvent(
                    date=rec.next_date,
                    amount=rec.signed_amount,
                    kind="recurring",
                    label=rec.label,
                )
            )
    return out


def _sort_key(event: ProjectionEvent):
    return (
        event.date,
        _KIND_RANK.get(event.kind, _DEFAULT_RANK),
        event.label or "",
        event.amount,
    )


def project_daily_balances(
    twin,
    *,
    horizon_days: int,
    extra_events: Iterable[ProjectionEvent] = (),
) -> Projection:
    """Roll ``twin.current_balance`` forward. See the module docstring for the
    exact rules."""
    as_of = twin.as_of
    horizon_days = max(int(horizon_days), 0)
    nominal_end = as_of + timedelta(days=horizon_days)

    injected = [e for e in extra_events if e.date >= as_of]
    horizon_end = nominal_end
    for e in injected:
        if e.date > horizon_end:
            horizon_end = e.date

    events = recurring_events(twin, horizon_end=horizon_end) + injected
    events.sort(key=_sort_key)

    delta_by_date: Dict[date, Decimal] = {}
    for e in events:
        delta_by_date[e.date] = delta_by_date.get(e.date, ZERO) + e.amount

    start_balance = money(twin.current_balance)
    points: List[BalancePoint] = []
    running = start_balance
    day = as_of
    total_days = (horizon_end - as_of).days
    for _ in range(total_days + 1):
        running = money(running + delta_by_date.get(day, ZERO))
        points.append(BalancePoint(date=day, balance=running))
        day = day + timedelta(days=1)

    return Projection(
        as_of=as_of,
        horizon_days=total_days,
        start_balance=start_balance,
        points=tuple(points),
        events=tuple(events),
    )
