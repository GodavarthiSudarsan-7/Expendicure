import datetime
import json

from flask import Blueprint, Response, jsonify, request

from database import execute_query
from date_filters import month_bounds, format_year_month, parse_iso_date
from finance_db import get_repository
from middleware import token_required
from reports_export import (
    DEFAULT_PERIOD,
    PERIOD_PRESETS,
    build_financial_profile,
    render_markdown,
    resolve_period,
)

reports_bp = Blueprint('reports', __name__)


def _safe_filename(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "profile"))
    return keep.strip("-") or "profile"


@reports_bp.route('/financial-profile', methods=['GET'], strict_slashes=False)
@token_required
def financial_profile(current_student):
    """Portable, user-scoped financial profile export.

    Query params:
      period  one of 30d | 3m (default) | 6m | 12m | all | custom
      from,to YYYY-MM-DD, required when period=custom
      format  json (default) | markdown | pdf

    The report is always scoped to the authenticated account. It never contains
    raw SMS, passwords, session tokens, ingest tokens or full account numbers.
    """
    student_id = current_student['id']
    fmt = (request.args.get('format') or 'json').lower()
    if fmt not in ('json', 'markdown', 'md', 'text', 'pdf'):
        return jsonify({"error": "format must be json, markdown or pdf"}), 400

    preset = (request.args.get('period') or DEFAULT_PERIOD).lower()
    if preset not in PERIOD_PRESETS:
        return jsonify({"error": f"period must be one of: {', '.join(PERIOD_PRESETS)}"}), 400

    custom_from = custom_to = None
    if preset == 'custom':
        try:
            custom_from = parse_iso_date(request.args.get('from', ''))
            custom_to = parse_iso_date(request.args.get('to', ''))
        except ValueError:
            return jsonify({"error": "custom period requires valid 'from' and 'to' "
                                     "YYYY-MM-DD dates"}), 400

    as_of = datetime.date.today()

    earliest = None
    if preset == 'all':
        row = execute_query(
            "SELECT MIN(payment_date) AS first_date FROM transactions WHERE student_id = %s",
            (student_id,), fetch_one=True,
        )
        earliest = (row or {}).get('first_date')
        if isinstance(earliest, datetime.datetime):
            earliest = earliest.date()

    try:
        period = resolve_period(
            preset, as_of=as_of, custom_from=custom_from, custom_to=custom_to,
            earliest_txn=earliest,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    report = build_financial_profile(
        get_repository(),
        student_id,
        account_name=current_student.get('name'),
        period=period,
        as_of=as_of,
        generated_at=datetime.datetime.now().isoformat(timespec='seconds'),
    )

    stem = f"expendicure-financial-profile-{_safe_filename(current_student.get('name'))}-{period['to']}"

    if fmt in ('markdown', 'md', 'text'):
        body = render_markdown(report)
        return Response(
            body, mimetype='text/markdown; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
        )

    if fmt == 'pdf':
        try:
            from reports_export import render_pdf
            pdf_bytes = render_pdf(report)
        except Exception:  # fpdf2 missing or rendering issue — degrade, never 500
            body = render_markdown(report)
            return Response(
                body, mimetype='text/markdown; charset=utf-8',
                headers={
                    'Content-Disposition': f'attachment; filename="{stem}.md"',
                    'X-Report-Fallback': 'pdf-unavailable',
                },
            )
        return Response(
            pdf_bytes, mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{stem}.pdf"'},
        )

    # json (default) — pretty-printed so another tool / person can read it raw
    return Response(
        json.dumps(report, indent=2, ensure_ascii=False),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{stem}.json"'},
    )


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
