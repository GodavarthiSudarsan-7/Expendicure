"""POST /api/affordability/check — deterministic "Can I afford this?" for the
authenticated student.

The HTTP embodiment of ``finance.affordability.check_affordability``. The future
Phase 9 agent will call that function in-process (not over HTTP) via the tool
registry; this route and the tool share the exact same engine and result shape.
"""

from flask import Blueprint, jsonify, request

from config import Config
from date_filters import parse_iso_date
from finance.affordability import DEFAULT_HORIZON_DAYS, check_affordability
from finance.twin import build_twin_state
from finance_db import get_repository
from middleware import token_required

affordability_bp = Blueprint('affordability', __name__)

MAX_HORIZON_DAYS = 365


@affordability_bp.route('/check', methods=['POST'], strict_slashes=False)
@token_required
def post_check(current_student):
    data = request.get_json(silent=True) or {}

    if data.get('amount') in (None, ''):
        return jsonify({"error": "amount is required"}), 400

    as_of = None
    if data.get('as_of'):
        try:
            as_of = parse_iso_date(data['as_of'])
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    purchase_date = None
    if data.get('date'):
        try:
            purchase_date = parse_iso_date(data['date'])
        except ValueError:
            return jsonify({"error": "date must be a valid YYYY-MM-DD date"}), 400

    horizon_days = data.get('horizon_days', DEFAULT_HORIZON_DAYS)
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    if not (0 <= horizon_days <= MAX_HORIZON_DAYS):
        return jsonify({"error": f"horizon_days must be between 0 and {MAX_HORIZON_DAYS}"}), 400

    twin = build_twin_state(
        get_repository(),
        current_student['id'],
        as_of=as_of,
        default_safety_buffer=Config.SAFETY_BUFFER,
    )

    try:
        result = check_affordability(
            twin,
            amount=data['amount'],
            category=data.get('category'),
            purchase_date=purchase_date,
            horizon_days=horizon_days,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result.to_dict())
