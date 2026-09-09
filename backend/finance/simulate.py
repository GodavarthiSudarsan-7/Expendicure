"""Deterministic what-if financial simulator.

Answers "what happens to my balance if ...?" by projecting a BASELINE and a
SCENARIO through the *one* shared kernel (``finance.projection``) and comparing
them. Pure ``Decimal`` arithmetic; no Flask, no DB, **no LLM**.

============================================================================
1. What-if simulation — definition
============================================================================
A what-if simulation is a **temporary, in-memory** hypothetical. It takes the
student's current Financial Digital Twin, applies a scenario (extra events
and/or a modified copy of a recurring item), and reports:

  * BASELINE   : the twin projected forward with nothing added.
  * SCENARIO   : the same twin projected forward WITH the hypothetical applied.
  * COMPARISON : how the scenario moves the projected minimum balance, the
                 ending balance, the safety-buffer situation, and (for a
                 one-off purchase) the Phase-4 affordability verdict.

============================================================================
2. Supported scenario types
============================================================================
one_off_expense       {amount>0, date?=as_of, category?}
one_off_income        {amount>0, date?=as_of}
recurring_expense     {amount>0, cadence: weekly|monthly, start_date?=as_of,
                       day_of_month? (monthly), weekday? (weekly), end_date?, label?}
recurring_income      same shape as recurring_expense
recurring_modification{recurring_id (must exist on the twin), plus at least one of:
                       new_amount>0, remove:true, new_next_date}
income_delta          {monthly_amount>0, start_date?=as_of}   ("+X expected income")

Recurring / income_delta scenarios are expanded to one ``ProjectionEvent`` per
occurrence **within the nominal horizon**; a one-off event dated beyond the
nominal horizon extends the projection so it is always included (same rule as
Phase 4).

============================================================================
3. Baseline vs scenario calculation
============================================================================
starting balance   = twin.current_balance  (reflects every real transaction
                     dated <= as_of; see finance.projection docstring)
BASELINE   min_balance = min end-of-day balance of
             project_daily_balances(twin, horizon_days=H)
SCENARIO   min_balance = min end-of-day balance of
             project_daily_balances(scenario_twin, horizon_days=H,
                                    extra_events=scenario_events)
where ``scenario_twin`` == twin for every scenario except
``recurring_modification`` (which replaces the affected recurring item on a
*copy* of the twin), and ``H`` is the effective horizon (>= requested, extended
to cover any far-dated one-off event). Both sides use the SAME ``H`` so their
projections are point-for-point comparable.

comparison:
  min_balance_delta = scenario.min_balance - baseline.min_balance
  end_balance_delta = scenario.end_balance - baseline.end_balance
  safety_buffer_impact: "none" | "breached" | "restored" | "deepened" | "eased"
  affordability_before: Phase-4 check_affordability(...) for a one_off_expense,
                        else null. affordability_after: reserved (null for now).

============================================================================
4. Why a simulation never modifies real data
============================================================================
``simulate`` receives an already-built ``TwinState`` value object and returns a
value object. It holds NO repository, NO connection, NO write path — it is
*structurally* incapable of touching ``transactions``, ``accounts``,
``recurring_transactions``, ``budgets`` or ``categories``. The route builds the
twin read-only and calls this function; nothing is persisted, ever.

============================================================================
5. Future agent integration point (Phase 9)
============================================================================
Exposed to the future Financial Orchestrator Agent as the tool
``simulate_financial_scenario`` (see ``TOOL_SPEC`` below). The Phase-9 wrapper
builds the twin deterministically, calls ``simulate(twin, scenario, ...)``, and
returns ``result.to_dict()`` VERBATIM. The LLM must never alter a number in the
result, and must never be used to compute the projection.  No LangChain /
LlamaIndex / MCP.
"""

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from finance.affordability import check_affordability
from finance.money import ZERO, money
from finance.projection import BalancePoint, ProjectionEvent, project_daily_balances
from finance.recurrence import monthly_occurrences, weekly_occurrences

DEFAULT_HORIZON_DAYS = 30
MAX_HORIZON_DAYS = 365

ONE_OFF_EXPENSE = "one_off_expense"
ONE_OFF_INCOME = "one_off_income"
RECURRING_EXPENSE = "recurring_expense"
RECURRING_INCOME = "recurring_income"
RECURRING_MODIFICATION = "recurring_modification"
INCOME_DELTA = "income_delta"

SCENARIO_TYPES = (
    ONE_OFF_EXPENSE,
    ONE_OFF_INCOME,
    RECURRING_EXPENSE,
    RECURRING_INCOME,
    RECURRING_MODIFICATION,
    INCOME_DELTA,
)

CADENCE_WEEKLY = "weekly"
CADENCE_MONTHLY = "monthly"

TOOL_SPEC = {
    "name": "simulate_financial_scenario",
    "description": (
        "Run a deterministic, in-memory what-if against the student's Financial "
        "Digital Twin: project the baseline balance versus a scenario balance and "
        "compare their minimum balances, ending balances, safety-buffer impact, "
        "and (for a one-off purchase) the Phase-4 affordability verdict. Never "
        "modifies stored data. The caller must not alter the returned result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(SCENARIO_TYPES)},
            "amount": {"type": ["string", "number"],
                       "description": "For one-off / recurring scenarios; must be > 0."},
            "category": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"],
                     "description": "One-off event date YYYY-MM-DD; defaults to the twin's as_of."},
            "cadence": {"type": ["string", "null"], "enum": [CADENCE_WEEKLY, CADENCE_MONTHLY, None]},
            "start_date": {"type": ["string", "null"]},
            "end_date": {"type": ["string", "null"]},
            "day_of_month": {"type": ["integer", "null"], "minimum": 1, "maximum": 31},
            "weekday": {"type": ["integer", "null"], "minimum": 0, "maximum": 6},
            "recurring_id": {"type": ["integer", "null"],
                             "description": "For recurring_modification; must exist on the twin."},
            "new_amount": {"type": ["string", "number", "null"]},
            "new_next_date": {"type": ["string", "null"]},
            "remove": {"type": ["boolean", "null"]},
            "monthly_amount": {"type": ["string", "number", "null"],
                               "description": "For income_delta; must be > 0."},
            "label": {"type": ["string", "null"]},
            "horizon_days": {"type": "integer", "minimum": 0, "maximum": MAX_HORIZON_DAYS,
                             "default": DEFAULT_HORIZON_DAYS},
        },
        "required": ["type"],
    },
}


# --------------------------------------------------------------------------- scenario

@dataclass(frozen=True)
class Scenario:
    type: str
    amount: Optional[Decimal] = None
    category: Optional[str] = None
    date: Optional[date] = None
    cadence: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    day_of_month: Optional[int] = None
    weekday: Optional[int] = None
    recurring_id: Optional[int] = None
    new_amount: Optional[Decimal] = None
    new_next_date: Optional[date] = None
    remove: bool = False
    monthly_amount: Optional[Decimal] = None
    label: Optional[str] = None

    def to_dict(self) -> dict:
        def d(x):
            return x.isoformat() if isinstance(x, date) else x

        out = {"type": self.type}
        for name in ("amount", "new_amount", "monthly_amount"):
            v = getattr(self, name)
            if v is not None:
                out[name] = str(v)
        for name in ("category", "cadence", "label"):
            v = getattr(self, name)
            if v is not None:
                out[name] = v
        for name in ("date", "start_date", "end_date", "new_next_date"):
            v = getattr(self, name)
            if v is not None:
                out[name] = d(v)
        for name in ("day_of_month", "weekday", "recurring_id"):
            v = getattr(self, name)
            if v is not None:
                out[name] = v
        if self.remove:
            out["remove"] = True
        return out


def _pos_money(raw, field_name):
    try:
        value = money(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a valid number") from exc
    if value <= ZERO:
        raise ValueError(f"{field_name} must be greater than 0")
    return value


def _parse_date(raw, field_name):
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date") from exc


def build_scenario(raw: dict, *, as_of: date) -> Scenario:
    """Validate a raw scenario dict into a :class:`Scenario`. Raises ``ValueError``
    (which the API maps to HTTP 400) for anything invalid."""
    if not isinstance(raw, dict):
        raise ValueError("scenario must be an object")
    stype = raw.get("type")
    if stype not in SCENARIO_TYPES:
        raise ValueError(
            f"unsupported scenario type; expected one of {', '.join(SCENARIO_TYPES)}"
        )

    label = raw.get("label")
    if label is not None:
        label = str(label).strip() or None

    if stype in (ONE_OFF_EXPENSE, ONE_OFF_INCOME):
        amount = _pos_money(raw.get("amount"), "amount")
        when = _parse_date(raw["date"], "date") if raw.get("date") else as_of
        if when < as_of:
            raise ValueError("date must not be before the twin's as_of date")
        return Scenario(
            type=stype,
            amount=amount,
            date=when,
            category=(str(raw["category"]).strip() if raw.get("category") else None),
            label=label,
        )

    if stype in (RECURRING_EXPENSE, RECURRING_INCOME):
        amount = _pos_money(raw.get("amount"), "amount")
        cadence = raw.get("cadence")
        if cadence not in (CADENCE_WEEKLY, CADENCE_MONTHLY):
            raise ValueError("cadence must be 'weekly' or 'monthly'")
        start = _parse_date(raw["start_date"], "start_date") if raw.get("start_date") else as_of
        if start < as_of:
            raise ValueError("start_date must not be before the twin's as_of date")
        end = _parse_date(raw["end_date"], "end_date") if raw.get("end_date") else None
        if end is not None and end < start:
            raise ValueError("end_date must not be before start_date")
        dom = raw.get("day_of_month")
        if dom is not None:
            try:
                dom = int(dom)
            except (TypeError, ValueError) as exc:
                raise ValueError("day_of_month must be an integer 1-31") from exc
            if not 1 <= dom <= 31:
                raise ValueError("day_of_month must be between 1 and 31")
        wd = raw.get("weekday")
        if wd is not None:
            try:
                wd = int(wd)
            except (TypeError, ValueError) as exc:
                raise ValueError("weekday must be an integer 0-6") from exc
            if not 0 <= wd <= 6:
                raise ValueError("weekday must be between 0 (Mon) and 6 (Sun)")
        return Scenario(
            type=stype, amount=amount, cadence=cadence, start_date=start, end_date=end,
            day_of_month=dom, weekday=wd,
            category=(str(raw["category"]).strip() if raw.get("category") else None),
            label=label,
        )

    if stype == INCOME_DELTA:
        monthly_amount = _pos_money(raw.get("monthly_amount"), "monthly_amount")
        start = _parse_date(raw["start_date"], "start_date") if raw.get("start_date") else as_of
        if start < as_of:
            raise ValueError("start_date must not be before the twin's as_of date")
        return Scenario(type=stype, monthly_amount=monthly_amount, start_date=start, label=label)

    # RECURRING_MODIFICATION
    rid = raw.get("recurring_id")
    if rid is None:
        raise ValueError("recurring_id is required for recurring_modification")
    try:
        rid = int(rid)
    except (TypeError, ValueError) as exc:
        raise ValueError("recurring_id must be an integer") from exc
    new_amount = _pos_money(raw["new_amount"], "new_amount") if raw.get("new_amount") is not None else None
    new_next_date = _parse_date(raw["new_next_date"], "new_next_date") if raw.get("new_next_date") else None
    remove = bool(raw.get("remove"))
    if new_amount is None and new_next_date is None and not remove:
        raise ValueError(
            "recurring_modification needs at least one of new_amount, new_next_date, remove"
        )
    return Scenario(
        type=RECURRING_MODIFICATION, recurring_id=rid, new_amount=new_amount,
        new_next_date=new_next_date, remove=remove, label=label,
    )


# --------------------------------------------------------------- recurrence expansion

def _recurring_occurrences(scenario: Scenario, *, nominal_end: date) -> List[date]:
    end = nominal_end if scenario.end_date is None else min(nominal_end, scenario.end_date)
    start = scenario.start_date
    if scenario.cadence == CADENCE_MONTHLY:
        return monthly_occurrences(start, end, day_of_month=scenario.day_of_month)
    return weekly_occurrences(start, end, weekday=scenario.weekday)


# ------------------------------------------------------------------------- result

@dataclass(frozen=True)
class SideState:
    starting_balance: Decimal
    min_balance: Decimal
    min_balance_date: date
    end_balance: Decimal
    projection: Tuple[BalancePoint, ...]

    def to_dict(self) -> dict:
        return {
            "starting_balance": str(self.starting_balance),
            "min_balance": str(self.min_balance),
            "min_balance_date": self.min_balance_date.isoformat(),
            "end_balance": str(self.end_balance),
            "projection": [
                {"date": p.date.isoformat(), "balance": str(p.balance)} for p in self.projection
            ],
        }


@dataclass(frozen=True)
class SimulationResult:
    scenario: Scenario
    as_of: date
    horizon_days: int
    safety_buffer: Decimal
    baseline: SideState
    scenario_side: SideState
    min_balance_delta: Decimal
    end_balance_delta: Decimal
    safety_buffer_impact: str
    affordability_before: Optional[dict]
    affordability_after: Optional[dict]
    changes: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "scenario_input": self.scenario.to_dict(),
            "as_of": self.as_of.isoformat(),
            "horizon_days": self.horizon_days,
            "safety_buffer": str(self.safety_buffer),
            "baseline": self.baseline.to_dict(),
            "scenario": self.scenario_side.to_dict(),
            "comparison": {
                "min_balance_delta": str(self.min_balance_delta),
                "end_balance_delta": str(self.end_balance_delta),
                "affordability_before": self.affordability_before,
                "affordability_after": self.affordability_after,
                "safety_buffer_impact": self.safety_buffer_impact,
                "changes": list(self.changes),
            },
        }


def _side(projection) -> SideState:
    return SideState(
        starting_balance=projection.start_balance,
        min_balance=projection.min_balance,
        min_balance_date=projection.min_date,
        end_balance=projection.end_balance,
        projection=projection.points,
    )


def _safety_buffer_impact(baseline_min: Decimal, scenario_min: Decimal, buffer: Decimal) -> str:
    base_ok = baseline_min >= buffer
    scen_ok = scenario_min >= buffer
    if base_ok and scen_ok:
        return "none"
    if base_ok and not scen_ok:
        return "breached"
    if not base_ok and scen_ok:
        return "restored"
    return "deepened" if scenario_min < baseline_min else "eased"


def _scenario_events_and_twin(scenario: Scenario, twin, *, nominal_end: date):
    """Return ``(scenario_twin, extra_events)``."""
    if scenario.type == ONE_OFF_EXPENSE:
        return twin, [ProjectionEvent(scenario.date, -scenario.amount, "scenario_expense",
                                      scenario.label or scenario.category or "one-off expense")]
    if scenario.type == ONE_OFF_INCOME:
        return twin, [ProjectionEvent(scenario.date, scenario.amount, "scenario_income",
                                      scenario.label or "one-off income")]
    if scenario.type in (RECURRING_EXPENSE, RECURRING_INCOME):
        sign = -1 if scenario.type == RECURRING_EXPENSE else 1
        kind = "scenario_recurring_expense" if sign < 0 else "scenario_recurring_income"
        label = scenario.label or ("recurring expense" if sign < 0 else "recurring income")
        events = [
            ProjectionEvent(occ, sign * scenario.amount, kind, label)
            for occ in _recurring_occurrences(scenario, nominal_end=nominal_end)
        ]
        return twin, events
    if scenario.type == INCOME_DELTA:
        events = [
            ProjectionEvent(occ, scenario.monthly_amount, "scenario_income_delta",
                            scenario.label or "expected income")
            for occ in monthly_occurrences(scenario.start_date, nominal_end, day_of_month=None)
        ]
        return twin, events
    # RECURRING_MODIFICATION
    ids = {r.id for r in twin.recurring}
    if scenario.recurring_id not in ids:
        raise ValueError(f"unknown recurring transaction id: {scenario.recurring_id}")
    new_recurring = []
    for rec in twin.recurring:
        if rec.id == scenario.recurring_id:
            if scenario.remove:
                continue
            rec = dataclasses.replace(
                rec,
                amount=scenario.new_amount if scenario.new_amount is not None else rec.amount,
                next_date=scenario.new_next_date or rec.next_date,
            )
        new_recurring.append(rec)
    return dataclasses.replace(twin, recurring=tuple(new_recurring)), []


def simulate(twin, scenario, *, horizon_days: int = DEFAULT_HORIZON_DAYS) -> SimulationResult:
    """Run a deterministic what-if. ``scenario`` may be a raw dict or a
    :class:`Scenario`. Raises ``ValueError`` for any invalid input."""
    if isinstance(horizon_days, bool) or isinstance(horizon_days, float):
        raise ValueError("horizon_days must be an integer")
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon_days must be an integer") from exc
    if not (0 <= horizon_days <= MAX_HORIZON_DAYS):
        raise ValueError(f"horizon_days must be between 0 and {MAX_HORIZON_DAYS}")

    if isinstance(scenario, dict):
        scenario = build_scenario(scenario, as_of=twin.as_of)

    as_of = twin.as_of
    nominal_end = as_of + timedelta(days=horizon_days)

    scenario_twin, events = _scenario_events_and_twin(scenario, twin, nominal_end=nominal_end)

    # A one-off event dated past the nominal horizon extends it (Phase 4 rule).
    horizon_end = nominal_end
    for e in events:
        if e.date > horizon_end:
            horizon_end = e.date
    effective_horizon_days = (horizon_end - as_of).days

    baseline_proj = project_daily_balances(twin, horizon_days=effective_horizon_days)
    scenario_proj = project_daily_balances(
        scenario_twin, horizon_days=effective_horizon_days, extra_events=events
    )

    baseline = _side(baseline_proj)
    scenario_side = _side(scenario_proj)

    min_delta = money(scenario_side.min_balance - baseline.min_balance)
    end_delta = money(scenario_side.end_balance - baseline.end_balance)
    buffer = money(twin.safety_buffer)
    impact = _safety_buffer_impact(baseline.min_balance, scenario_side.min_balance, buffer)

    affordability_before = None
    if scenario.type == ONE_OFF_EXPENSE:
        affordability_before = check_affordability(
            twin,
            amount=scenario.amount,
            category=scenario.category,
            purchase_date=scenario.date,
            horizon_days=horizon_days,
        ).to_dict()

    changes = _describe(scenario, events, baseline, scenario_side, min_delta, end_delta,
                        impact, buffer, effective_horizon_days)

    return SimulationResult(
        scenario=scenario,
        as_of=as_of,
        horizon_days=effective_horizon_days,
        safety_buffer=buffer,
        baseline=baseline,
        scenario_side=scenario_side,
        min_balance_delta=min_delta,
        end_balance_delta=end_delta,
        safety_buffer_impact=impact,
        affordability_before=affordability_before,
        affordability_after=None,
        changes=tuple(changes),
    )


def _describe(scenario, events, baseline, scenario_side, min_delta, end_delta, impact,
              buffer, horizon) -> List[str]:
    out: List[str] = []
    if scenario.type in (RECURRING_EXPENSE, RECURRING_INCOME, INCOME_DELTA):
        out.append(f"{len(events)} hypothetical occurrence(s) within {horizon} days.")
    elif scenario.type == RECURRING_MODIFICATION:
        if scenario.remove:
            out.append(f"Recurring item {scenario.recurring_id} removed for this scenario.")
        else:
            bits = []
            if scenario.new_amount is not None:
                bits.append(f"amount -> {scenario.new_amount}")
            if scenario.new_next_date is not None:
                bits.append(f"next date -> {scenario.new_next_date.isoformat()}")
            out.append(f"Recurring item {scenario.recurring_id} changed ({', '.join(bits)}).")
    out.append(
        f"Projected minimum balance changes by {min_delta} "
        f"(from {baseline.min_balance} to {scenario_side.min_balance})."
    )
    out.append(f"Projected ending balance changes by {end_delta} over {horizon} days.")
    impact_msg = {
        "none": f"Safety buffer ({buffer}) is not crossed in either case.",
        "breached": f"Scenario pushes the projected minimum below the {buffer} safety buffer.",
        "restored": f"Scenario lifts the projected minimum back to or above the {buffer} safety buffer.",
        "deepened": f"Already below the {buffer} safety buffer; scenario makes the shortfall worse.",
        "eased": f"Still below the {buffer} safety buffer, but the scenario reduces the shortfall.",
    }
    out.append(impact_msg[impact])
    return out
