"""Assemble the Portable Financial Profile (JSON schema v1.0).

Pure: given a ``FinanceRepository`` and an account id, return a dict. All money
is emitted as 2-decimal strings, matching the rest of the API.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from finance.forecast import DEFAULT_HORIZON_DAYS, DETECTION_LOOKBACK_DAYS, forecast
from finance.models import CREDIT, DEBIT
from finance.money import ZERO, money
from finance.twin import build_twin_state
from finance.repository import FinanceRepository
from decision.goal_progress import compute_goal_progress

REPORT_VERSION = "1.0"
CURRENCY = "INR"

# preset -> (label, day span or None for "all")
PERIOD_PRESETS = {
    "30d": ("Last 30 days", 30),
    "3m": ("Last 3 months", 91),
    "6m": ("Last 6 months", 182),
    "12m": ("Last 12 months", 365),
    "all": ("All available data", None),
    "custom": ("Custom range", None),
}
DEFAULT_PERIOD = "3m"

_DAYS_PER_MONTH = Decimal("30.4375")


def _s(value) -> str:
    return str(money(value))


def _pct(part: Decimal, whole: Decimal) -> float:
    if whole is None or whole == 0:
        return 0.0
    return round(float(part / whole * 100), 1)


def resolve_period(preset: str, *, as_of: date, custom_from=None, custom_to=None,
                   earliest_txn: date | None = None) -> dict:
    """Turn a preset (+ optional custom range) into a concrete window.

    Returns ``{"preset", "label", "from", "to", "days"}`` with ISO date strings.
    Invalid input raises ``ValueError`` (the route turns that into HTTP 400).
    """
    preset = (preset or DEFAULT_PERIOD).lower()
    if preset not in PERIOD_PRESETS:
        raise ValueError(f"period must be one of: {', '.join(PERIOD_PRESETS)}")
    label, span = PERIOD_PRESETS[preset]
    to_d = as_of

    if preset == "custom":
        if not custom_from or not custom_to:
            raise ValueError("custom period requires 'from' and 'to' dates")
        from_d, to_d = custom_from, custom_to
        if from_d > to_d:
            raise ValueError("'from' must be on or before 'to'")
        if to_d > as_of:
            to_d = as_of
    elif preset == "all":
        from_d = earliest_txn or (as_of - timedelta(days=365))
    else:
        from_d = to_d - timedelta(days=span - 1)

    return {
        "preset": preset,
        "label": label,
        "from": from_d.isoformat(),
        "to": to_d.isoformat(),
        "days": (to_d - from_d).days + 1,
    }


def build_financial_profile(
    repo: FinanceRepository,
    student_id: int,
    *,
    account_name: str | None,
    period: dict,
    as_of: date | None = None,
    generated_at: str,
) -> dict:
    """Build the schema-v1.0 report dict. Read-only."""
    as_of = as_of or date.today()
    period_from = date.fromisoformat(period["from"])
    period_to = date.fromisoformat(period["to"])
    months = max(Decimal("1"), (Decimal(period["days"]) / _DAYS_PER_MONTH))

    twin = build_twin_state(repo, student_id, as_of=as_of)

    # --- transactions in the selected window -----------------------------------
    txns = list(repo.get_transactions(student_id, start=period_from, end=period_to))
    debits = [t for t in txns if t.direction == DEBIT]
    credits = [t for t in txns if t.direction == CREDIT]

    spend_total = sum((t.amount for t in debits), ZERO)
    income_total = sum((t.amount for t in credits), ZERO)

    by_category: dict[str, dict] = {}
    for t in debits:
        cat = t.category_name or "Uncategorized"
        slot = by_category.setdefault(cat, {"total": ZERO, "count": 0})
        slot["total"] += t.amount
        slot["count"] += 1
    category_rows = sorted(
        (
            {
                "category": cat,
                "total": _s(v["total"]),
                "transaction_count": v["count"],
                "share_pct": _pct(v["total"], spend_total),
            }
            for cat, v in by_category.items()
        ),
        key=lambda r: Decimal(r["total"]),
        reverse=True,
    )

    by_merchant: dict[str, dict] = {}
    for t in debits:
        m = (t.merchant_name or "Unknown").strip() or "Unknown"
        slot = by_merchant.setdefault(m, {"total": ZERO, "count": 0})
        slot["total"] += t.amount
        slot["count"] += 1
    merchant_rows = sorted(
        (
            {"merchant": m, "total": _s(v["total"]), "transaction_count": v["count"]}
            for m, v in by_merchant.items()
        ),
        key=lambda r: Decimal(r["total"]),
        reverse=True,
    )[:10]

    txn_dates = [t.payment_date for t in txns]

    # --- recurring commitments (no raw identifiers) ---------------------------
    recurring_rows = [
        {
            "label": r.label,
            "merchant": r.merchant_name,
            "amount": _s(r.amount),
            "direction": r.direction,
            "cadence": r.cadence,
            "next_date": r.next_date.isoformat() if r.next_date else None,
        }
        for r in twin.recurring
    ]
    recurring_monthly_out = sum(
        (r.amount for r in twin.recurring
         if r.direction == DEBIT and r.cadence == "monthly"),
        ZERO,
    )

    # --- budgets (current month, from the twin) -----------------------------
    budget_rows = []
    for cat, limit in sorted(twin.budgets.items()):
        spent = twin.spending_by_category.get(cat, ZERO)
        budget_rows.append({
            "category": cat,
            "monthly_limit": _s(limit),
            "month_spending": _s(spent),
            "utilization_pct": _pct(spent, limit),
            "remaining": _s(limit - spent),
        })

    # --- savings goals ----------------------------------------------------------
    goal_rows = []
    goals_on_track = 0
    for g in repo.get_savings_goals(student_id, status=None):
        prog = compute_goal_progress(g, as_of=as_of).to_dict()
        if prog.get("on_track"):
            goals_on_track += 1
        goal_rows.append({
            "name": g.name,
            "status": g.status,
            "target_amount": _s(g.target_amount),
            "current_amount": _s(g.current_amount),
            "monthly_contribution": _s(g.monthly_contribution),
            "target_date": g.target_date.isoformat() if g.target_date else None,
            "percent_complete": prog.get("percent_complete"),
            "remaining_amount": prog.get("remaining_amount"),
            "required_monthly_contribution": prog.get("required_monthly_contribution"),
            "projected_completion_date": prog.get("projected_completion_date"),
            "on_track": prog.get("on_track"),
        })

    # --- forecast -------------------------------------------------------------
    history = repo.get_transactions(
        student_id, start=as_of - timedelta(days=DETECTION_LOOKBACK_DAYS), end=as_of
    )
    fc = forecast(twin, history, horizon_days=DEFAULT_HORIZON_DAYS).to_dict()
    forecast_block = {
        "horizon_days": fc["horizon_days"],
        "starting_balance": fc["starting_balance"],
        "projected_min_balance": fc["projected_min_balance"],
        "projected_min_balance_date": fc["projected_min_balance_date"],
        "projected_end_balance": fc["projected_end_balance"],
        "projected_income": fc["projected_income"],
        "projected_expenses": fc["projected_expenses"],
        "projected_net": fc["projected_net"],
        "safety_buffer": fc["safety_buffer"],
        "safety_buffer_breached": fc["safety_buffer_breached"],
        "breach_date": fc["breach_date"],
        "confidence": fc["confidence"],
    }

    report = {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "currency": CURRENCY,
        "period": period,
        "account_profile": {
            "name": account_name or None,
            "report_generated_on": as_of.isoformat(),
            "currency": CURRENCY,
        },
        "financial_snapshot": {
            "as_of": twin.as_of.isoformat(),
            "current_balance": _s(twin.current_balance),
            "opening_balance": _s(twin.opening_balance),
            "safety_buffer": _s(twin.safety_buffer),
            "committed_upcoming": _s(twin.committed_upcoming),
            "committed_upcoming_horizon_days": twin.committed_upcoming_horizon_days,
            "discretionary_buffer": _s(twin.discretionary_buffer),
            "available_safe_to_spend": _s(max(twin.discretionary_buffer, ZERO)),
        },
        "income": {
            "period_total": _s(income_total),
            "monthly_average": _s(income_total / months),
            "transaction_count": len(credits),
        },
        "spending": {
            "period_total": _s(spend_total),
            "monthly_average": _s(spend_total / months),
            "daily_average": _s(spend_total / Decimal(period["days"])),
            "transaction_count": len(debits),
            "recurring_monthly_commitment": _s(recurring_monthly_out),
            "by_category": category_rows,
            "top_categories": [r["category"] for r in category_rows[:5]],
            "by_merchant": merchant_rows,
        },
        "budgets": budget_rows,
        "recurring_commitments": recurring_rows,
        "savings_goals": goal_rows,
        "forecast": forecast_block,
        "transaction_summary": {
            "count": len(txns),
            "debit_count": len(debits),
            "credit_count": len(credits),
            "period_from": period["from"],
            "period_to": period["to"],
            "first_transaction_date": min(txn_dates).isoformat() if txn_dates else None,
            "last_transaction_date": max(txn_dates).isoformat() if txn_dates else None,
        },
        "insights": _insights(
            spend_total=spend_total,
            months=months,
            category_rows=category_rows,
            budget_rows=budget_rows,
            recurring_monthly_out=recurring_monthly_out,
            recurring_count=len([r for r in twin.recurring if r.direction == DEBIT]),
            goal_total=len(goal_rows),
            goals_on_track=goals_on_track,
            forecast_block=forecast_block,
        ),
        "privacy": {
            "contains_raw_sms": False,
            "contains_full_account_numbers": False,
            "contains_credentials": False,
            "contains_ingest_tokens": False,
            "contains_personal_identifiers": False,
        },
    }
    return report


def _insights(*, spend_total, months, category_rows, budget_rows,
              recurring_monthly_out, recurring_count, goal_total, goals_on_track,
              forecast_block) -> list[str]:
    """Deterministic, backend-supported statements only. No psychological claims."""
    out: list[str] = []

    if spend_total > 0 and category_rows:
        top = category_rows[0]
        out.append(
            f"{top['category']} was the largest recorded spending category during the "
            f"selected period, at {top['share_pct']}% of total spending "
            f"({CURRENCY} {top['total']})."
        )
        monthly_avg = money(spend_total / months)
        out.append(
            f"Recorded spending averaged {CURRENCY} {monthly_avg} per month over the "
            f"selected period."
        )

    if recurring_count:
        out.append(
            f"{recurring_count} recurring expense "
            f"{'commitment is' if recurring_count == 1 else 'commitments are'} configured, "
            f"totalling {CURRENCY} {money(recurring_monthly_out)} per month."
        )

    over = [b for b in budget_rows if Decimal(b["remaining"]) < 0]
    if budget_rows:
        if over:
            out.append(
                f"{len(over)} of {len(budget_rows)} budgeted categories are over their "
                f"monthly limit this month."
            )
        else:
            out.append(
                f"All {len(budget_rows)} budgeted categories are within their monthly "
                f"limit this month."
            )

    if goal_total:
        out.append(
            f"{goals_on_track} of {goal_total} savings "
            f"{'goal is' if goal_total == 1 else 'goals are'} on track based on the "
            f"current contribution rate."
        )

    if forecast_block["safety_buffer_breached"] and forecast_block["breach_date"]:
        out.append(
            f"Projected balance falls below the configured safety buffer "
            f"({CURRENCY} {forecast_block['safety_buffer']}) around "
            f"{forecast_block['breach_date']}."
        )
    else:
        out.append(
            f"Projected balance stays above the configured safety buffer for the next "
            f"{forecast_block['horizon_days']} days."
        )

    return out
