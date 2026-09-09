"""Phase 10 — the ``evaluate_financial_decision`` tool.

Thin validated wrapper over the consequence engine. Runs against ``FakeRepo``
through the real engine + real projection kernel.
"""

import pathlib

import pytest

from tests.agent_helpers import AS_OF, FakeRepo, repo_factory
from tools import build_default_registry, make_context

TOOL = "evaluate_financial_decision"


def run(args, repo=None, user_id=1):
    reg = build_default_registry(repo_factory(repo))
    ctx = make_context(user_id, as_of=AS_OF, repo_factory=repo_factory(repo))
    return reg.run(TOOL, ctx, args)


# --------------------------------------------------------------- happy path
def test_registered_in_default_registry():
    assert build_default_registry(repo_factory()).has(TOOL)


def test_evaluates_a_purchase_and_returns_the_full_shape():
    res = run({"amount": "500", "description": "headphones", "category": "electronics"})
    assert res.ok
    d = res.data
    assert d["decision"] in {"BUY", "WAIT", "SPEND_LESS", "AVOID"}
    assert d["amount"] == "500.00"
    assert d["description"] == "headphones" and d["category"] == "electronics"
    assert d["minimum_balance_before"] and d["minimum_balance_after"]
    assert d["month_end_balance_before"] and d["month_end_balance_after"]
    assert d["goal_impact"] == {"available": False, "delay_days": None,
                                "reason": "no savings goal is configured for this account"}
    assert d["goal_delay_days"] is None
    assert isinstance(d["alternatives"], list) and d["alternatives"][0]["kind"] == "buy_now"


def test_summary_is_compact_and_has_the_decision_fields():
    res = run({"amount": "500", "description": "headphones"})
    s = res.summary
    assert set(s) >= {"decision", "amount", "minimum_balance_before", "minimum_balance_after",
                      "risk_before", "risk_after", "risk_change", "recommended_wait_days",
                      "reason_codes", "alternatives"}
    # summary must not carry the day-by-day projection
    assert "points" not in s and "baseline" not in s


def test_merchant_is_used_as_description_when_description_absent():
    res = run({"amount": "500", "merchant": "Sony Store"})
    assert res.ok and res.data["description"] == "Sony Store"


def test_big_purchase_that_breaches_buffer_recommends_action():
    # FakeRepo: balance 14000, buffer 2000, rent -1500 on 2026-10-05
    res = run({"amount": "13000", "description": "laptop"})
    assert res.ok
    assert res.data["decision"] in {"WAIT", "SPEND_LESS", "AVOID"}
    assert res.data["buffer_breached_after"] is True


# --------------------------------------------------------------- validation
def test_missing_amount_is_invalid_arguments():
    res = run({"description": "headphones"})
    assert res.ok is False and "invalid arguments" in res.error


@pytest.mark.parametrize("bad", ["0", "-10", "abc", "NaN", "Infinity"])
def test_bad_amount_is_rejected_before_running(bad):
    res = run({"amount": bad})
    assert res.ok is False and "invalid arguments" in res.error


def test_identity_key_in_args_is_rejected():
    res = run({"amount": "500", "user_id": 999})
    assert res.ok is False and "invalid arguments" in res.error
    res = run({"amount": "500", "student_id": 999})
    assert res.ok is False


def test_unknown_arguments_are_ignored_not_passed_through():
    res = run({"amount": "500", "nonsense": "drop me", "horizon": 9999})
    assert res.ok  # unknown keys silently dropped


def test_authenticated_user_id_comes_from_context_only():
    # there is no accepted arg that can change identity; a spoof attempt is rejected
    res = run({"amount": "500", "id": 42})
    assert res.ok is False


def test_engine_valueerror_becomes_tool_failure_not_a_crash():
    res = run({"amount": "500", "purchase_date": "2026-01-01"})   # before as_of
    assert res.ok is False
    assert "invalid arguments" not in res.error                   # passed validation, engine refused
    assert "before today" in res.error


def test_bad_purchase_date_string_is_invalid_arguments():
    res = run({"amount": "500", "purchase_date": "not-a-date"})
    assert res.ok is False and "invalid arguments" in res.error


# --------------------------------------------------------------- read-only
def test_tool_module_has_no_write_path():
    src = pathlib.Path("tools/decision_tool.py").read_text(encoding="utf-8")
    for banned in ("commit", "execute_query", ".create(", ".update(", ".delete(", ".remove("):
        assert banned not in src


def test_repeated_calls_are_deterministic():
    a = run({"amount": "2500", "description": "tablet"})
    b = run({"amount": "2500", "description": "tablet"})
    assert a.data == b.data
