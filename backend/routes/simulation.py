"""POST /api/simulation/what-if — deterministic, in-memory what-if simulation.

Read-only with respect to the database: the twin is built from repository
reads, ``finance.simulate.simulate`` holds no connection and no write path,
and nothing is persisted. The future Phase 9 agent calls the same
``simulate`` function in-process via the tool registry.
"""

from flask import Blueprint, jsonify, request

from config import Config
from date_filters import parse_iso_date
from finance.simulate import DEFAULT_HORIZON_DAYS, MAX_HORIZON_DAYS, simulate
from finance.twin import build_twin_state
from finance_db import get_repository
from middleware import token_required

simulation_bp = Blueprint('simulation', __name__)


@simulation_bp.route('/what-if', methods=['POST'], strict_slashes=False)
@token_required
def post_what_if(current_student):
    data = request.get_json(silent=True) or {}

    as_of = None
    if data.get('as_of'):
        try:
            as_of = parse_iso_date(data['as_of'])
        except ValueError:
            return jsonify({"error": "as_of must be a valid YYYY-MM-DD date"}), 400

    horizon_days = data.get('horizon_days', DEFAULT_HORIZON_DAYS)
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, (int, str)):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError):
        return jsonify({"error": "horizon_days must be an integer"}), 400
    if not (0 <= horizon_days <= MAX_HORIZON_DAYS):
        return jsonify({"error": f"horizon_days must be between 0 and {MAX_HORIZON_DAYS}"}), 400

    # The scenario is the request body minus the transport-only fields.
    scenario = {k: v for k, v in data.items() if k not in ("as_of", "horizon_days")}
    if not scenario.get("type"):
        return jsonify({"error": "type is required"}), 400

    twin = build_twin_state(
        get_repository(),
        current_student['id'],
        as_of=as_of,
        default_safety_buffer=Config.SAFETY_BUFFER,
    )

    try:
        result = simulate(twin, scenario, horizon_days=horizon_days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result.to_dict())
