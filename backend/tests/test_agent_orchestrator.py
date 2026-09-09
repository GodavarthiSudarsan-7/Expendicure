"""Herman.process_message — the full loop, per intent + edge cases."""

from datetime import date

import pytest

from tests.agent_helpers import AS_OF, FakeClient, FakeRepo, plan_json, repo_factory
from agent import conversation as convo
from agent.orchestrator import Herman

WHEN = date(2026, 9, 30)


@pytest.fixture(autouse=True)
def _reset_convos():
    convo.reset()
    yield
    convo.reset()


def herman(planner_json, responder_text="Here's the answer.", *, available=True, repo=None):
    client = FakeClient(scripts=[planner_json, responder_text], available=available)
    return Herman(client=client, repo_factory=repo_factory(repo)), client


# ------------------------------------------------------------ e2e (the demo)
def test_end_to_end_affordability_amazon_2000():
    h, client = herman(plan_json("AFFORDABILITY", "check_affordability",
                                 {"amount": 2000, "merchant": "Amazon"}),
                       "Yes — this looks safe. Your projected low point stays above your buffer.")
    r = h.process_message(1, "Herman, can I spend ₹2000 on Amazon?", current_date=WHEN)
    assert r.intent == "AFFORDABILITY"
    assert r.tool_used == "check_affordability"
    assert r.data["verdict"] in {"affordable", "tight", "not_affordable"}
    assert r.data["merchant"] == "Amazon"
    assert r.text and "safe" in r.text.lower()
    assert r.suggested_actions
    assert r.ai["available"] is True
    # exactly 2 model calls: planner + responder
    assert len(client.calls) == 2


def test_what_if_flow():
    h, _ = herman(plan_json("WHAT_IF", "simulate_expense", {"amount": 5000}),
                  "In that scenario your end balance drops by ₹5,000.")
    r = h.process_message(1, "what if I spend 5000?", current_date=WHEN)
    assert r.intent == "WHAT_IF" and r.tool_used == "simulate_expense"
    assert "comparison" in r.data


def test_forecast_flow():
    h, _ = herman(plan_json("FORECAST", "get_cashflow_forecast", {"horizon": 30}),
                  "Over the next 30 days you're projected to end around a healthy level.")
    r = h.process_message(1, "what will my money look like at month end?", current_date=WHEN)
    assert r.intent == "FORECAST" and r.tool_used == "get_cashflow_forecast"
    assert "projection" in r.data


def test_anomaly_flow():
    h, _ = herman(plan_json("ANOMALY", "get_financial_anomalies", {"history_days": 90}),
                  "A couple of things stood out this month.")
    r = h.process_message(1, "anything unusual?", current_date=WHEN)
    assert r.intent == "ANOMALY" and r.tool_used == "get_financial_anomalies"


def test_transaction_query_flow():
    h, _ = herman(plan_json("TRANSACTION_QUERY", "get_transactions", {"direction": "credit"}),
                  "You have one credit: a scholarship.")
    r = h.process_message(1, "show my income transactions", current_date=WHEN)
    assert r.tool_used == "get_transactions" and r.data["count"] == 1


def test_budget_query_flow():
    h, _ = herman(plan_json("BUDGET_QUERY", "get_budget_status", {}),
                  "You're within budget on Food.")
    r = h.process_message(1, "how are my budgets?", current_date=WHEN)
    assert r.tool_used == "get_budget_status" and "categories" in r.data


def test_general_question_no_tool():
    h, _ = herman(plan_json("GENERAL", None, {}), "I can help you weigh money decisions.")
    r = h.process_message(1, "what can you do?", current_date=WHEN)
    assert r.intent == "GENERAL" and r.tool_used is None and r.data == {}
    assert r.text


def test_follow_up_uses_previous_tool_context():
    client = FakeClient(scripts=[
        plan_json("AFFORDABILITY", "check_affordability", {"amount": 3000, "merchant": "headphones"}),
        "That would be tight.",
        # planner for the follow-up: merges previous args, changes amount
        plan_json("AFFORDABILITY", "check_affordability", {"amount": 2000, "merchant": "headphones"}),
        "₹2,000 is comfortable.",
    ])
    h = Herman(client=client, repo_factory=repo_factory())
    r1 = h.process_message(1, "Can I spend ₹3000 on headphones?", current_date=WHEN)
    cid = r1.conversation_id
    r2 = h.process_message(1, "What if it's ₹2000?", conversation_id=cid, current_date=WHEN)
    assert r2.conversation_id == cid
    assert r2.tool_used == "check_affordability"
    assert r2.data["amount"] == "2000.00"
    # the planner prompt for r2 must include the previous tool + args so "it" resolves
    planner_prompt_2 = client.calls[2]["prompt"]
    assert "check_affordability" in planner_prompt_2
    assert "headphones" in planner_prompt_2


def test_tool_call_limit_is_capped():
    from agent.orchestrator import MAX_TOOL_CALLS
    assert MAX_TOOL_CALLS == 3
    h, client = herman(plan_json("AFFORDABILITY", "check_affordability", {"amount": 100}), "ok")
    h.process_message(1, "can i afford 100", current_date=WHEN)
    # one plan + one tool + one responder — never a runaway
    assert len(client.calls) == 2


def test_ollama_unavailable_is_graceful_no_crash():
    client = FakeClient(available=False)
    h = Herman(client=client, repo_factory=repo_factory())
    r = h.process_message(1, "can I afford a laptop?", current_date=WHEN)
    assert r.ai["available"] is False
    assert r.tool_used is None
    assert "offline" in r.text.lower()
    assert client.calls == []  # we don't even try to generate when offline


def test_planner_junk_still_produces_a_reply_not_an_error():
    client = FakeClient(scripts=["garbage", "garbage", "I can help with money decisions."])
    h = Herman(client=client, repo_factory=repo_factory())
    r = h.process_message(1, "??!!", current_date=WHEN)
    assert r.intent == "GENERAL" and r.tool_used is None
    assert r.text


def test_responder_failure_falls_back_to_deterministic_template():
    # planner ok, tool ok, but responder generate() raises -> template
    client = FakeClient(scripts=[plan_json("AFFORDABILITY", "check_affordability", {"amount": 500})])
    client_raise = FakeClient(available=True)
    # first call (planner) returns the json; make a client that returns json once then raises
    class HalfBroken(FakeClient):
        def generate(self, prompt, system=None):
            self.calls.append({"prompt": prompt, "system": system})
            if len(self.calls) == 1:
                return plan_json("AFFORDABILITY", "check_affordability", {"amount": 500})
            from ai.ollama_client import OllamaUnavailable
            raise OllamaUnavailable("responder down")

    h = Herman(client=HalfBroken(), repo_factory=repo_factory())
    r = h.process_message(1, "can I afford 500?", current_date=WHEN)
    assert r.tool_used == "check_affordability"
    assert r.text and "₹" in r.text  # deterministic fallback template with real numbers


def test_conversation_isolated_per_user():
    client = FakeClient(scripts=[plan_json("GENERAL", None, {}), "hi"] * 4)
    h = Herman(client=client, repo_factory=repo_factory())
    r1 = h.process_message(1, "hello", current_date=WHEN)
    # user 2 tries to reuse user 1's conversation id -> gets a fresh one
    r2 = h.process_message(2, "hello", conversation_id=r1.conversation_id, current_date=WHEN)
    assert r2.conversation_id != r1.conversation_id
