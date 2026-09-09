from flask import Blueprint, jsonify, request
from database import execute_query
import datetime
from date_filters import month_bounds, format_year_month
from middleware import token_required

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/chart-data', methods=['GET'])
@token_required
def get_chart_data(current_student):
    student_id = current_student['id']
    category = request.args.get('category')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    month = request.args.get('month')  # Format: YYYY-MM

    month_start = month_end = None
    if month:
        try:
            month_start, month_end = month_bounds(month)
        except ValueError:
            return jsonify({"error": "month must be in YYYY-MM format"}), 400

    def apply_filters(query, params):
        if category:
            query += " AND c.name = %s"
            params.append(category)
        if start_date:
            query += " AND t.payment_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND t.payment_date <= %s"
            params.append(end_date)
        if month_start is not None:
            query += " AND t.payment_date >= %s AND t.payment_date < %s"
            params.append(month_start)
            params.append(month_end)
        return query, params

    # Filtered transaction list (also feeds the table).
    base_query = """
        SELECT t.id, t.amount, t.merchant_name, t.payment_date, t.payment_method, t.notes,
               c.name AS category_name, c.id AS category_id
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.student_id = %s
    """
    base_query, base_params = apply_filters(base_query, [student_id])
    base_query += " ORDER BY t.payment_date DESC"

    transactions = execute_query(base_query, tuple(base_params), fetch_all=True)
    if transactions is None:
        return jsonify({"error": "Failed to fetch transactions"}), 500

    # Pie chart: category-wise spend for the filtered period.
    pie_query = """
        SELECT c.name AS category_name,
               COALESCE(SUM(t.amount), 0) AS total_spent
        FROM categories c
        LEFT JOIN transactions t
               ON c.id = t.category_id
              AND t.student_id = %s
    """
    pie_query, pie_params = apply_filters(pie_query, [student_id])
    pie_query += " GROUP BY c.id, c.name ORDER BY total_spent DESC"

    pie_data = execute_query(pie_query, tuple(pie_params), fetch_all=True)
    if pie_data is None:
        return jsonify({"error": "Failed to fetch pie chart data"}), 500

    # Bar chart: last 6 months of spending. Group by numeric year/month so the
    # query carries no literal '%' for the driver to misread.
    bar_query = """
        SELECT YEAR(t.payment_date) AS y, MONTH(t.payment_date) AS m,
               COALESCE(SUM(t.amount), 0) AS total_spent
        FROM transactions t
        WHERE t.student_id = %s
    """
    bar_params = [student_id]
    if category:
        bar_query += " AND t.category_id = (SELECT id FROM categories WHERE name = %s)"
        bar_params.append(category)
    bar_query += " GROUP BY y, m ORDER BY y DESC, m DESC LIMIT 6"

    bar_data = execute_query(bar_query, tuple(bar_params), fetch_all=True)
    if bar_data is None:
        return jsonify({"error": "Failed to fetch bar chart data"}), 500

    bar_points = [
        {"month": format_year_month(row['y'], row['m']), "value": float(row['total_spent'])}
        for row in reversed(bar_data or [])
    ]

    response = {
        "pie_chart": [
            {"name": item['category_name'], "value": float(item['total_spent'])}
            for item in (pie_data or [])
        ],
        "bar_chart": bar_points,
        "recent_transactions": [
            {
                "id": t['id'],
                "amount": float(t['amount']),
                "merchant_name": t['merchant_name'],
                "category": t['category_name'],
                "payment_date": t['payment_date'].strftime('%Y-%m-%d')
                if isinstance(t['payment_date'], datetime.date) else t['payment_date'],
                "payment_method": t['payment_method'],
                "notes": t['notes'],
            }
            for t in (transactions or [])
        ],
    }

    return jsonify(response)
