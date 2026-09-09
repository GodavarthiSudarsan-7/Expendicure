from flask import Blueprint, jsonify, request
from database import execute_query
from middleware import token_required

categories_bp = Blueprint('categories', __name__)

CATEGORY_SELECT = "SELECT id, name, is_default, student_id, created_at FROM categories WHERE id = %s"


@categories_bp.route('/', methods=['GET'], strict_slashes=False)
@token_required
def get_categories(current_student):
    # Global default categories (student_id IS NULL) plus this student's own.
    query = (
        "SELECT id, name, is_default, student_id, created_at FROM categories "
        "WHERE student_id = %s OR student_id IS NULL "
        "ORDER BY name"
    )
    categories = execute_query(query, (current_student['id'],), fetch_all=True)
    if categories is None:
        return jsonify({"error": "Failed to fetch categories"}), 500
    return jsonify(categories)


@categories_bp.route('/', methods=['POST'], strict_slashes=False)
@token_required
def add_category(current_student):
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({"error": "name is required"}), 400
    name = str(data['name']).strip()
    student_id = current_student['id']

    # Reject a name that collides with a global category or one this student
    # already has.
    existing = execute_query(
        "SELECT id FROM categories "
        "WHERE name = %s AND (student_id = %s OR student_id IS NULL)",
        (name, student_id),
        fetch_one=True,
    )
    if existing:
        return jsonify({"error": "Category already exists"}), 409

    category_id = execute_query(
        "INSERT INTO categories (name, is_default, student_id) VALUES (%s, %s, %s)",
        (name, bool(data.get('is_default', False)), student_id),
        commit=True,
    )
    if category_id is None:
        return jsonify({"error": "Failed to add category"}), 500

    return jsonify(execute_query(CATEGORY_SELECT, (category_id,), fetch_one=True)), 201


@categories_bp.route('/<int:category_id>', methods=['PUT'])
@token_required
def update_category(current_student, category_id):
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({"error": "name is required"}), 400
    name = str(data['name']).strip()
    student_id = current_student['id']

    category = execute_query(
        "SELECT id, student_id FROM categories WHERE id = %s", (category_id,), fetch_one=True
    )
    if category is None:
        return jsonify({"error": "Category not found"}), 404
    if category['student_id'] is None:
        return jsonify({"error": "Global categories cannot be modified"}), 403
    if category['student_id'] != student_id:
        return jsonify({"error": "Not authorized for this category"}), 403

    clash = execute_query(
        "SELECT id FROM categories "
        "WHERE name = %s AND id != %s AND (student_id = %s OR student_id IS NULL)",
        (name, category_id, student_id),
        fetch_one=True,
    )
    if clash:
        return jsonify({"error": "Category name already exists"}), 409

    result = execute_query(
        "UPDATE categories SET name = %s WHERE id = %s", (name, category_id), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to update category"}), 500

    return jsonify(execute_query(CATEGORY_SELECT, (category_id,), fetch_one=True))


@categories_bp.route('/<int:category_id>', methods=['DELETE'])
@token_required
def delete_category(current_student, category_id):
    student_id = current_student['id']

    category = execute_query(
        "SELECT id, student_id, is_default FROM categories WHERE id = %s",
        (category_id,),
        fetch_one=True,
    )
    if category is None:
        return jsonify({"error": "Category not found"}), 404
    if category['student_id'] is None:
        return jsonify({"error": "Global categories cannot be deleted"}), 403
    if category['student_id'] != student_id:
        return jsonify({"error": "Not authorized for this category"}), 403

    usage = execute_query(
        "SELECT COUNT(*) AS count FROM transactions WHERE category_id = %s",
        (category_id,),
        fetch_one=True,
    )
    if usage and usage['count'] > 0:
        return jsonify({"error": "Cannot delete category that is being used in transactions"}), 400

    budget_usage = execute_query(
        "SELECT COUNT(*) AS count FROM budgets WHERE category_id = %s",
        (category_id,),
        fetch_one=True,
    )
    if budget_usage and budget_usage['count'] > 0:
        return jsonify({"error": "Cannot delete category that is being used in budgets"}), 400

    result = execute_query(
        "DELETE FROM categories WHERE id = %s", (category_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete category"}), 500

    return jsonify({"message": "Category deleted successfully"}), 200
