"""POST /api/agent/chat — talk to Herman, the Financial Orchestrator Agent.

Read-only. The authenticated user's identity comes from ``token_required`` and
is NEVER taken from the request body. If the local model is offline, Herman
still replies gracefully (HTTP 200) and the rest of Expendicure is unaffected.
"""

from datetime import date

from flask import Blueprint, jsonify, request

from agent import Herman
from middleware import token_required

agent_bp = Blueprint("agent", __name__)
_herman = Herman()

MAX_MESSAGE_CHARS = 2000


@agent_bp.route("/chat", methods=["POST"], strict_slashes=False)
@token_required
def agent_chat(current_student):
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "message is required"}), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify({"error": f"message must be at most {MAX_MESSAGE_CHARS} characters"}), 400

    conversation_id = data.get("conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        conversation_id = None

    # Identity is server-side only. Any user_id in the body is ignored.
    response = _herman.process_message(
        current_student["id"],
        message,
        conversation_id=conversation_id,
        current_date=date.today(),
    )
    return jsonify(response.to_dict())
