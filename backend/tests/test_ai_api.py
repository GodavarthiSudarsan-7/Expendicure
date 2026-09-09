"""/api/ai/* endpoint tests. Ollama is mocked; no live model, no network."""

import pytest

from ai.ollama_client import OllamaUnavailable


def test_health_available(client, monkeypatch):
    monkeypatch.setattr(
        "routes.ai._client.health",
        lambda: {"available": True, "provider": "ollama", "model": "mistral"},
    )
    r = client.get("/api/ai/health")
    assert r.status_code == 200
    assert r.get_json()["available"] is True


def test_health_unavailable_returns_503_not_crash(client, monkeypatch):
    monkeypatch.setattr(
        "routes.ai._client.health",
        lambda: {"available": False, "provider": "ollama", "model": "mistral",
                 "error": "Local AI service unavailable"},
    )
    r = client.get("/api/ai/health")
    assert r.status_code == 503
    body = r.get_json()
    assert body["available"] is False and body["error"]


def test_health_needs_no_auth(client, monkeypatch):
    monkeypatch.setattr("routes.ai._client.health", lambda: {"available": False})
    assert client.get("/api/ai/health").status_code in (200, 503)


def test_generate_requires_auth(client):
    assert client.post("/api/ai/generate", json={"prompt": "hi"}).status_code == 401


def test_generate_requires_prompt(client, auth_headers):
    assert client.post("/api/ai/generate", json={}, headers=auth_headers).status_code == 400
    assert client.post("/api/ai/generate", json={"prompt": "  "}, headers=auth_headers).status_code == 400


def test_generate_rejects_oversized_prompt(client, auth_headers):
    from ai.config import AIConfig
    big = "x" * (AIConfig.MAX_PROMPT_CHARS + 1)
    assert client.post("/api/ai/generate", json={"prompt": big}, headers=auth_headers).status_code == 400


def test_generate_happy_path(client, auth_headers, monkeypatch):
    monkeypatch.setattr("routes.ai._client.generate", lambda prompt, **kw: "explained.")
    r = client.post("/api/ai/generate", json={"prompt": "explain X"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body["text"] == "explained." and body["model"]


def test_generate_degrades_to_503_when_ollama_down(client, auth_headers, monkeypatch):
    def boom(prompt, **kw):
        raise OllamaUnavailable("Could not reach the local AI service")
    monkeypatch.setattr("routes.ai._client.generate", boom)
    r = client.post("/api/ai/generate", json={"prompt": "hi"}, headers=auth_headers)
    assert r.status_code == 503
    body = r.get_json()
    assert "error" in body and "reach" in body["error"].lower()
    # never leaks a stack trace
    assert "Traceback" not in str(body)


def test_generate_never_500s_on_ai_failure(client, auth_headers, monkeypatch):
    def boom(prompt, **kw):
        raise OllamaUnavailable("timeout")
    monkeypatch.setattr("routes.ai._client.generate", boom)
    r = client.post("/api/ai/generate", json={"prompt": "hi"}, headers=auth_headers)
    assert r.status_code != 500
