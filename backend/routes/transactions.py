from flask import Blueprint, jsonify, request
from decimal import Decimal, InvalidOperation
from database import execute_query
from date_filters import parse_iso_date
from finance.models import DIRECTIONS, DEBIT
from middleware import token_required

transactions_bp = Blueprint('transactions', __name__)

TXN_SELECT = """
    SELECT t.id, t.amount, t.direction, t.merchant_name, t.payment_date,
           t.payment_method, t.notes, c.name AS category_name, t.category_id,
           t.created_at, t.updated_at
    FROM transactions t
    JOIN categories c ON t.category_id = c.id
    WHERE t.id = %s
"""


def _validate_amount(raw):
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None, "amount must be a number"
    if amount.is_nan() or amount.is_infinite():
        return None, "amount must be a finite number"
    if amount <= 0:
        return None, "amount must be greater than 0"
    return amount, None


def _category_exists(category_id):
    return execute_query(
        "SELECT id FROM categories WHERE id = %s", (category_id,), fetch_one=True
    ) is not None


@transactions_bp.route('/', methods=['GET'], strict_slashes=False)
@token_required
def get_transactions(current_student):
    student_id = current_student['id']

    query = """
        SELECT t.id, t.amount, t.direction, t.merchant_name, t.payment_date,
               t.payment_method, t.notes, c.name AS category_name, t.category_id,
               t.created_at, t.updated_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.student_id = %s
        ORDER BY t.payment_date DESC, t.created_at DESC
    """
    transactions = execute_query(query, (student_id,), fetch_all=True)
    if transactions is None:
        return jsonify({"error": "Failed to fetch transactions"}), 500
    return jsonify(transactions)


@transactions_bp.route('/', methods=['POST'], strict_slashes=False)
@token_required
def add_transaction(current_student):
    student_id = current_student['id']
    data = request.get_json(silent=True) or {}
    required_fields = ['amount', 'merchant_name', 'category_id', 'payment_date']
    for field in required_fields:
        if data.get(field) in (None, ''):
            return jsonify({"error": f"{field} is required"}), 400

    amount, err = _validate_amount(data['amount'])
    if err:
        return jsonify({"error": err}), 400

    direction = (data.get('direction') or DEBIT).lower()
    if direction not in DIRECTIONS:
        return jsonify({"error": "direction must be 'debit' or 'credit'"}), 400

    try:
        parse_iso_date(data['payment_date'])
    except ValueError:
        return jsonify({"error": "payment_date must be a valid YYYY-MM-DD date"}), 400

    if not _category_exists(data['category_id']):
        return jsonify({"error": "category_id does not exist"}), 400

    query = """
        INSERT INTO transactions
            (student_id, amount, direction, merchant_name, category_id,
             payment_date, payment_method, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        student_id,
        str(amount),
        direction,
        data['merchant_name'],
        data['category_id'],
        data['payment_date'],
        data.get('payment_method'),
        data.get('notes'),
    )
    transaction_id = execute_query(query, params, commit=True)
    if transaction_id is None:
        return jsonify({"error": "Failed to add transaction"}), 500

    new_transaction = execute_query(TXN_SELECT, (transaction_id,), fetch_one=True)
    return jsonify(new_transaction), 201


@transactions_bp.route('/<int:transaction_id>', methods=['PUT'])
@token_required
def update_transaction_category(current_student, transaction_id):
    student_id = current_student['id']
    data = request.get_json(silent=True) or {}
    if data.get('category_id') in (None, ''):
        return jsonify({"error": "category_id is required"}), 400

    if not _category_exists(data['category_id']):
        return jsonify({"error": "category_id does not exist"}), 400

    transaction = execute_query(
        "SELECT id FROM transactions WHERE id = %s AND student_id = %s",
        (transaction_id, student_id),
        fetch_one=True,
    )
    if transaction is None:
        return jsonify({"error": "Transaction not found or unauthorized"}), 404

    result = execute_query(
        "UPDATE transactions SET category_id = %s WHERE id = %s",
        (data['category_id'], transaction_id),
        commit=True,
    )
    if result is None:
        return jsonify({"error": "Failed to update transaction"}), 500

    updated_transaction = execute_query(TXN_SELECT, (transaction_id,), fetch_one=True)
    return jsonify(updated_transaction)


@transactions_bp.route('/<int:transaction_id>', methods=['DELETE'])
@token_required
def delete_transaction(current_student, transaction_id):
    student_id = current_student['id']
    transaction = execute_query(
        "SELECT id FROM transactions WHERE id = %s AND student_id = %s",
        (transaction_id, student_id),
        fetch_one=True,
    )
    if transaction is None:
        return jsonify({"error": "Transaction not found or unauthorized"}), 404

    result = execute_query(
        "DELETE FROM transactions WHERE id = %s", (transaction_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete transaction"}), 500

    return jsonify({"message": "Transaction deleted successfully"}), 200
