from flask import Blueprint, jsonify
import datetime
from database import execute_query
from date_filters import month_bounds
from finance_db import get_repository
from middleware import token_required

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/summary', methods=['GET'])
@token_required
def get_dashboard_summary(current_student):
    student_id = current_student['id']

    current_month = datetime.datetime.now().strftime('%Y-%m')
    month_start, month_end = month_bounds(current_month)

    # Total spending for the current month.
    monthly_spending_result = execute_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS total_spent
        FROM transactions
        WHERE student_id = %s AND payment_date >= %s AND payment_date < %s
        """,
        (student_id, month_start, month_end),
        fetch_one=True,
    )
    total_monthly_spending = (monthly_spending_result or {}).get('total_spent') or 0

    # Sum of all category budgets set for the current month.
    total_budget_result = execute_query(
        """
        SELECT COALESCE(SUM(monthly_limit), 0) AS total_budget
        FROM budgets
        WHERE student_id = %s AND month = %s
        """,
        (student_id, current_month),
        fetch_one=True,
    )
    total_budget = (total_budget_result or {}).get('total_budget') or 0

    total_monthly_spending = float(total_monthly_spending)
    total_budget = float(total_budget)
    remaining_budget = (total_budget - total_monthly_spending) if total_budget > 0 else 0.0

    # Real balance: opening_balance + credits - debits, from the deterministic
    # finance repository. 0.00 when the student has no account and no income.
    total_balance = float(get_repository().compute_current_balance(student_id))

    recent_transactions = execute_query(
        """
        SELECT t.id, t.amount, t.merchant_name, t.payment_date, t.payment_method, t.notes,
               c.name AS category_name
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.student_id = %s
        ORDER BY t.payment_date DESC, t.created_at DESC
        LIMIT 5
        """,
        (student_id,),
        fetch_all=True,
    )

    category_summary = execute_query(
        """
        SELECT c.name AS category_name,
               COALESCE(SUM(t.amount), 0) AS spent,
               COALESCE(b.monthly_limit, 0) AS budget
        FROM categories c
        LEFT JOIN transactions t
               ON c.id = t.category_id
              AND t.student_id = %s
              AND t.payment_date >= %s
              AND t.payment_date < %s
        LEFT JOIN budgets b
               ON c.id = b.category_id
              AND b.student_id = %s
              AND b.month = %s
        GROUP BY c.id, c.name, b.monthly_limit
        ORDER BY c.name
        """,
        (student_id, month_start, month_end, student_id, current_month),
        fetch_all=True,
    )

    response = {
        "total_balance": total_balance,
        "total_monthly_spending": total_monthly_spending,
        "remaining_budget": remaining_budget,
        "recent_transactions": recent_transactions or [],
        "category_wise_summary": [
            {
                "category": item['category_name'],
                "spent": float(item['spent']),
                "budget": float(item['budget']),
                "remaining": float(item['budget'] - item['spent']) if item['budget'] > 0 else 0,
            }
            for item in (category_summary or [])
        ],
    }

    return jsonify(response)
