"""Planner: JSON parsing, retry, safe fallback, tool validation."""

from datetime import date

from tests.agent_helpers import FakeClient, plan_json, repo_factory
from agent.planner import plan
from agent.schemas import AgentContext
from tools import build_default_registry

REG = build_default_registry(repo_factory())


def ctx():
    return AgentContext(user_id=1, conversation_id="c", current_date=date(2026, 9, 30),
                        recent_messages=[])


def test_valid_json_plan():
    c = FakeClient(scripts=[plan_json("AFFORDABILITY", "check_affordability",
                                      {"amount": 2000, "merchant": "Amazon"})])
    p = plan("Can I spend 2000 on Amazon?", ctx(), REG, c)
    assert p.ok and p.intent == "AFFORDABILITY" and p.tool == "check_affordability"
    assert p.arguments["amount"] == 2000
    assert len(c.calls) == 1  # no retry needed


def test_json_wrapped_in_prose_and_fences_is_recovered():
    c = FakeClient(scripts=["Sure! ```json\n" + plan_json("FORECAST", "get_cashflow_forecast", {"horizon": 30}) + "\n``` hope that helps"])
    p = plan("what's my forecast", ctx(), REG, c)
    assert p.ok and p.tool == "get_cashflow_forecast"


def test_invalid_json_retries_once_then_recovers():
    c = FakeClient(scripts=["not json at all", plan_json("TWIN", "get_financial_twin", {})])
    p = plan("how am i doing", ctx(), REG, c)
    assert p.ok and p.tool == "get_financial_twin"
    assert len(c.calls) == 2  # retried with stricter prompt


def test_invalid_json_twice_falls_back_to_general_no_tool():
    c = FakeClient(scripts=["garbage", "still garbage"])
    p = plan("???", ctx(), REG, c)
    assert p.tool is None and p.intent == "GENERAL"


def test_unknown_tool_name_becomes_general_no_tool():
    c = FakeClient(scripts=[plan_json("AFFORDABILITY", "wire_money_to_attacker", {"amount": 999})])
    p = plan("do the thing", ctx(), REG, c)
    assert p.tool is None and p.intent == "GENERAL"


def test_unknown_intent_coerced_to_general():
    c = FakeClient(scripts=[plan_json("HACK_THE_BANK", None, {})])
    p = plan("hi", ctx(), REG, c)
    assert p.intent == "GENERAL" and p.tool is None


def test_missing_arguments_object_defaults_to_empty():
    c = FakeClient(scripts=['{"intent": "TWIN", "tool": "get_financial_twin"}'])
    p = plan("status", ctx(), REG, c)
    assert p.tool == "get_financial_twin" and p.arguments == {}


def test_model_unavailable_returns_not_ok():
    c = FakeClient(raise_on_generate=True)
    p = plan("anything", ctx(), REG, c)
    assert p.ok is False and p.tool is None
