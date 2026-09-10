"""Per-account settings: opening balance, safety buffer, as-of date.

The live balance is never stored — it is derived by the finance repository
(opening_balance + credits - debits up to today).
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from config import Config
from database import execute_query
from date_filters import parse_iso_date
from finance.money import money
from finance_db import get_repository
from middleware import token_required

account_bp = Blueprint('account', __name__)


def _money_field(data, name):
    """Return (Decimal, None) or (None, error_message). Missing -> (None, None)."""
    if name not in data or data[name] in (None, ''):
        return None, None
    try:
        value = Decimal(str(data[name]))
    except (InvalidOperation, TypeError, ValueError):
        return None, f"{name} must be a number"
    if value.is_nan() or value.is_infinite():
        return None, f"{name} must be a finite number"
    if value < 0:
        return None, f"{name} must not be negative"
    return value, None


def _serialize(student_id):
    repo = get_repository()
    account = repo.get_account(student_id)
    if account is None:
        opening = Decimal('0.00')
        buffer_ = Config.SAFETY_BUFFER
        as_of = date.today()
        exists = False
    else:
        opening = account.opening_balance
        buffer_ = account.safety_buffer
        as_of = account.as_of_date
        exists = True

    current_balance = repo.compute_current_balance(student_id)
    return {
        "exists": exists,
        "opening_balance": str(money(opening)),
        "safety_buffer": str(money(buffer_)),
        "as_of_date": as_of.isoformat(),
        "current_balance": str(money(current_balance)),
    }


@account_bp.route('', methods=['GET'], strict_slashes=False)
@token_required
def get_account(current_student):
    return jsonify(_serialize(current_student['id']))


@account_bp.route('', methods=['PUT'], strict_slashes=False)
@token_required
def upsert_account(current_student):
    student_id = current_student['id']
    data = request.get_json(silent=True) or {}

    opening, err = _money_field(data, 'opening_balance')
    if err:
        return jsonify({"error": err}), 400
    buffer_, err = _money_field(data, 'safety_buffer')
    if err:
        return jsonify({"error": err}), 400

    as_of = None
    if data.get('as_of_date'):
        try:
            as_of = parse_iso_date(data['as_of_date'])
        except ValueError:
            return jsonify({"error": "as_of_date must be a valid YYYY-MM-DD date"}), 400

    existing = execute_query(
        "SELECT id FROM accounts WHERE student_id = %s", (student_id,), fetch_one=True
    )

    if existing is None:
        result = execute_query(
            "INSERT INTO accounts (student_id, opening_balance, safety_buffer, as_of_date) "
            "VALUES (%s, %s, %s, %s)",
            (
                student_id,
                str(opening if opening is not None else Decimal('0.00')),
                str(buffer_ if buffer_ is not None else Config.SAFETY_BUFFER),
                (as_of or date.today()).isoformat(),
            ),
            commit=True,
        )
        if result is None:
            return jsonify({"error": "Failed to create account"}), 500
    else:
        sets = []
        params = []
        if opening is not None:
            sets.append("opening_balance = %s")
            params.append(str(opening))
        if buffer_ is not None:
            sets.append("safety_buffer = %s")
            params.append(str(buffer_))
        if as_of is not None:
            sets.append("as_of_date = %s")
            params.append(as_of.isoformat())
        if not sets:
            return jsonify({"error": "no fields to update"}), 400
        params.append(student_id)
        result = execute_query(
            f"UPDATE accounts SET {', '.join(sets)} WHERE student_id = %s",
            tuple(params),
            commit=True,
        )
        if result is None:
            return jsonify({"error": "Failed to update account"}), 500

    return jsonify(_serialize(student_id))
