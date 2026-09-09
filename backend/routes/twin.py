"""GET /api/twin/state — the Financial Digital Twin for the authenticated student.

Every value in the response is computed deterministically by
``finance.twin.build_twin_state`` from database rows. Money is returned as
2-decimal strings, consistent with /api/account.
"""

from flask import Blueprint, jsonify, request

from config import Config
from date_filters import parse_iso_date
from finance.twin import build_twin_state
from finance_db import get_repository
from middleware import token_required

twin_bp = Blueprint('twin', __name__)


def _serialize(state):
    return {
        "student_id": state.student_id,
        "as_of": state.as_of.isoformat(),
        "month": state.month,
        "opening_balance": str(state.opening_balance),
        "current_balance": str(state.current_balance),
        "month_income": str(state.month_income),
        "month_spending": str(state.month_spending),
        "month_net": str(state.month_net),
        "month_discretionary_spending": str(state.month_discretionary_spending),
        "spending_by_category": {k: str(v) for k, v in state.spending_by_category.items()},
        "budgets": {k: str(v) for k, v in state.budgets.items()},
        "recurring": [
            {
                "id": r.id,
                "label": r.label,
                "merchant_name": r.merchant_name,
                "amount": str(r.amount),
                "direction": r.direction,
                "cadence": r.cadence,
                "day_of_month": r.day_of_month,
                "weekday": r.weekday,
                "next_date": r.next_date.isoformat() if r.next_date else None,
                "source": r.source,
                "active": r.active,
            }
            for r in state.recurring
        ],
        "safety_buffer": str(state.safety_buffer),
        "committed_upcoming": str(state.committed_upcoming),
        "committed_upcoming_horizon_days": state.committed_upcoming_horizon_days,
        "discretionary_buffer": str(state.discretionary_buffer),
    }


@twin_bp.route('/state', methods=['GET'], strict_slashes=False)
@token_required
def get_twin_state(current_student):
    as_of = None
    raw = request.args.get('as_of')
    if raw:
        try:
            as_of = parse_iso_date(raw)
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    state = build_twin_state(
        get_repository(),
        current_student['id'],
        as_of=as_of,
        default_safety_buffer=Config.SAFETY_BUFFER,
    )
    return jsonify(_serialize(state))
