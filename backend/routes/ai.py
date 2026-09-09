"""Phase 8 AI infrastructure endpoints.

  GET  /api/ai/health    - is the local model usable? (no auth; never crashes)
  POST /api/ai/generate  - controlled generic text generation (auth required)

This is NOT the Financial Agent. It injects no financial data, calls no
deterministic tools, and does no tool-calling. It exists so Phase 9 has a
working local-LLM substrate to build on.
"""

from flask import Blueprint, jsonify, request

from ai.config import AIConfig
from ai.ollama_client import OllamaClient, OllamaError
from middleware import token_required

ai_bp = Blueprint("ai", __name__)
_client = OllamaClient()


@ai_bp.route("/health", methods=["GET"], strict_slashes=False)
def ai_health():
    info = _client.health()  # never raises
    status = 200 if info.get("available") else 503
    return jsonify(info), status


@ai_bp.route("/generate", methods=["POST"], strict_slashes=False)
@token_required
def ai_generate(current_student):
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"error": "prompt is required"}), 400
    if len(prompt) > AIConfig.MAX_PROMPT_CHARS:
        return jsonify({
            "error": f"prompt must be at most {AIConfig.MAX_PROMPT_CHARS} characters"
        }), 400

    try:
        text = _client.generate(prompt)
    except OllamaError as exc:
        # Graceful degradation: a clear 503, never a stack trace.
        return jsonify({
            "error": str(exc),
            "provider": AIConfig.PROVIDER,
            "model": AIConfig.MODEL,
        }), 503

    return jsonify({"text": text, "model": AIConfig.MODEL})
