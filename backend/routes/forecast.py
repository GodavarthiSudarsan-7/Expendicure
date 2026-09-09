"""GET /api/forecast — deterministic cash-flow forecast for the authenticated
student.

Read-only: builds the twin and reads recent transaction history for recurring
detection, then calls ``finance.forecast.forecast``. Nothing is written. The
future Phase 9 agent calls the same function in-process via the tool registry.
"""

from datetime import timedelta

from flask import Blueprint, jsonify, request

from config import Config
from date_filters import parse_iso_date
from finance.forecast import (
    DEFAULT_HORIZON_DAYS,
    DETECTION_LOOKBACK_DAYS,
    MAX_HORIZON_DAYS,
    MIN_HORIZON_DAYS,
    forecast,
)
from finance.twin import build_twin_state
from finance_db import get_repository
from middleware import token_required

forecast_bp = Blueprint('forecast', __name__)


@forecast_bp.route('', methods=['GET'], strict_slashes=False)
@token_required
def get_forecast(current_student):
    as_of = None
    raw_as_of = request.args.get('as_of')
    if raw_as_of:
        try:
            as_of = parse_iso_date(raw_as_of)
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    raw_horizon = request.args.get('horizon_days', DEFAULT_HORIZON_DAYS)
    try:
        horizon_days = int(raw_horizon)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    if not (MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS):
        return jsonify({
            "error": f"horizon_days must be between {MIN_HORIZON_DAYS} and {MAX_HORIZON_DAYS}"
        }), 400

    repo = get_repository()
    twin = build_twin_state(
        repo, current_student['id'], as_of=as_of, default_safety_buffer=Config.SAFETY_BUFFER
    )
    history = repo.get_transactions(
        current_student['id'],
        start=twin.as_of - timedelta(days=DETECTION_LOOKBACK_DAYS),
        end=twin.as_of,
    )

    try:
        result = forecast(twin, history, horizon_days=horizon_days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result.to_dict())
