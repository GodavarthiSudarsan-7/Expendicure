"""Environment-driven configuration for the local AI layer.

Nothing secret lives here — only a base URL, a model name and a timeout.
"""

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class AIConfig:
    # Where the local Ollama daemon listens.
    BASE_URL = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    # Which local model to use (must be pulled by the operator, e.g. `ollama pull mistral`).
    MODEL = os.environ.get("OLLAMA_MODEL") or "mistral"
    # Per-request timeout, seconds.
    TIMEOUT_SECONDS = _int_env("OLLAMA_TIMEOUT_SECONDS", 60)
    # Provider label surfaced to the frontend.
    PROVIDER = "ollama"

    # Upper bound on a single /api/ai/generate prompt (defensive; user input is untrusted).
    MAX_PROMPT_CHARS = _int_env("AI_MAX_PROMPT_CHARS", 4000)

    @classmethod
    def as_public_dict(cls) -> dict:
        """Non-sensitive settings safe to return from a health endpoint."""
        return {"provider": cls.PROVIDER, "model": cls.MODEL, "base_url": cls.BASE_URL}
