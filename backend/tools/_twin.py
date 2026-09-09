"""Shared helpers: build the twin for a tool call, and compact serializers.

Compact = only the fields Herman needs to explain a result. We deliberately do
NOT dump raw transaction history to the LLM.
"""

from datetime import date, timedelta

from config import Config
from finance.twin import build_twin_state


def twin_for(ctx, as_of=None):
    when = None
    if as_of:
        when = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    return build_twin_state(
        ctx.repo_factory(),
        ctx.user_id,
        as_of=when or ctx.as_of,
        default_safety_buffer=Config.SAFETY_BUFFER,
    )


def twin_summary(state) -> dict:
    """A small, human-explainable snapshot."""
    return {
        "as_of": state.as_of.isoformat(),
        "month": state.month,
        "current_balance": str(state.current_balance),
        "safety_buffer": str(state.safety_buffer),
        "discretionary_buffer": str(state.discretionary_buffer),
        "committed_upcoming": str(state.committed_upcoming),
        "month_income": str(state.month_income),
        "month_spending": str(state.month_spending),
        "month_net": str(state.month_net),
        "top_spending_categories": sorted(
            ({"category": k, "spent": str(v)} for k, v in state.spending_by_category.items()),
            key=lambda r: float(r["spent"]), reverse=True,
        )[:5],
        "next_commitments": [
            {"label": r.label, "amount": str(r.amount), "direction": r.direction,
             "next_date": r.next_date.isoformat() if r.next_date else None}
            for r in sorted(
                (r for r in state.recurring if r.active),
                key=lambda r: (r.next_date or date.max),
            )[:4]
        ],
    }


def history_for_forecast(ctx, twin):
    return ctx.repo_factory().get_transactions(
        ctx.user_id, start=twin.as_of - timedelta(days=180), end=twin.as_of
    )
