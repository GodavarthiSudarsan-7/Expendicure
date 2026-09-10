"""Deterministic cash-flow forecast — "what will my money look like?".

Projects the student's **expected** balance over the next N days from their
current balance plus *known* recurring money movements. Pure ``Decimal``
arithmetic; no Flask, no DB, **no LLM, no ML** (no pandas / sklearn / Prophet /
numpy).

============================================================================
1. Forecast definition
============================================================================
The forecast rolls ``twin.current_balance`` forward day-by-day, applying every
future occurrence (within the horizon) of:
  * the student's active recurring transactions (``twin.recurring``), and
  * recurring patterns conservatively *detected* from transaction history
    (only where the evidence is strong enough — see section 3).
It assumes **nothing changes**: no new spending decisions, no hypotheticals.

============================================================================
2. Digital Twin vs What-If vs Forecast
============================================================================
  CURRENT REALITY     -> Financial Digital Twin (finance.twin)
        "what IS, as of now"
  HYPOTHETICAL FUTURE -> What-If Simulator (finance.simulate)
        "what WOULD happen if I made this specific change"
  EXPECTED FUTURE     -> Cash-Flow Forecast (this module)
        "what is LIKELY to happen if nothing changes"

All three share the ONE balance kernel, ``finance.projection``. Forecasting
decides WHICH future events to project; the kernel decides HOW they move the
balance. This module never creates a second balance algorithm.

============================================================================
3. Recurring detection rules (deterministic, explainable)
============================================================================
From ``history`` (transactions in ``[as_of - DETECTION_LOOKBACK_DAYS, as_of]``):
  a. Group by key ``(normalised_merchant, direction)`` where
     normalised_merchant = lower-cased, non-alphanumerics stripped, first
     ``MERCHANT_KEY_LEN`` chars.
  b. Consider only groups with ``>= MIN_OBSERVATIONS`` transactions.
  c. Sort by date; compute consecutive day-gaps.
       monthly if median gap in MONTHLY_MEDIAN_RANGE and every gap in MONTHLY_GAP_RANGE
       weekly  if median gap in WEEKLY_MEDIAN_RANGE  and every gap in WEEKLY_GAP_RANGE
       otherwise -> not recurring (inconsistent cadence).
  d. Amount spread = (max - min) / median_amount.
       spread >  AMOUNT_TOLERANCE_LOOSE  -> not recurring (too erratic to forecast)
       else the projected amount is the median of the observed amounts.
  e. Next occurrence = the pattern continued from the last observed date
     (monthly: same day-of-month; weekly: +7 days), rolled forward by whole
     periods until it is ``>= as_of``.
  f. A detected group is dropped if an active user recurring already covers the
     same ``(normalised_merchant, direction)`` — the explicit record wins.

Sparse / weak history -> no detected recurring is invented; the forecast is a
flat line and overall confidence is ``low`` with an explanatory assumption note.

============================================================================
4. Confidence rules (deterministic, explainable)
============================================================================
Per recurring assumption:
  high   : an active user-created recurring transaction (explicit intent), OR a
           detected group with >= 6 obs, all gaps in the strict cadence range,
           and amount spread <= AMOUNT_TOLERANCE_STRICT.
  medium : a detected group with >= 4 obs, all gaps in the strict cadence range,
           and amount spread <= AMOUNT_TOLERANCE_MEDIUM.
  low    : a detected group with >= 3 obs, cadence consistent (loose range),
           and amount spread <= AMOUNT_TOLERANCE_LOOSE.
Groups that do not reach ``low`` are not forecast at all.

Overall forecast confidence = the LOWEST assumption confidence
(low < medium < high); ``low`` when there are no assumptions.

============================================================================
5. Projection rules
============================================================================
A copy of the twin with ``recurring = ()`` is passed to
``project_daily_balances`` together with EVERY forecast occurrence as an
explicit ``ProjectionEvent`` (credit = +amount, debit = -amount). This avoids
double-counting the kernel's own single-occurrence handling while keeping the
kernel the sole balance algorithm. Horizon boundaries, same-day summation and
minimum-balance rules are exactly as documented in ``finance.projection``.

============================================================================
6. Safety-buffer logic
============================================================================
``safety_buffer_breached`` = the projected end-of-day balance falls below
``twin.safety_buffer`` on any day in the horizon. ``breach_date`` = the
*earliest* such day. Purely arithmetic; never an LLM judgement.

============================================================================
7. Future agent tool integration (Phase 9)
============================================================================
Exposed as the tool ``forecast_cashflow`` (``TOOL_SPEC`` below). The Phase-9
wrapper builds the twin + history deterministically, calls
``forecast(twin, history, horizon_days=...)``, and returns ``result.to_dict()``
VERBATIM. The agent must never compute or alter a forecast number. No
LangChain / LlamaIndex / MCP.
"""

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from finance.models import CREDIT, DEBIT
from finance.money import ZERO, money
from finance.projection import BalancePoint, ProjectionEvent, project_daily_balances
from finance.recurrence import (
    MERCHANT_KEY_LEN,
    add_months,
    normalise_merchant,
    occurrences_for_recurring,
)

DEFAULT_HORIZON_DAYS = 30
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 365

DETECTION_LOOKBACK_DAYS = 180
MIN_OBSERVATIONS = 3

MONTHLY_MEDIAN_RANGE = (26, 35)
MONTHLY_GAP_RANGE = (24, 38)
WEEKLY_MEDIAN_RANGE = (6, 8)
WEEKLY_GAP_RANGE = (5, 10)

AMOUNT_TOLERANCE_STRICT = Decimal("0.15")
AMOUNT_TOLERANCE_MEDIUM = Decimal("0.25")
AMOUNT_TOLERANCE_LOOSE = Decimal("0.40")

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

TOOL_SPEC = {
    "name": "forecast_cashflow",
    "description": (
        "Deterministically project the user's expected balance over the next "
        "N days from their current balance plus known recurring money movements "
        "(active user-declared recurring transactions and conservatively detected "
        "recurring patterns from history). Returns the projected minimum and "
        "ending balance, projected income/expenses/net, a daily balance series, "
        "the recurring assumptions with confidence, and whether the safety buffer "
        "is breached. Read-only; the caller must not alter the result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "horizon_days": {
                "type": "integer", "minimum": MIN_HORIZON_DAYS, "maximum": MAX_HORIZON_DAYS,
                "default": DEFAULT_HORIZON_DAYS,
                "description": "Number of days to forecast.",
            },
            "as_of": {
                "type": ["string", "null"],
                "description": "YYYY-MM-DD; defaults to today / the twin's as_of.",
            },
        },
    },
}


# ---------------------------------------------------------------- result types

@dataclass(frozen=True)
class ForecastEvent:
    date: date
    direction: str            # "debit" | "credit"
    amount: Decimal
    label: str
    source: str               # "recurring" (user) | "detected"
    confidence: str            # "low" | "medium" | "high"

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "direction": self.direction,
            "amount": str(self.amount),
            "label": self.label,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RecurringAssumption:
    label: str
    direction: str
    amount: Decimal
    cadence: str
    next_date: date
    source: str                # "recurring" | "detected"
    confidence: str
    occurrences_in_horizon: int
    observations: Optional[int] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "direction": self.direction,
            "amount": str(self.amount),
            "cadence": self.cadence,
            "next_date": self.next_date.isoformat() if self.next_date else None,
            "source": self.source,
            "confidence": self.confidence,
            "occurrences_in_horizon": self.occurrences_in_horizon,
            "observations": self.observations,
            "note": self.note,
        }


@dataclass(frozen=True)
class ForecastResult:
    as_of: date
    horizon_days: int
    starting_balance: Decimal
    projected_min_balance: Decimal
    projected_min_balance_date: date
    projected_end_balance: Decimal
    projected_income: Decimal
    projected_expenses: Decimal
    projected_net: Decimal
    confidence: str
    events: Tuple[ForecastEvent, ...]
    assumptions: Tuple[RecurringAssumption, ...]
    safety_buffer: Decimal
    safety_buffer_breached: bool
    breach_date: Optional[date]
    projection: Tuple[BalancePoint, ...]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "horizon_days": self.horizon_days,
            "starting_balance": str(self.starting_balance),
            "projected_min_balance": str(self.projected_min_balance),
            "projected_min_balance_date": self.projected_min_balance_date.isoformat(),
            "projected_end_balance": str(self.projected_end_balance),
            "projected_income": str(self.projected_income),
            "projected_expenses": str(self.projected_expenses),
            "projected_net": str(self.projected_net),
            "confidence": self.confidence,
            "events": [e.to_dict() for e in self.events],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "safety_buffer": str(self.safety_buffer),
            "safety_buffer_breached": self.safety_buffer_breached,
            "breach_date": self.breach_date.isoformat() if self.breach_date else None,
            "projection": [
                {"date": p.date.isoformat(), "balance": str(p.balance)} for p in self.projection
            ],
        }


# ------------------------------------------------------------------- helpers

def _validate_horizon(horizon_days):
    if isinstance(horizon_days, bool) or isinstance(horizon_days, float):
        raise ValueError("horizon_days must be an integer")
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon_days must be an integer") from exc
    if not (MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS):
        raise ValueError(f"horizon_days must be between {MIN_HORIZON_DAYS} and {MAX_HORIZON_DAYS}")
    return horizon_days


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _in_range(value, lo_hi) -> bool:
    return lo_hi[0] <= value <= lo_hi[1]


# ---------------------------------------------------------- recurring detection

@dataclass(frozen=True)
class _Detected:
    key: Tuple[str, str]
    label: str
    direction: str
    amount: Decimal
    cadence: str
    next_date: date
    observations: int
    confidence: str


def detect_recurring(history, *, as_of: date) -> List[_Detected]:
    """Deterministically detect recurring patterns from ``history`` (a list of
    ``Transaction``). See module docstring section 3 for the exact rules."""
    lookback_start = as_of - timedelta(days=DETECTION_LOOKBACK_DAYS)
    groups: Dict[Tuple[str, str], list] = {}
    for txn in history:
        if txn.payment_date is None or not (lookback_start <= txn.payment_date <= as_of):
            continue
        key = (normalise_merchant(txn.merchant_name), txn.direction or DEBIT)
        if not key[0]:
            continue
        groups.setdefault(key, []).append(txn)

    detected: List[_Detected] = []
    for key, txns in groups.items():
        if len(txns) < MIN_OBSERVATIONS:
            continue
        txns = sorted(txns, key=lambda t: t.payment_date)
        gaps = [(txns[i].payment_date - txns[i - 1].payment_date).days for i in range(1, len(txns))]
        if not gaps:
            continue
        median_gap = _median(gaps)

        if _in_range(median_gap, MONTHLY_MEDIAN_RANGE) and all(_in_range(g, MONTHLY_GAP_RANGE) for g in gaps):
            cadence = "monthly"
        elif _in_range(median_gap, WEEKLY_MEDIAN_RANGE) and all(_in_range(g, WEEKLY_GAP_RANGE) for g in gaps):
            cadence = "weekly"
        else:
            continue  # inconsistent cadence

        amounts = [t.amount for t in txns]
        median_amount = money(_median(amounts))
        if median_amount <= ZERO:
            continue
        spread = (max(amounts) - min(amounts)) / median_amount
        if spread > AMOUNT_TOLERANCE_LOOSE:
            continue  # amounts too erratic to forecast

        strict_gaps = all(_in_range(g, MONTHLY_GAP_RANGE if cadence == "monthly" else WEEKLY_GAP_RANGE)
                          for g in gaps)
        n = len(txns)
        if n >= 6 and strict_gaps and spread <= AMOUNT_TOLERANCE_STRICT:
            confidence = "high"
        elif n >= 4 and strict_gaps and spread <= AMOUNT_TOLERANCE_MEDIUM:
            confidence = "medium"
        else:
            confidence = "low"

        last = txns[-1].payment_date
        if cadence == "monthly":
            nxt = add_months(last, 1)
            while nxt < as_of:
                nxt = add_months(nxt, 1)
        else:
            nxt = last + timedelta(days=7)
            while nxt < as_of:
                nxt = nxt + timedelta(days=7)

        detected.append(_Detected(
            key=key, label=(txns[-1].merchant_name or key[0]), direction=key[1],
            amount=median_amount, cadence=cadence, next_date=nxt,
            observations=n, confidence=confidence,
        ))

    detected.sort(key=lambda d: (d.next_date, d.label))
    return detected


# ------------------------------------------------------------------- forecast

class _RecView:
    """Adapter so ``occurrences_for_recurring`` can consume a detected pattern."""

    def __init__(self, next_date, cadence, day_of_month=None):
        self.next_date = next_date
        self.cadence = cadence
        self.day_of_month = day_of_month
        self.weekday = None


def _overall_confidence(assumptions) -> str:
    if not assumptions:
        return "low"
    return min((a.confidence for a in assumptions), key=lambda c: CONFIDENCE_ORDER[c])


def forecast(twin, history=None, *, horizon_days: int = DEFAULT_HORIZON_DAYS) -> ForecastResult:
    """Deterministic cash-flow forecast for ``twin`` over ``horizon_days``.

    ``history`` is an optional list of ``Transaction`` used only for recurring
    detection; pass ``None``/``[]`` to forecast from user recurring items alone.
    Raises ``ValueError`` for an invalid horizon.
    """
    horizon_days = _validate_horizon(horizon_days)
    history = list(history or [])

    as_of = twin.as_of
    horizon_end = as_of + timedelta(days=horizon_days)

    user_keys = set()
    events: List[ForecastEvent] = []
    assumptions: List[RecurringAssumption] = []

    # --- user recurring (explicit intent -> confidence "high") ---
    for rec in twin.recurring:
        if not rec.active:
            continue
        user_keys.add((normalise_merchant(rec.merchant_name), rec.direction or DEBIT))
        occ_dates = occurrences_for_recurring(rec, start=as_of, end=horizon_end)
        for d in occ_dates:
            events.append(ForecastEvent(
                date=d, direction=rec.direction or DEBIT, amount=money(rec.amount),
                label=rec.label, source="recurring", confidence="high",
            ))
        assumptions.append(RecurringAssumption(
            label=rec.label, direction=rec.direction or DEBIT, amount=money(rec.amount),
            cadence=rec.cadence, next_date=rec.next_date, source="recurring",
            confidence="high", occurrences_in_horizon=len(occ_dates), observations=None,
        ))

    # --- detected recurring from history ---
    for det in detect_recurring(history, as_of=as_of):
        if det.key in user_keys:
            continue  # explicit user record already covers it
        view = _RecView(det.next_date, det.cadence)
        occ_dates = occurrences_for_recurring(view, start=as_of, end=horizon_end)
        for d in occ_dates:
            events.append(ForecastEvent(
                date=d, direction=det.direction, amount=det.amount,
                label=det.label, source="detected", confidence=det.confidence,
            ))
        assumptions.append(RecurringAssumption(
            label=det.label, direction=det.direction, amount=det.amount,
            cadence=det.cadence, next_date=det.next_date, source="detected",
            confidence=det.confidence, occurrences_in_horizon=len(occ_dates),
            observations=det.observations,
            note=f"detected from {det.observations} historical transactions",
        ))

    if not assumptions:
        assumptions.append(RecurringAssumption(
            label="(none)", direction="", amount=ZERO, cadence="", next_date=None,
            source="none", confidence="low", occurrences_in_horizon=0, observations=len(history),
            note="insufficient recurring evidence; forecast is a flat projection of the current balance",
        ))

    # --- project through the ONE kernel ---
    events.sort(key=lambda e: (e.date, 0 if e.direction == CREDIT else 1, e.label))
    projection_events = [
        ProjectionEvent(
            date=e.date,
            amount=e.amount if e.direction == CREDIT else -e.amount,
            kind=e.source,
            label=e.label,
        )
        for e in events
    ]
    twin_flat = dataclasses.replace(twin, recurring=())
    proj = project_daily_balances(twin_flat, horizon_days=horizon_days, extra_events=projection_events)

    projected_income = money(sum((e.amount for e in events if e.direction == CREDIT), ZERO))
    projected_expenses = money(sum((e.amount for e in events if e.direction == DEBIT), ZERO))
    projected_net = money(projected_income - projected_expenses)

    buffer = money(twin.safety_buffer)
    breach_date = next((p.date for p in proj.points if p.balance < buffer), None)

    return ForecastResult(
        as_of=as_of,
        horizon_days=horizon_days,
        starting_balance=proj.start_balance,
        projected_min_balance=money(proj.min_balance),
        projected_min_balance_date=proj.min_date,
        projected_end_balance=money(proj.end_balance),
        projected_income=projected_income,
        projected_expenses=projected_expenses,
        projected_net=projected_net,
        confidence=_overall_confidence([a for a in assumptions if a.source != "none"]),
        events=tuple(events),
        assumptions=tuple(assumptions),
        safety_buffer=buffer,
        safety_buffer_breached=breach_date is not None,
        breach_date=breach_date,
        projection=proj.points,
    )
