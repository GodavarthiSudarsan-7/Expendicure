"""OllamaClient unit tests. All HTTP is mocked — no live Ollama, no network."""

import json

import pytest
import requests

from ai.config import AIConfig
from ai.ollama_client import OllamaClient, OllamaUnavailable


class FakeResp:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def client():
    return OllamaClient()


# ------------------------------------------------------------------- health

def test_health_available_when_model_present(client, monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: FakeResp(200, {"models": [{"name": f"{AIConfig.MODEL}:latest"}]}),
    )
    info = client.health()
    assert info["available"] is True
    assert info["provider"] == "ollama"
    assert info["model"] == AIConfig.MODEL
    assert "error" not in info


def test_health_unavailable_when_connection_refused(client, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(requests, "get", boom)
    info = client.health()
    assert info["available"] is False
    assert "unavailable" in info["error"].lower()


def test_health_reports_missing_model(client, monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: FakeResp(200, {"models": [{"name": "something-else"}]})
    )
    info = client.health()
    assert info["available"] is False
    assert "not installed" in info["error"]


def test_health_handles_non_200(client, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(500, {}))
    info = client.health()
    assert info["available"] is False
    assert "HTTP 500" in info["error"]


def test_health_handles_bad_json(client, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(200, raise_json=True))
    info = client.health()
    assert info["available"] is False


def test_health_returns_dict_on_every_request_failure(client, monkeypatch):
    for exc_cls in (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException):
        monkeypatch.setattr(requests, "get", lambda *a, exc=exc_cls, **k: (_ for _ in ()).throw(exc()))
        info = client.health()
        assert info["available"] is False and "error" in info


# ----------------------------------------------------------------- generate

def test_generate_returns_text(client, monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResp(200, {"response": "  hello there  "})
    )
    assert client.generate("hi") == "hello there"


def test_generate_sends_system_prompt(client, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResp(200, {"response": "ok"})

    monkeypatch.setattr(requests, "post", fake_post)
    client.generate("explain this")
    assert captured["json"]["system"]  # a non-empty system prompt is always sent
    assert captured["json"]["stream"] is False
    assert captured["json"]["model"] == AIConfig.MODEL


def test_generate_timeout_is_unavailable(client, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.Timeout()
    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(OllamaUnavailable):
        client.generate("hi")


def test_generate_connection_error_is_unavailable(client, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError()
    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(OllamaUnavailable):
        client.generate("hi")


def test_generate_404_reports_missing_model(client, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(404, {}))
    with pytest.raises(OllamaUnavailable) as exc:
        client.generate("hi")
    assert "not installed" in str(exc.value)


def test_generate_malformed_json_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(200, raise_json=True))
    with pytest.raises(OllamaUnavailable):
        client.generate("hi")


def test_generate_empty_response_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(200, {"response": "   "}))
    with pytest.raises(OllamaUnavailable):
        client.generate("hi")


def test_generate_rejects_empty_prompt(client):
    with pytest.raises(ValueError):
        client.generate("   ")
