"""Flexible-spending intelligence.

When a purchase is unsafe, look for the SMALLEST set of changes to the user's
own FLEXIBLE recurring commitments that makes it safe — and prove it by
re-simulating.

Hard rules (all enforced here, all tested):
  * Only commitments the user marked ``flexibility='flexible'`` are touched.
    Essential / fixed commitments are never proposed for change.
  * Only outflows. An income stream can never be "cut" to create headroom.
  * Nothing is invented: every candidate comes from ``twin.recurring``.
  * At most :data:`MAX_CHANGES` changes are ever recommended.
  * If the user set ``allows_flexible_cuts = False``, nothing is proposed at
    all, however safe it would be.
  * A returned set is only returned if it actually makes the plan pass S1.
    No "try this and hope" suggestions.

Pure: ``Decimal`` + stdlib + ``finance`` + ``decision.safety``. No Flask, DB,
repository, network or LLM.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from finance.money import ZERO, money

from decision.safety import (
    ACTION_REDUCE,
    ACTION_STOP,
    Baseline,
    PlanPayment,
    SpendingChange,
    is_safe,
)

#: The spec's cap: never ask the user to change more than three things.
MAX_CHANGES = 3

#: A "reduce" first tries halving the commitment before proposing a full stop,
#: so the gentlest change that works is preferred.
REDUCTION_FRACTION = Decimal("0.5")


def flexible_candidates(twin) -> Tuple:
    """The user's flexible OUTFLOW commitments, in deterministic order.

    Ordered by largest monthly amount first (biggest lever), then label then id
    so the result never depends on dict/row ordering.
    """
    cands = [r for r in twin.recurring if getattr(r, "is_flexible", False) and r.active]
    return tuple(sorted(cands, key=lambda r: (-r.amount, r.label, r.id)))


def _reduce_change(rec) -> SpendingChange:
    target = money(rec.amount * REDUCTION_FRACTION)
    return SpendingChange(
        recurring_id=rec.id, label=rec.label, action=ACTION_REDUCE,
        from_amount=money(rec.amount), to_amount=target,
    )


def _stop_change(rec) -> SpendingChange:
    return SpendingChange(
        recurring_id=rec.id, label=rec.label, action=ACTION_STOP,
        from_amount=money(rec.amount), to_amount=ZERO,
    )


def find_adjustments(
    baseline: Baseline,
    twin,
    *,
    payments: Sequence[PlanPayment],
    max_changes: int = MAX_CHANGES,
) -> Tuple[SpendingChange, ...]:
    """The smallest proven-sufficient set of flexible changes, or ``()``.

    Algorithm (greedy, deterministic, and verified at every step):

      0. If the user does not allow flexible cuts, return ``()`` immediately.
      1. If the plan is already safe with no changes, return ``()`` — never
         propose a change that is not needed.
      2. Walk the candidates in the fixed order from
         :func:`flexible_candidates`. For each one, try the gentlest change
         first (halve it); if the plan is now safe, stop and return.
         Otherwise try stopping it; if that makes the plan safe, stop and
         return. If neither is enough on its own, keep the STOP (the larger
         lever) and move to the next candidate.
      3. Give up after ``max_changes`` candidates.
      4. Return the accumulated set ONLY if it actually passes S1; otherwise
         return ``()``.

    Greedy rather than exhaustive: with the cap at three changes an exhaustive
    search is affordable, but greedy-largest-first is deterministic, always
    returns a *sufficient* set when one exists along this path, and keeps the
    projection count low. See "remaining limitations" — it is not guaranteed to
    be the globally minimal-pain set.
    """
    if not getattr(twin, "allows_flexible_cuts", True):
        return ()
    if is_safe(baseline, payments=payments):
        return ()

    selected: List[SpendingChange] = []
    for rec in flexible_candidates(twin)[: max(0, int(max_changes))]:
        trial_reduce = selected + [_reduce_change(rec)]
        if is_safe(baseline, payments=payments, changes=trial_reduce):
            return tuple(trial_reduce)
        trial_stop = selected + [_stop_change(rec)]
        if is_safe(baseline, payments=payments, changes=trial_stop):
            return tuple(trial_stop)
        selected = trial_stop          # keep the bigger lever, keep looking

    if selected and is_safe(baseline, payments=payments, changes=selected):
        return tuple(selected)
    return ()


def total_monthly_saving(changes: Sequence[SpendingChange]) -> Decimal:
    return money(sum((c.monthly_saving for c in changes), ZERO))
