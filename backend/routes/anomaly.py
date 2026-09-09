"""GET /api/anomalies - deterministic financial anomaly detection.

Read-only: reads the student's transactions, budgets and categories, calls
``finance.anomaly.detect_anomalies``, and returns the structured findings.
Never writes. The future Phase 9 agent calls the same function in-process.
"""

from datetime import date

from flask import Blueprint, jsonify, request

from date_filters import parse_iso_date
from finance.anomaly import (
    HISTORY_DAYS_DEFAULT,
    HISTORY_DAYS_MAX,
    HISTORY_DAYS_MIN,
    detect_anomalies,
)
from finance_db import get_repository
from middleware import token_required

anomaly_bp = Blueprint('anomaly', __name__)


@anomaly_bp.route('', methods=['GET'], strict_slashes=False)
@token_required
def get_anomalies(current_student):
    student_id = current_student['id']

    as_of = date.today()
    raw_as_of = request.args.get('as_of')
    if raw_as_of:
        try:
            as_of = parse_iso_date(raw_as_of)
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    raw_history = request.args.get('history_days', HISTORY_DAYS_DEFAULT)
    try:
        history_days = int(raw_history)
    except (TypeError, ValueError):
        return jsonify({"error": "history_days must be an integer"}), 400
    if not (HISTORY_DAYS_MIN <= history_days <= HISTORY_DAYS_MAX):
        return jsonify({
            "error": f"history_days must be between {HISTORY_DAYS_MIN} and {HISTORY_DAYS_MAX}"
        }), 400

    repo = get_repository()
    # All transactions up to as_of: the engine bounds its statistical windows by
    # history_days internally, but needs the full set to know whether a merchant
    # has appeared before.
    transactions = repo.get_transactions(student_id, end=as_of)
    budgets = repo.get_budgets(student_id, f"{as_of.year:04d}-{as_of.month:02d}")
    categories = repo.get_categories(student_id)

    try:
        result = detect_anomalies(
            transactions,
            budgets=budgets,
            categories=categories,
            as_of=as_of,
            history_days=history_days,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result.to_dict())
