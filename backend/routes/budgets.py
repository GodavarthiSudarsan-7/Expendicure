from flask import Blueprint, jsonify, request
from database import execute_query
from middleware import token_required

budgets_bp = Blueprint('budgets', __name__)

@budgets_bp.route('/', methods=['GET'], strict_slashes=False)
@token_required
def get_budgets(current_student):
    student_id = current_student['id']
    month = request.args.get('month')  # Format: YYYY-MM
    
    query = """
        SELECT b.id, b.monthly_limit, b.month,
               c.name AS category_name, c.id AS category_id
        FROM budgets b
        JOIN categories c ON b.category_id = c.id
        WHERE b.student_id = %s
    """
    params = [student_id]
    
    if month:
        query += " AND b.month = %s"
        params.append(month)
    
    query += " ORDER BY c.name"
    
    budgets = execute_query(query, tuple(params), fetch_all=True)
    if budgets is None:
        return jsonify({"error": "Failed to fetch budgets"}), 500
    return jsonify(budgets)

@budgets_bp.route('/', methods=['POST'], strict_slashes=False)
@token_required
def add_or_update_budget(current_student):
    student_id = current_student['id']
    data = request.get_json()
    required_fields = ['category_id', 'monthly_limit', 'month']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} is required"}), 400
    
    # Check if budget already exists for this student/category/month
    check_query = """
        SELECT id FROM budgets 
        WHERE student_id = %s AND category_id = %s AND month = %s
    """
    existing = execute_query(check_query, (student_id, data['category_id'], data['month']), fetch_one=True)
    
    if existing:
        # Update existing budget
        update_query = """
            UPDATE budgets 
            SET monthly_limit = %s, updated_at = CURRENT_TIMESTAMP
            WHERE student_id = %s AND category_id = %s AND month = %s
        """
        params = (data['monthly_limit'], student_id, data['category_id'], data['month'])
        result = execute_query(update_query, params, commit=True)
        if result is None:
            return jsonify({"error": "Failed to update budget"}), 500
        
        # Fetch the updated budget
        budget = execute_query(
            """
            SELECT b.id, b.monthly_limit, b.month,
                   c.name AS category_name, c.id AS category_id
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE b.id = %s
            """,
            (existing['id'],),
            fetch_one=True
        )
        return jsonify(budget)
    else:
        # Add new budget
        insert_query = """
            INSERT INTO budgets (student_id, category_id, monthly_limit, month)
            VALUES (%s, %s, %s, %s)
        """
        params = (student_id, data['category_id'], data['monthly_limit'], data['month'])
        budget_id = execute_query(insert_query, params, commit=True)
        if budget_id is None:
            return jsonify({"error": "Failed to add budget"}), 500
        
        # Fetch the newly added budget
        budget = execute_query(
            """
            SELECT b.id, b.monthly_limit, b.month,
                   c.name AS category_name, c.id AS category_id
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE b.id = %s
            """,
            (budget_id,),
            fetch_one=True
        )
        return jsonify(budget), 201


@budgets_bp.route('/<int:budget_id>', methods=['DELETE'])
@token_required
def delete_budget(current_student, budget_id):
    student_id = current_student['id']

    existing = execute_query(
        "SELECT id FROM budgets WHERE id = %s AND student_id = %s",
        (budget_id, student_id),
        fetch_one=True,
    )
    if existing is None:
        return jsonify({"error": "Budget not found or unauthorized"}), 404

    result = execute_query(
        "DELETE FROM budgets WHERE id = %s", (budget_id,), commit=True
    )
    if result is None:
        return jsonify({"error": "Failed to delete budget"}), 500

    return jsonify({"message": "Budget deleted successfully"}), 200