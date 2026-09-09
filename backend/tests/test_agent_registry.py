"""ToolRegistry + tool catalog."""

import pytest

from tools import build_default_registry
from tools.base import Tool, ToolRegistry, ToolResult

EXPECTED = {
    "get_financial_twin", "check_affordability", "evaluate_financial_decision",
    "simulate_expense", "get_cashflow_forecast", "get_financial_anomalies",
    "get_transactions", "get_budget_status", "retrieve_financial_knowledge",
    "get_savings_goals", "evaluate_recovery_plan",
}


def test_default_registry_has_the_full_toolset():
    reg = build_default_registry()
    assert set(reg.names()) == EXPECTED


def test_lookup_and_has():
    reg = build_default_registry()
    assert reg.has("check_affordability")
    assert reg.get("check_affordability").name == "check_affordability"
    assert not reg.has("delete_everything")
    assert reg.get("delete_everything") is None


def test_run_unknown_tool_returns_failure_not_raise():
    reg = build_default_registry()
    res = reg.run("nope", ctx=None, raw_args={})
    assert isinstance(res, ToolResult) and res.ok is False and "unknown tool" in res.error


def test_catalog_shape_and_no_defaults_leaked():
    reg = build_default_registry()
    cat = reg.catalog()
    assert isinstance(cat, list) and len(cat) == len(EXPECTED)
    for entry in cat:
        assert set(entry) == {"name", "description", "arguments"}
        for arg_rule in entry["arguments"].values():
            assert "default" not in arg_rule  # planner shouldn't see internal defaults


def test_duplicate_registration_rejected():
    reg = ToolRegistry()

    class T(Tool):
        name = "t"
        def run(self, ctx, args):  # pragma: no cover
            return ToolResult.success("t", {})

    reg.register(T(lambda: None))
    with pytest.raises(ValueError):
        reg.register(T(lambda: None))


def test_nameless_tool_rejected():
    reg = ToolRegistry()

    class Bad(Tool):
        name = ""
        def run(self, ctx, args):  # pragma: no cover
            return ToolResult.success("", {})

    with pytest.raises(ValueError):
        reg.register(Bad(lambda: None))


def test_tool_execute_rejects_bad_args_before_running():
    reg = build_default_registry()
    tool = reg.get("check_affordability")
    res = tool.execute(ctx=object(), raw_args={"amount": "not a number"})
    assert res.ok is False and "invalid arguments" in res.error
