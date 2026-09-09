"""Deterministic alternatives to a purchase decision.

Every alternative is scored by the SAME consequence engine (which uses the same
projection kernel). No LLM decides whether ₹3,000 is affordable — the engine does.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional

from decision.consequence_engine import (
    DECISION_BUY,
    evaluate_consequence,
)


@dataclass(frozen=True)
class Alternative:
    kind: str                       # "buy_now" | "wait" | "spend_less"
    label: str
    amount: Optional[Decimal]
    wait_days: Optional[int]
    decision: str
    minimum_balance_after: Decimal
    safe: bool                       # min stays at/above the safety buffer
    goal_delay_months: Optional[int] = None   # goal delay this alternative causes

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "amount": str(self.amount) if self.amount is not None else None,
            "wait_days": self.wait_days,
            "decision": self.decision,
            "minimum_balance_after": str(self.minimum_balance_after),
            "safe": self.safe,
            "goal_delay_months": self.goal_delay_months,
        }


def _goal_delay(result) -> Optional[int]:
    gi = getattr(result, "goal_impact", None)
    return gi.delay_months if (gi is not None and gi.available) else None


def build_alternatives(twin, *, base, amount, category=None, description=None,
                       goals=None, goal_id=None) -> List[Alternative]:
    """``base`` is the :class:`ConsequenceResult` for buying the full amount now.

    ``goals`` is forwarded to every re-score so each alternative reports its own
    deterministic goal delay.
    """
    alts: List[Alternative] = [
        Alternative(
            kind="buy_now",
            label="Buy now",
            amount=base.amount,
            wait_days=0,
            decision=base.decision,
            minimum_balance_after=base.minimum_balance_after,
            safe=(not base.buffer_breached_after) and base.safe_to_spend,
            goal_delay_months=_goal_delay(base),
        )
    ]

    if base.recommended_wait_days is not None:
        waited = evaluate_consequence(
            twin, amount=amount, category=category, description=description,
            purchase_date=base.purchase_date + timedelta(days=base.recommended_wait_days),
            goals=goals, goal_id=goal_id,
        )
        alts.append(Alternative(
            kind="wait",
            label=f"Wait {base.recommended_wait_days} day{'s' if base.recommended_wait_days != 1 else ''}",
            amount=base.amount,
            wait_days=base.recommended_wait_days,
            decision=waited.decision,
            minimum_balance_after=waited.minimum_balance_after,
            safe=not waited.buffer_breached_after,
            goal_delay_months=_goal_delay(waited),
        ))

    if base.largest_safe_amount is not None and base.largest_safe_amount < base.amount:
        smaller = evaluate_consequence(
            twin, amount=base.largest_safe_amount, category=category, description=description,
            purchase_date=base.purchase_date, goals=goals, goal_id=goal_id,
        )
        alts.append(Alternative(
            kind="spend_less",
            label=f"Spend {base.largest_safe_amount} instead",
            amount=base.largest_safe_amount,
            wait_days=None,
            decision=smaller.decision,
            minimum_balance_after=smaller.minimum_balance_after,
            safe=not smaller.buffer_breached_after,
            goal_delay_months=_goal_delay(smaller),
        ))

    return alts
