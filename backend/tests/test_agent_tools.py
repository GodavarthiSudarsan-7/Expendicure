"""Each tool runs against a FakeRepo through the REAL deterministic engines."""

from datetime import date
from decimal import Decimal

import pytest

from tests.agent_helpers import AS_OF, FakeRepo, repo_factory, txn
from tools import build_default_registry, make_context


def ctx(repo=None):
    return make_context(1, as_of=AS_OF, repo_factory=repo_factory(repo))


def reg():
    return build_default_registry(repo_factory())


def run(tool_name, args, repo=None):
    r = build_default_registry(repo_factory(repo))
    return r.run(tool_name, ctx(repo), args)


# ---------------------------------------------------------------- twin
def test_get_financial_twin():
    res = run("get_financial_twin", {})
    assert res.ok
    d = res.data
    assert "current_balance" in d and "discretionary_buffer" in d
    assert isinstance(d["top_spending_categories"], list)
    # 10000 + 5000 credit - 6*100 - 400 = 14000
    assert d["current_balance"] == "14000.00"


# ------------------------------------------------------- affordability
def test_check_affordability_calls_real_engine():
    res = run("check_affordability", {"amount": "500", "merchant": "Amazon", "category": "Food"})
    assert res.ok
    assert res.data["verdict"] in {"affordable", "tight", "not_affordable"}
    assert res.data["merchant"] == "Amazon"
    assert res.summary["merchant"] == "Amazon"
    assert set(res.summary) >= {"verdict", "score", "projected_min_balance", "safety_buffer"}


def test_check_affordability_bad_amount_is_failure():
    res = run("check_affordability", {"amount": "-5"})
    assert res.ok is False and "invalid arguments" in res.error


def test_check_affordability_engine_valueerror_is_failure():
    # purchase date before as_of -> engine raises ValueError -> ToolResult.failure
    res = run("check_affordability", {"amount": "10", "date": "2026-01-01"})
    assert res.ok is False


# --------------------------------------------------------- simulate
def test_simulate_one_time():
    res = run("simulate_expense", {"amount": "5000", "merchant": "Laptop"})
    assert res.ok
    assert res.summary["scenario"]["type"] == "one_off_expense"
    assert "end_balance_delta" in res.summary
    assert "safety_buffer_impact" in res.summary


def test_simulate_monthly_repeating():
    res = run("simulate_expense", {"amount": "1000", "frequency": "monthly", "duration": 3})
    assert res.ok
    assert res.summary["scenario"]["type"] == "recurring_expense"
    assert res.summary["scenario"]["cadence"] == "monthly"


def test_simulate_bad_frequency_rejected():
    res = run("simulate_expense", {"amount": "1000", "frequency": "yearly"})
    assert res.ok is False


# --------------------------------------------------------- forecast
def test_forecast_valid_horizons():
    for h in (7, 30, 60, 90):
        res = run("get_cashflow_forecast", {"horizon": h})
        assert res.ok
        assert res.summary["horizon_days"] == h
        assert "projected_min_balance" in res.summary


def test_forecast_rejects_disallowed_horizon():
    res = run("get_cashflow_forecast", {"horizon": 45})
    assert res.ok is False


# --------------------------------------------------------- anomalies
def test_anomalies_runs_and_summarises():
    res = run("get_financial_anomalies", {"history_days": 90})
    assert res.ok
    assert set(res.summary) >= {"count", "high", "medium", "low", "anomalies"}


def test_anomalies_severity_filter():
    res = run("get_financial_anomalies", {"history_days": 90, "severity_filter": "high"})
    assert res.ok
    assert all(a["severity"] == "high" for a in res.summary["anomalies"])


def test_anomalies_bad_history_days_rejected():
    res = run("get_financial_anomalies", {"history_days": 5})
    assert res.ok is False


# --------------------------------------------------------- transactions
def test_get_transactions_filters():
    res = run("get_transactions", {"direction": "credit"})
    assert res.ok
    assert res.data["count"] == 1
    assert res.data["transactions"][0]["merchant"] == "Scholarship"


def test_get_transactions_merchant_substring_and_limit():
    res = run("get_transactions", {"merchant": "hist", "limit": 3})
    assert res.ok
    assert res.data["returned"] == 3 and res.data["count"] == 6


def test_get_transactions_amount_range():
    res = run("get_transactions", {"min_amount": "300"})
    assert res.ok
    assert all(float(t["amount"]) >= 300 for t in res.data["transactions"])


# --------------------------------------------------------- budgets
def test_get_budget_status_uses_twin_numbers():
    res = run("get_budget_status", {})
    assert res.ok
    cats = res.data["categories"]
    food = next(c for c in cats if c["category"] == "Food")
    # Food spend month-to-date from twin = 400 (the BigShop debit), budget 500
    assert food["budget"] == "500.00"
    assert food["spent"] == "400.00"
    assert food["remaining"] == "100.00"
    assert food["used_percent"] == "80.00"
    assert food["status"] == "warning"  # 80% used


def test_get_budget_status_over_budget():
    repo = FakeRepo(budgets={"Food": Decimal("300.00")})
    res = run("get_budget_status", {}, repo=repo)
    food = next(c for c in res.data["categories"] if c["category"] == "Food")
    assert food["status"] == "over"
    assert food["over_by"] == "100.00"
    assert "Food" in res.data["over_budget"]


# --------------------------------------------------------- read-only guarantee
def test_no_tool_module_imports_a_write_path():
    import ast
    import pathlib
    for p in pathlib.Path("tools").glob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "commit=True" not in src
        assert "execute_query" not in src
        for banned in (".create(", ".update(", ".remove(", ".delete("):
            assert banned not in src, f"{p} contains {banned}"
