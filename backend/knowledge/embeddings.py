"""Local text embeddings via Ollama.

``requests`` is used here (this is the knowledge/AI support layer, like
``ai/``). The deterministic finance engine does NOT depend on this — if Ollama
or the embedding model is unavailable, ``embed_texts`` returns ``None`` and the
retriever falls back to keyword matching.
"""

import os

import requests

EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text"
_BASE_URL = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
_TIMEOUT = 20


def model_name() -> str:
    return EMBED_MODEL


def embed_texts(texts):
    """Return ``[[float, ...], ...]`` (one vector per text) or ``None`` on any failure."""
    if not texts:
        return []
    vectors = []
    try:
        for t in texts:
            resp = requests.post(
                f"{_BASE_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": str(t)[:4000]},
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            vec = data.get("embedding")
            if not isinstance(vec, list) or not vec:
                return None
            vectors.append([float(x) for x in vec])
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return None
    return vectors


def embed_one(text):
    out = embed_texts([text])
    return out[0] if out else None
