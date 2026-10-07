"""POST /api/affordability/check — deterministic "Can I afford this?" for the
authenticated account.

TWO response shapes on ONE endpoint, chosen by the optional ``mode`` field:

  mode omitted / "affordability"  (DEFAULT, unchanged, backward compatible)
      the Phase-4 verdict from ``finance.affordability.check_affordability``.

  mode = "decision"
      the canonical Financial Decision object from
      ``decision.orchestrator.decide`` — amount_safe_to_pay, a proven payment
      plan, the earliest safe full-payment date, required spending changes,
      goal impact and structured explanation facts.

Deliberately NOT a second endpoint: the decision object is a richer answer to
the same question, so it lives on the same affordability resource.

This route does no financial arithmetic. It authenticates, validates input,
loads the Twin (+ history and goals for the decision mode), calls the engine,
and serialises the result.
"""

from datetime import timedelta

from flask import Blueprint, jsonify, request

from config import Config
from date_filters import parse_iso_date
from decimal import Decimal, InvalidOperation
from decision.orchestrator import DecisionRequest, decide
from decision.payment_plans import InstallmentOption
from decision.safety import SAFETY_HORIZON_DAYS
from finance.affordability import DEFAULT_HORIZON_DAYS, check_affordability
from finance.money import money
from finance.twin import build_twin_state
from finance_db import get_repository
from middleware import token_required

affordability_bp = Blueprint('affordability', __name__)

MAX_HORIZON_DAYS = 365
MODE_AFFORDABILITY = 'affordability'
MODE_DECISION = 'decision'
MODES = (MODE_AFFORDABILITY, MODE_DECISION)
#: history window handed to the decision engine for recurring detection
DECISION_HISTORY_DAYS = 180
MAX_INSTALLMENT_OPTIONS = 10


def _parse_installment_options(raw):
    """Validate caller-supplied payment options. Returns (options, error)."""
    if raw in (None, ''):
        return (), None
    if not isinstance(raw, list):
        return None, "installment_options must be a list"
    if len(raw) > MAX_INSTALLMENT_OPTIONS:
        return None, f"at most {MAX_INSTALLMENT_OPTIONS} installment_options are allowed"

    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"installment_options[{i}] must be an object"
        try:
            first = parse_iso_date(item['first_payment_date'])
        except (KeyError, ValueError, TypeError):
            return None, f"installment_options[{i}].first_payment_date must be YYYY-MM-DD"
        try:
            count = int(item['number_of_payments'])
            payment = money(str(item['payment_amount']))
            total = money(str(item['total_payable']))
            fee = money(str(item.get('fee', '0')))
            interval = item.get('interval_days')
            interval = int(interval) if interval not in (None, '') else None
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None, (f"installment_options[{i}] needs number_of_payments, "
                          f"payment_amount and total_payable")
        if count < 1 or count > 60:
            return None, f"installment_options[{i}].number_of_payments must be 1-60"
        if payment <= 0 or total <= 0 or fee < 0:
            return None, f"installment_options[{i}] amounts must be positive"
        if interval is not None and not (1 <= interval <= 365):
            return None, f"installment_options[{i}].interval_days must be 1-365"
        out.append(InstallmentOption(
            option_id=str(item.get('option_id') or f"option_{i + 1}"),
            first_payment_date=first, number_of_payments=count,
            payment_amount=payment, total_payable=total, fee=fee,
            interval_days=interval, label=str(item.get('label') or 'installment'),
        ))
    return tuple(out), None


@affordability_bp.route('/check', methods=['POST'], strict_slashes=False)
@token_required
def post_check(current_student):
    data = request.get_json(silent=True) or {}

    if data.get('amount') in (None, ''):
        return jsonify({"error": "amount is required"}), 400

    as_of = None
    if data.get('as_of'):
        try:
            as_of = parse_iso_date(data['as_of'])
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    purchase_date = None
    if data.get('date'):
        try:
            purchase_date = parse_iso_date(data['date'])
        except ValueError:
            return jsonify({"error": "date must be a valid YYYY-MM-DD date"}), 400

    horizon_days = data.get('horizon_days', DEFAULT_HORIZON_DAYS)
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    if not (0 <= horizon_days <= MAX_HORIZON_DAYS):
        return jsonify({"error": f"horizon_days must be between 0 and {MAX_HORIZON_DAYS}"}), 400

    mode = str(data.get('mode') or MODE_AFFORDABILITY).lower()
    if mode not in MODES:
        return jsonify({"error": f"mode must be one of: {', '.join(MODES)}"}), 400

    repo = get_repository()
    twin = build_twin_state(
        repo,
        current_student['id'],
        as_of=as_of,
        default_safety_buffer=Config.SAFETY_BUFFER,
    )

    if mode == MODE_DECISION:
        return _decision_response(repo, twin, data, purchase_date)

    try:
        result = check_affordability(
            twin,
            amount=data['amount'],
            category=data.get('category'),
            purchase_date=purchase_date,
            horizon_days=horizon_days,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result.to_dict())


def _decision_response(repo, twin, data, purchase_date):
    """Load the extra state the decision engine needs, call it, serialise.

    No arithmetic here — every figure in the response comes from
    ``decision.orchestrator.decide``.
    """
    options, err = _parse_installment_options(data.get('installment_options'))
    if err:
        return jsonify({"error": err}), 400

    deadline = None
    if data.get('desired_completion_date'):
        try:
            deadline = parse_iso_date(data['desired_completion_date'])
        except ValueError:
            return jsonify(
                {"error": "desired_completion_date must be a valid YYYY-MM-DD date"}), 400

    horizon = data.get('horizon_days', SAFETY_HORIZON_DAYS)
    try:
        horizon = int(horizon)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    if not (1 <= horizon <= MAX_HORIZON_DAYS):
        return jsonify(
            {"error": f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}"}), 400

    minimum_balance = None
    if data.get('minimum_balance') not in (None, ''):
        try:
            minimum_balance = money(str(data['minimum_balance']))
        except (ValueError, InvalidOperation):
            return jsonify({"error": "minimum_balance must be a number"}), 400
        if minimum_balance < 0:
            return jsonify({"error": "minimum_balance must not be negative"}), 400

    goal_id = data.get('goal_id')
    if goal_id not in (None, ''):
        try:
            goal_id = int(goal_id)
        except (TypeError, ValueError):
            return jsonify({"error": "goal_id must be an integer"}), 400
    else:
        goal_id = None

    try:
        amount = money(str(data['amount']))
    except (ValueError, InvalidOperation):
        return jsonify({"error": "amount must be a number"}), 400

    # history feeds recurring DETECTION inside the 90-day baseline; goals feed
    # goal impact. Both are read-only and scoped to this account.
    history = repo.get_transactions(
        twin.student_id,
        start=twin.as_of - timedelta(days=DECISION_HISTORY_DAYS),
        end=twin.as_of,
    )
    goals = repo.get_savings_goals(twin.student_id)

    request_obj = DecisionRequest(
        amount=amount,
        description=(str(data['description'])[:200] if data.get('description') else None),
        category=(str(data['category'])[:80] if data.get('category') else None),
        request_date=purchase_date,
        desired_completion_date=deadline,
        installment_options=options,
        goal_id=goal_id,
        horizon_days=horizon,
        minimum_balance=minimum_balance,
    )

    try:
        decision = decide(twin, request_obj, history=history, goals=goals)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(decision.to_dict())
