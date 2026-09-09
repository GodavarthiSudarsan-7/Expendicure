"""Deterministic affordability engine — "Can I afford this?".

Given a :class:`finance.twin.TwinState` and a prospective purchase, returns a
structured, machine-readable verdict. Pure ``Decimal`` arithmetic; no Flask, no
DB, **no LLM**.

============================================================================
Agent integration (future Phase 9) — DO NOT add an LLM to this module.
============================================================================
This module is a deterministic TOOL. The planned architecture:

    User
      -> Financial Orchestrator Agent            (local LLM via Ollama, Phase 9)
        -> Financial Tools                       (hand-written registry, Phase 9)
             check_affordability  ------------------.
        -> Deterministic Finance Engine            |  this module
             finance.affordability.check_affordability(twin, **args)
             finance.projection.project_daily_balances(...)   (shared kernel)
             finance.twin.build_twin_state(...)               (source of truth)
        -> Guardrails                             (Phase 11)
        -> Agent explanation

The Phase 9 tool wrapper (``ai/tools.py``) will:
  1. Receive ``{"amount", "category"?, "date"?, "horizon_days"?}`` from the model.
  2. Build the twin deterministically:
       ``build_twin_state(get_repository(), student_id,
                          default_safety_buffer=Config.SAFETY_BUFFER)``
  3. Call ``check_affordability(twin, **args)``.
  4. Return ``result.to_dict()`` VERBATIM to the agent / guardrails.

The agent MUST NOT compute, round, override, or invent any figure in the
result. ``TOOL_SPEC`` below is the machine-readable descriptor for the
hand-written registry — no LangChain / LlamaIndex / MCP.

----------------------------------------------------------------------------
Verdict (from the projection, WITH the purchase applied)
----------------------------------------------------------------------------
Let ``min_bal`` = projected minimum end-of-day balance over the horizon and
``buffer`` = ``twin.safety_buffer``.

    min_bal <  buffer                                   -> "not_affordable"
    min_bal >= buffer and (min_bal - buffer) < 0.10*amount -> "tight"
    otherwise                                           -> "affordable"

A category-budget breach is reported in ``breaches`` and ``reasons`` but does
NOT by itself change the verdict.

----------------------------------------------------------------------------
Score (exact, deterministic, documented)
----------------------------------------------------------------------------
    score = clamp(
        round_half_up(
            50 + 50 * (projected_min_balance - safety_buffer) / max(amount, 1)
        ),
        0, 100
    )

- ``round_half_up`` matches ``finance.money`` (ROUND_HALF_UP).
- Monotonic in ``projected_min_balance`` (increasing) and in ``-safety_buffer``;
  more precisely, monotonic in the normalised safety margin
  ``(projected_min_balance - safety_buffer) / max(amount, 1)``.
- No category-budget penalty. No example-fitting. e.g. amount=4000,
  projected_min_balance=0, safety_buffer=2000  ->  score = 25.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple

from finance.money import ZERO, money
from finance.projection import ProjectionEvent, project_daily_balances

DEFAULT_HORIZON_DAYS = 30

VERDICT_AFFORDABLE = "affordable"
VERDICT_TIGHT = "tight"
VERDICT_NOT_AFFORDABLE = "not_affordable"

# "tight" band: the projected minimum clears the safety buffer, but by less
# than this fraction of the purchase amount.
TIGHT_MARGIN_FRACTION = Decimal("0.10")

TOOL_SPEC = {
    "name": "check_affordability",
    "description": (
        "Deterministically assess whether the student can afford a prospective "
        "purchase, given their Financial Digital Twin. Returns a structured "
        "verdict, a 0-100 safety score, the projected minimum balance over the "
        "horizon, and human-readable reasons. The caller must not alter any "
        "returned number."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "amount": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Purchase amount in the account currency.",
            },
            "category": {
                "type": ["string", "null"],
                "description": "Optional spending category name.",
            },
            "date": {
                "type": ["string", "null"],
                "description": "Optional purchase date YYYY-MM-DD; defaults to the twin's as_of.",
            },
            "horizon_days": {
                "type": "integer",
                "minimum": 0,
                "maximum": 365,
                "default": DEFAULT_HORIZON_DAYS,
                "description": "Look-ahead window for the balance projection.",
            },
        },
        "required": ["amount"],
    },
}


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str  # "info" | "low" | "medium" | "high"
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class AffordabilityResult:
    verdict: str
    score: int
    amount: Decimal
    category: Optional[str]
    as_of: date
    purchase_date: date
    horizon_days: int
    current_balance: Decimal
    baseline_min_balance: Decimal
    projected_min_balance: Decimal
    projected_min_date: date
    safety_buffer: Decimal
    committed_upcoming: Decimal
    discretionary_buffer_before: Decimal
    discretionary_buffer_after: Decimal
    breaches: Tuple[str, ...]
    reasons: Tuple[Reason, ...]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "amount": str(self.amount),
            "category": self.category,
            "as_of": self.as_of.isoformat(),
            "purchase_date": self.purchase_date.isoformat(),
            "horizon_days": self.horizon_days,
            "current_balance": str(self.current_balance),
            "baseline_min_balance": str(self.baseline_min_balance),
            "projected_min_balance": str(self.projected_min_balance),
            "projected_min_date": self.projected_min_date.isoformat(),
            "safety_buffer": str(self.safety_buffer),
            "committed_upcoming": str(self.committed_upcoming),
            "discretionary_buffer_before": str(self.discretionary_buffer_before),
            "discretionary_buffer_after": str(self.discretionary_buffer_after),
            "breaches": list(self.breaches),
            "reasons": [r.to_dict() for r in self.reasons],
        }


def _score(projected_min_balance: Decimal, safety_buffer: Decimal, amount: Decimal) -> int:
    denominator = amount if amount > Decimal(1) else Decimal(1)  # max(amount, 1)
    raw = Decimal(50) + Decimal(50) * (projected_min_balance - safety_buffer) / denominator
    rounded = int(raw.to_integral_value(rounding=ROUND_HALF_UP))
    return max(0, min(100, rounded))


def _find_ci(mapping, name: str):
    """Case-insensitive, whitespace-trimmed lookup in a ``{category_name: X}`` map."""
    if name in mapping:
        return mapping[name]
    target = name.strip().casefold()
    for key, value in mapping.items():
        if key.strip().casefold() == target:
            return value
    return None


def check_affordability(
    twin,
    *,
    amount,
    category: Optional[str] = None,
    purchase_date: Optional[date] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> AffordabilityResult:
    """Deterministically assess a prospective purchase against ``twin``.

    Raises ``ValueError`` for a non-positive amount or a purchase dated before
    the twin's ``as_of``.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise ValueError("amount must be greater than 0")

    purchase_date = purchase_date or twin.as_of
    if purchase_date < twin.as_of:
        raise ValueError("purchase_date must not be before the twin's as_of date")

    horizon_days = max(int(horizon_days), 0)
    # Always project at least far enough to include the purchase.
    effective_horizon_days = max(horizon_days, (purchase_date - twin.as_of).days)

    baseline = project_daily_balances(twin, horizon_days=effective_horizon_days)
    projected = project_daily_balances(
        twin,
        horizon_days=effective_horizon_days,
        extra_events=[
            ProjectionEvent(
                date=purchase_date,
                amount=-amount,
                kind="purchase",
                label=category or "purchase",
            )
        ],
    )

    buffer = twin.safety_buffer
    min_bal = projected.min_balance
    min_date = projected.min_date
    margin = min_bal - buffer

    if min_bal < buffer:
        verdict = VERDICT_NOT_AFFORDABLE
    elif margin < (TIGHT_MARGIN_FRACTION * amount):
        verdict = VERDICT_TIGHT
    else:
        verdict = VERDICT_AFFORDABLE

    score = _score(min_bal, buffer, amount)

    disc_before = twin.discretionary_buffer
    disc_after = money(disc_before - amount)

    breaches: List[str] = []
    reasons: List[Reason] = []

    if min_bal < ZERO:
        breaches.append("overdraft")
        reasons.append(
            Reason(
                "negative_balance",
                "high",
                f"Projected balance goes negative ({min_bal}) on {min_date.isoformat()}.",
            )
        )
    if min_bal < buffer:
        breaches.append("safety_buffer")
        reasons.append(
            Reason(
                "below_safety_buffer",
                "high",
                f"Projected balance falls to {min_bal} on {min_date.isoformat()}, "
                f"below your {buffer} safety buffer.",
            )
        )

    if baseline.min_balance < buffer:
        reasons.append(
            Reason(
                "pre_existing_shortfall",
                "medium",
                f"Even without this purchase, your balance was projected to fall to "
                f"{baseline.min_balance} within {effective_horizon_days} days.",
            )
        )

    if category:
        budget = _find_ci(twin.budgets, category)
        if budget is not None:
            spent = _find_ci(twin.spending_by_category, category) or ZERO
            remaining = money(budget - spent)
            if amount > remaining:
                breaches.append("category_budget")
                reasons.append(
                    Reason(
                        "category_over_budget",
                        "medium",
                        f"This purchase exceeds the remaining {category} budget "
                        f"({remaining} left of {budget} this month).",
                    )
                )

    if verdict == VERDICT_AFFORDABLE and not reasons:
        reasons.append(
            Reason(
                "within_safe_margin",
                "info",
                f"Projected minimum balance {min_bal} stays clear of your "
                f"{buffer} safety buffer over {effective_horizon_days} days.",
            )
        )
    elif verdict == VERDICT_TIGHT:
        reasons.insert(
            0,
            Reason(
                "thin_margin",
                "low",
                f"Projected minimum balance {min_bal} is only "
                f"{margin} above your {buffer} safety buffer.",
            ),
        )

    return AffordabilityResult(
        verdict=verdict,
        score=score,
        amount=amount,
        category=category,
        as_of=twin.as_of,
        purchase_date=purchase_date,
        horizon_days=effective_horizon_days,
        current_balance=money(twin.current_balance),
        baseline_min_balance=money(baseline.min_balance),
        projected_min_balance=money(min_bal),
        projected_min_date=min_date,
        safety_buffer=money(buffer),
        committed_upcoming=money(twin.committed_upcoming),
        discretionary_buffer_before=money(disc_before),
        discretionary_buffer_after=disc_after,
        breaches=tuple(breaches),
        reasons=tuple(reasons),
    )
