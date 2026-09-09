"""A small, isolated client for a local Ollama daemon.

Responsibilities: health check, text generation, timeouts, connection-error and
malformed-response handling. Nothing else — no DB, no finance, no mutation.
``requests`` is used ONLY here (and in ``routes/ai.py``); never in ``finance/``.
"""

import json

import requests

from ai.config import AIConfig
from ai.prompts import SYSTEM_PROMPT


class OllamaError(Exception):
    """Base error for the AI layer."""


class OllamaUnavailable(OllamaError):
    """Ollama could not be reached / did not respond usefully."""


class OllamaClient:
    def __init__(self, config=AIConfig):
        self.base_url = config.BASE_URL
        self.model = config.MODEL
        self.timeout = config.TIMEOUT_SECONDS

    # ---------------------------------------------------------------- health
    def health(self) -> dict:
        """Return a dict describing whether the local model is usable.

        Never raises — a health check must not be able to break a caller.
        """
        info = {"available": False, "provider": AIConfig.PROVIDER, "model": self.model}
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=min(self.timeout, 5))
        except requests.exceptions.RequestException as exc:
            info["error"] = f"Local AI service unavailable ({type(exc).__name__})"
            return info

        if resp.status_code != 200:
            info["error"] = f"Local AI service returned HTTP {resp.status_code}"
            return info

        try:
            names = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
        except (ValueError, AttributeError, TypeError):
            info["error"] = "Local AI service returned an unreadable response"
            return info

        if self.model.split(":")[0] not in names:
            info["error"] = (
                f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"
            )
            return info

        info["available"] = True
        return info

    def is_available(self) -> bool:
        return bool(self.health().get("available"))

    # -------------------------------------------------------------- generate
    def generate(self, prompt: str, *, system: str = SYSTEM_PROMPT, format: str = None) -> str:
        """Generate a completion for ``prompt``.

        ``format="json"`` asks Ollama to constrain the output to a valid JSON
        value (used by the agent planner so weak local models still emit
        parseable plans).

        Raises ``OllamaUnavailable`` on any connection / timeout / malformed
        response so the caller can degrade gracefully.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if format:
            payload["format"] = format
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise OllamaUnavailable("Local AI request timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaUnavailable(
                f"Could not reach the local AI service ({type(exc).__name__})"
            ) from exc

        if resp.status_code == 404:
            raise OllamaUnavailable(
                f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"
            )
        if resp.status_code != 200:
            raise OllamaUnavailable(f"Local AI service returned HTTP {resp.status_code}")

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable("Local AI service returned invalid JSON") from exc

        text = (data or {}).get("response")
        if not isinstance(text, str) or not text.strip():
            raise OllamaUnavailable("Local AI service returned an empty response")
        return text.strip()
