"""Local LLM integration layer (Phase 8).

This package is the ONLY place in the backend that talks to a language model.
It is an *explanation / interface* layer — never a financial calculator:

    Frontend -> Flask -> ai.ollama_client -> local Ollama model

Hard rules:
- Nothing here computes balances, affordability, forecasts or anomalies —
  those come from ``finance/`` (the deterministic source of truth).
- Nothing in ``finance/`` imports this package.
- If Ollama is missing / down / slow / broken, the rest of Expendicure keeps
  working; AI degrades gracefully.
"""

from ai.config import AIConfig
from ai.ollama_client import OllamaClient, OllamaError, OllamaUnavailable

__all__ = ["AIConfig", "OllamaClient", "OllamaError", "OllamaUnavailable"]
