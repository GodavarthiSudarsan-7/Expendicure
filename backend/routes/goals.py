"""CRUD for a student's savings goals (Phase 13).

Ownership is enforced on every row: the authenticated student id comes from
``token_required`` and is never taken from the request body. A goal that
belongs to another student is a 404 for everyone else — it is never returned,
updated, or deleted across users.

The goal-progress / goal-impact / recovery engines only READ these rows; the
agent never writes here.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from database import execute_query
from date_filters import parse_iso_date
from finance.models import GOAL_STATUSES, GOAL_ACTIVE, GOAL_ARCHIVED
from middleware import token_required

goals_bp = Blueprint("goals", __name__)

GOAL_SELECT = (
    "SELECT id, student_id, name, target_amount, current_amount, "
    "monthly_contribution, target_date, status, created_at, updated_at "
    "FROM savings_goals WHERE id = %s"
)


def _money(value, field, *, allow_zero=True):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, f"{field} must be a number"
    if amount.is_nan() or amount.is_infinite():
        return None, f"{field} must be a finite number"
    if amount < 0 or (amount == 0 and not allow_zero):
        return None, f"{field} must be {'zero or more' if allow_zero else 'greater than 0'}"
    return amount, None


def _validate(data, *, partial=False):
    """Return (clean, None) or (None, error). ``partial`` allows a subset (PUT)."""
    clean = {}

    def has(name):
        return name in data and data[name] is not None

    if not partial or has("name"):
        name = str(data.get("name") or "").strip()
        if not name:
            return None, "name is required"
        clean["name"] = name[:120]

    if not partial or has("target_amount"):
        amount, err = _money(data.get("target_amount"), "target_amount", allow_zero=False)
        if err:
            return None, err
        clean["target_amount"] = amount

    if not partial or has("current_amount"):
        amount, err = _money(data.get("current_amount", 0), "current_amount")
        if err:
            return None, err
        clean["current_amount"] = amount

    if not partial or has("monthly_contribution"):
        amount, err = _money(data.get("monthly_contribution", 0), "monthly_contribution")
        if err:
            return None, err
        clean["monthly_contribution"] = amount

    if not partial or has("target_date"):
        try:
            clean["target_date"] = parse_iso_date(data["target_date"]).isoformat()
        except (ValueError, KeyError, TypeError):
            return None, "target_date must be a valid YYYY-MM-DD date"

    if has("status"):
        status = str(data["status"]).strip().lower()
        if status not in GOAL_STATUSES:
            return None, f"status must be one of {', '.join(GOAL_STATUSES)}"
        clean["status"] = status

    return clean, None


def _cross_field_ok(target_amount, current_amount):
    """No overfunding: current_amount must not exceed target_amount."""
    if target_amount is not None and current_amount is not None and current_amount > target_amount:
        return "current_amount must not exceed target_amount"
    return None


def _owned(student_id, goal_id):
    return execute_query(
        "SELECT id, target_amount, current_amount FROM savings_goals "
        "WHERE id = %s AND student_id = %s",
        (goal_id, student_id),
        fetch_one=True,
    )


@goals_bp.route("", methods=["GET"], strict_slashes=False)
@token_required
def list_goals(current_student):
    status = request.args.get("status")
    sql = GOAL_SELECT.replace("WHERE id = %s", "WHERE student_id = %s")
    params = [current_student["id"]]
    if status:
        if status.lower() not in GOAL_STATUSES:
            return jsonify({"error": "invalid status filter"}), 400
        sql += " AND status = %s"
        params.append(status.lower())
    sql += " ORDER BY target_date, id"
    rows = execute_query(sql, tuple(params), fetch_all=True)
    if rows is None:
        return jsonify({"error": "Failed to fetch goals"}), 500
    return jsonify(rows)


@goals_bp.route("/<int:goal_id>", methods=["GET"])
@token_required
def get_goal(current_student, goal_id):
    if _owned(current_student["id"], goal_id) is None:
        return jsonify({"error": "Goal not found or unauthorized"}), 404
    return jsonify(execute_query(GOAL_SELECT, (goal_id,), fetch_one=True))


@goals_bp.route("", methods=["POST"], strict_slashes=False)
@token_required
def create_goal(current_student):
    data = request.get_json(silent=True) or {}
    clean, err = _validate(data, partial=False)
    if err:
        return jsonify({"error": err}), 400
    err = _cross_field_ok(clean["target_amount"], clean["current_amount"])
    if err:
        return jsonify({"error": err}), 400

    new_id = execute_query(
        "INSERT INTO savings_goals "
        "(student_id, name, target_amount, current_amount, monthly_contribution, "
        " target_date, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            current_student["id"], clean["name"], str(clean["target_amount"]),
            str(clean["current_amount"]), str(clean["monthly_contribution"]),
            clean["target_date"], clean.get("status", GOAL_ACTIVE),
        ),
        commit=True,
    )
    if new_id is None:
        return jsonify({"error": "Failed to create goal"}), 500
    return jsonify(execute_query(GOAL_SELECT, (new_id,), fetch_one=True)), 201


@goals_bp.route("/<int:goal_id>", methods=["PUT"])
@token_required
def update_goal(current_student, goal_id):
    owned = _owned(current_student["id"], goal_id)
    if owned is None:
        return jsonify({"error": "Goal not found or unauthorized"}), 404

    data = request.get_json(silent=True) or {}
    clean, err = _validate(data, partial=True)
    if err:
        return jsonify({"error": err}), 400
    if not clean:
        return jsonify({"error": "no fields to update"}), 400

    target = clean.get("target_amount", Decimal(str(owned["target_amount"])))
    current = clean.get("current_amount", Decimal(str(owned["current_amount"])))
    err = _cross_field_ok(target, current)
    if err:
        return jsonify({"error": err}), 400

    columns = {
        "name": "name", "target_amount": "target_amount",
        "current_amount": "current_amount", "monthly_contribution": "monthly_contribution",
        "target_date": "target_date", "status": "status",
    }
    sets, params = [], []
    for key, column in columns.items():
        if key in clean:
            sets.append(f"{column} = %s")
            params.append(str(clean[key]) if isinstance(clean[key], Decimal) else clean[key])
    params.append(goal_id)

    result = execute_query(
        f"UPDATE savings_goals SET {', '.join(sets)} WHERE id = %s",
        tuple(params), commit=True,
    )
    if result is None:
        return jsonify({"error": "Failed to update goal"}), 500
    return jsonify(execute_query(GOAL_SELECT, (goal_id,), fetch_one=True))


@goals_bp.route("/<int:goal_id>", methods=["DELETE"])
@token_required
def delete_goal(current_student, goal_id):
    if _owned(current_student["id"], goal_id) is None:
        return jsonify({"error": "Goal not found or unauthorized"}), 404

    archive = request.args.get("archive") in ("1", "true", "yes")
    if archive:
        result = execute_query(
            "UPDATE savings_goals SET status = %s WHERE id = %s",
            (GOAL_ARCHIVED, goal_id), commit=True,
        )
        if result is None:
            return jsonify({"error": "Failed to archive goal"}), 500
        return jsonify({"message": "Goal archived", "goal": execute_query(
            GOAL_SELECT, (goal_id,), fetch_one=True)}), 200

    result = execute_query(
        "DELETE FROM savings_goals WHERE id = %s", (goal_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete goal"}), 500
    return jsonify({"message": "Goal deleted successfully"}), 200
