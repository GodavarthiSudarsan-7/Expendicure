"""POST /api/agent/chat."""

import pytest

from tests.agent_helpers import FakeClient, plan_json, repo_factory
from agent import conversation as convo


@pytest.fixture(autouse=True)
def _reset():
    convo.reset()
    yield
    convo.reset()


@pytest.fixture
def herman_client(monkeypatch):
    """Swap the module-level Herman for one with a scripted fake model + fake repo."""
    from agent.orchestrator import Herman

    def make(scripts, available=True):
        h = Herman(client=FakeClient(scripts=scripts, available=available),
                   repo_factory=repo_factory())
        monkeypatch.setattr("routes.agent._herman", h)
        return h

    return make


def test_requires_auth(client):
    assert client.post("/api/agent/chat", json={"message": "hi"}).status_code == 401


def test_missing_message_is_400(client, auth_headers, herman_client):
    herman_client(["x"])
    assert client.post("/api/agent/chat", json={}, headers=auth_headers).status_code == 400
    assert client.post("/api/agent/chat", json={"message": "  "}, headers=auth_headers).status_code == 400


def test_oversized_message_is_400(client, auth_headers, herman_client):
    herman_client(["x"])
    big = "a" * 2001
    assert client.post("/api/agent/chat", json={"message": big}, headers=auth_headers).status_code == 400


def test_happy_path_affordability(client, auth_headers, herman_client):
    herman_client([
        plan_json("AFFORDABILITY", "check_affordability", {"amount": 2000, "merchant": "Amazon"}),
        "Yes — this looks safe.",
    ])
    r = client.post("/api/agent/chat", json={"message": "Can I spend 2000 on Amazon?"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"text", "intent", "tool_used", "data", "suggested_actions",
                         "conversation_id", "ai"}
    assert body["intent"] == "AFFORDABILITY"
    assert body["tool_used"] == "check_affordability"
    assert body["text"]
    assert body["conversation_id"]
    assert body["ai"]["available"] is True
    # never leak internals
    assert "system" not in body and "prompt" not in str(body).lower()


def test_body_user_id_is_ignored(client, auth_headers, herman_client):
    herman_client([plan_json("TWIN", "get_financial_twin", {}), "balance report"])
    r = client.post("/api/agent/chat",
                    json={"message": "status", "user_id": 999, "student_id": 999},
                    headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    # identity came from the token (user 1), not the body; the twin tool ran
    assert body["tool_used"] == "get_financial_twin"
    cb = body["data"].get("current_balance")
    assert isinstance(cb, str) and len(cb.split(".")[1]) == 2


def test_ai_failure_returns_200_graceful(client, auth_headers, herman_client):
    herman_client([], available=False)
    r = client.post("/api/agent/chat", json={"message": "can I afford a car?"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ai"]["available"] is False
    assert "offline" in body["text"].lower()
    assert body["tool_used"] is None


def test_conversation_continuity(client, auth_headers, herman_client):
    herman_client([
        plan_json("AFFORDABILITY", "check_affordability", {"amount": 3000}), "tight",
        plan_json("AFFORDABILITY", "check_affordability", {"amount": 2000}), "fine",
    ])
    r1 = client.post("/api/agent/chat", json={"message": "afford 3000?"}, headers=auth_headers).get_json()
    r2 = client.post("/api/agent/chat",
                     json={"message": "what if 2000", "conversation_id": r1["conversation_id"]},
                     headers=auth_headers).get_json()
    assert r2["conversation_id"] == r1["conversation_id"]
