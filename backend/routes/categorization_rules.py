"""CRUD for categorization rules (merchant text -> category).

A rule with student_id NULL is a global default (managed out-of-band, e.g. by a
seed migration). The API only ever creates/edits/deletes rules owned by the
calling student; global rules are read-only here.
"""

from flask import Blueprint, jsonify, request

from database import execute_query
from finance.models import MATCH_TYPES
from middleware import token_required

categorization_rules_bp = Blueprint('categorization_rules', __name__)

RULE_SELECT = (
    "SELECT id, student_id, match_type, pattern, category_id, priority, created_at "
    "FROM categorization_rules WHERE id = %s"
)


def _validate(data, *, partial=False):
    clean = {}

    if not partial or 'match_type' in data:
        match_type = (data.get('match_type') or 'contains').lower()
        if match_type not in MATCH_TYPES:
            return None, "match_type must be 'contains' or 'equals'"
        clean['match_type'] = match_type

    if not partial or 'pattern' in data:
        pattern = (data.get('pattern') or '').strip()
        if not pattern:
            return None, "pattern is required"
        if len(pattern) > 120:
            return None, "pattern must be at most 120 characters"
        clean['pattern'] = pattern

    if not partial or 'category_id' in data:
        try:
            clean['category_id'] = int(data['category_id'])
        except (KeyError, TypeError, ValueError):
            return None, "category_id must be an integer"

    if 'priority' in data and data['priority'] is not None:
        try:
            clean['priority'] = int(data['priority'])
        except (TypeError, ValueError):
            return None, "priority must be an integer"

    return clean, None


def _category_visible_to(student_id, category_id):
    return execute_query(
        "SELECT id FROM categories WHERE id = %s AND (student_id = %s OR student_id IS NULL)",
        (category_id, student_id),
        fetch_one=True,
    ) is not None


@categorization_rules_bp.route('', methods=['GET'], strict_slashes=False)
@token_required
def list_rules(current_student):
    rows = execute_query(
        "SELECT id, student_id, match_type, pattern, category_id, priority, created_at "
        "FROM categorization_rules "
        "WHERE student_id = %s OR student_id IS NULL "
        "ORDER BY priority, id",
        (current_student['id'],),
        fetch_all=True,
    )
    if rows is None:
        return jsonify({"error": "Failed to fetch rules"}), 500
    return jsonify(rows)


@categorization_rules_bp.route('', methods=['POST'], strict_slashes=False)
@token_required
def create_rule(current_student):
    data = request.get_json(silent=True) or {}
    clean, err = _validate(data, partial=False)
    if err:
        return jsonify({"error": err}), 400
    if not _category_visible_to(current_student['id'], clean['category_id']):
        return jsonify({"error": "category_id does not exist"}), 400

    row_id = execute_query(
        "INSERT INTO categorization_rules "
        "(student_id, match_type, pattern, category_id, priority) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            current_student['id'],
            clean['match_type'],
            clean['pattern'],
            clean['category_id'],
            clean.get('priority', 100),
        ),
        commit=True,
    )
    if row_id is None:
        return jsonify({"error": "Failed to create rule"}), 500
    return jsonify(execute_query(RULE_SELECT, (row_id,), fetch_one=True)), 201


def _owned_rule(student_id, rule_id):
    return execute_query(
        "SELECT id, student_id FROM categorization_rules WHERE id = %s",
        (rule_id,),
        fetch_one=True,
    )


@categorization_rules_bp.route('/<int:rule_id>', methods=['PUT'])
@token_required
def update_rule(current_student, rule_id):
    row = _owned_rule(current_student['id'], rule_id)
    if row is None:
        return jsonify({"error": "Rule not found"}), 404
    if row['student_id'] is None:
        return jsonify({"error": "Global rules cannot be modified"}), 403
    if row['student_id'] != current_student['id']:
        return jsonify({"error": "Not authorized for this rule"}), 403

    data = request.get_json(silent=True) or {}
    clean, err = _validate(data, partial=True)
    if err:
        return jsonify({"error": err}), 400
    if not clean:
        return jsonify({"error": "no fields to update"}), 400
    if 'category_id' in clean and not _category_visible_to(current_student['id'], clean['category_id']):
        return jsonify({"error": "category_id does not exist"}), 400

    columns = ['match_type', 'pattern', 'category_id', 'priority']
    sets, params = [], []
    for column in columns:
        if column in clean:
            sets.append(f"{column} = %s")
            params.append(clean[column])
    params.append(rule_id)

    result = execute_query(
        f"UPDATE categorization_rules SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
        commit=True,
    )
    if result is None:
        return jsonify({"error": "Failed to update rule"}), 500
    return jsonify(execute_query(RULE_SELECT, (rule_id,), fetch_one=True))


@categorization_rules_bp.route('/<int:rule_id>', methods=['DELETE'])
@token_required
def delete_rule(current_student, rule_id):
    row = _owned_rule(current_student['id'], rule_id)
    if row is None:
        return jsonify({"error": "Rule not found"}), 404
    if row['student_id'] is None:
        return jsonify({"error": "Global rules cannot be deleted"}), 403
    if row['student_id'] != current_student['id']:
        return jsonify({"error": "Not authorized for this rule"}), 403

    result = execute_query(
        "DELETE FROM categorization_rules WHERE id = %s", (rule_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete rule"}), 500
    return jsonify({"message": "Rule deleted successfully"}), 200
