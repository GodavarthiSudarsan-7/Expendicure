"""CRUD for user-declared recurring transactions.

Phase 2 provides the model and API only. Detection of recurring items from
history, and use of these rows in forecasting/affordability, come later.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from database import execute_query
from date_filters import parse_iso_date
from finance.models import DIRECTIONS, CADENCES, CADENCE_MONTHLY, CADENCE_WEEKLY
from middleware import token_required

recurring_bp = Blueprint('recurring', __name__)

RECURRING_SELECT = """
    SELECT id, student_id, label, merchant_name, amount, direction, cadence,
           day_of_month, weekday, next_date, source, confidence, active,
           created_at, updated_at
    FROM recurring_transactions
    WHERE id = %s
"""


def _validate_payload(data, *, partial=False):
    """Return (clean_dict, None) or (None, error). ``partial`` allows a subset
    (used by PUT)."""
    clean = {}

    def required(name):
        return not partial or name in data

    if required('label'):
        if not data.get('label'):
            return None, "label is required"
        clean['label'] = str(data['label']).strip()

    if required('merchant_name'):
        if not data.get('merchant_name'):
            return None, "merchant_name is required"
        clean['merchant_name'] = str(data['merchant_name']).strip()

    if required('amount'):
        try:
            amount = Decimal(str(data['amount']))
        except (InvalidOperation, TypeError, ValueError):
            return None, "amount must be a number"
        if amount.is_nan() or amount.is_infinite() or amount <= 0:
            return None, "amount must be greater than 0"
        clean['amount'] = str(amount)

    if 'direction' in data or not partial:
        direction = (data.get('direction') or 'debit').lower()
        if direction not in DIRECTIONS:
            return None, "direction must be 'debit' or 'credit'"
        clean['direction'] = direction

    if required('cadence'):
        cadence = (data.get('cadence') or '').lower()
        if cadence not in CADENCES:
            return None, "cadence must be 'weekly' or 'monthly'"
        clean['cadence'] = cadence

    if required('next_date'):
        try:
            clean['next_date'] = parse_iso_date(data['next_date']).isoformat()
        except (ValueError, KeyError, TypeError):
            return None, "next_date must be a valid YYYY-MM-DD date"

    if 'day_of_month' in data and data['day_of_month'] is not None:
        try:
            dom = int(data['day_of_month'])
        except (TypeError, ValueError):
            return None, "day_of_month must be an integer 1-31"
        if not 1 <= dom <= 31:
            return None, "day_of_month must be between 1 and 31"
        clean['day_of_month'] = dom

    if 'weekday' in data and data['weekday'] is not None:
        try:
            wd = int(data['weekday'])
        except (TypeError, ValueError):
            return None, "weekday must be an integer 0-6"
        if not 0 <= wd <= 6:
            return None, "weekday must be between 0 (Mon) and 6 (Sun)"
        clean['weekday'] = wd

    if 'active' in data:
        clean['active'] = bool(data['active'])

    # Cross-field sanity for a full payload.
    effective_cadence = clean.get('cadence')
    if not partial and effective_cadence == CADENCE_MONTHLY and 'day_of_month' not in clean:
        return None, "day_of_month is required for a monthly recurring item"
    if not partial and effective_cadence == CADENCE_WEEKLY and 'weekday' not in clean:
        return None, "weekday is required for a weekly recurring item"

    return clean, None


@recurring_bp.route('', methods=['GET'], strict_slashes=False)
@token_required
def list_recurring(current_student):
    include_inactive = request.args.get('include_inactive') in ('1', 'true', 'yes')
    sql = (
        "SELECT id, student_id, label, merchant_name, amount, direction, cadence, "
        "day_of_month, weekday, next_date, source, confidence, active, "
        "created_at, updated_at FROM recurring_transactions WHERE student_id = %s"
    )
    if not include_inactive:
        sql += " AND active = TRUE"
    sql += " ORDER BY next_date, id"
    rows = execute_query(sql, (current_student['id'],), fetch_all=True)
    if rows is None:
        return jsonify({"error": "Failed to fetch recurring transactions"}), 500
    return jsonify(rows)


@recurring_bp.route('', methods=['POST'], strict_slashes=False)
@token_required
def create_recurring(current_student):
    data = request.get_json(silent=True) or {}
    clean, err = _validate_payload(data, partial=False)
    if err:
        return jsonify({"error": err}), 400

    row_id = execute_query(
        "INSERT INTO recurring_transactions "
        "(student_id, label, merchant_name, amount, direction, cadence, "
        " day_of_month, weekday, next_date, source, active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'user', %s)",
        (
            current_student['id'],
            clean['label'],
            clean['merchant_name'],
            clean['amount'],
            clean['direction'],
            clean['cadence'],
            clean.get('day_of_month'),
            clean.get('weekday'),
            clean['next_date'],
            clean.get('active', True),
        ),
        commit=True,
    )
    if row_id is None:
        return jsonify({"error": "Failed to create recurring transaction"}), 500
    return jsonify(execute_query(RECURRING_SELECT, (row_id,), fetch_one=True)), 201


def _owned_row(student_id, row_id):
    return execute_query(
        "SELECT id FROM recurring_transactions WHERE id = %s AND student_id = %s",
        (row_id, student_id),
        fetch_one=True,
    )


@recurring_bp.route('/<int:row_id>', methods=['PUT'])
@token_required
def update_recurring(current_student, row_id):
    if _owned_row(current_student['id'], row_id) is None:
        return jsonify({"error": "Recurring transaction not found or unauthorized"}), 404

    data = request.get_json(silent=True) or {}
    clean, err = _validate_payload(data, partial=True)
    if err:
        return jsonify({"error": err}), 400
    if not clean:
        return jsonify({"error": "no fields to update"}), 400

    columns = {
        'label': 'label', 'merchant_name': 'merchant_name', 'amount': 'amount',
        'direction': 'direction', 'cadence': 'cadence',
        'day_of_month': 'day_of_month', 'weekday': 'weekday',
        'next_date': 'next_date', 'active': 'active',
    }
    sets, params = [], []
    for key, column in columns.items():
        if key in clean:
            sets.append(f"{column} = %s")
            params.append(clean[key])
    params.append(row_id)

    result = execute_query(
        f"UPDATE recurring_transactions SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
        commit=True,
    )
    if result is None:
        return jsonify({"error": "Failed to update recurring transaction"}), 500
    return jsonify(execute_query(RECURRING_SELECT, (row_id,), fetch_one=True))


@recurring_bp.route('/<int:row_id>', methods=['DELETE'])
@token_required
def delete_recurring(current_student, row_id):
    if _owned_row(current_student['id'], row_id) is None:
        return jsonify({"error": "Recurring transaction not found or unauthorized"}), 404
    result = execute_query(
        "DELETE FROM recurring_transactions WHERE id = %s", (row_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete recurring transaction"}), 500
    return jsonify({"message": "Recurring transaction deleted successfully"}), 200
