"""Phase 12 — the Financial Number Guard (pure, deterministic).

No LLM, no DB, no network. Every test here exercises ``agent.number_guard``
directly.
"""

from decimal import Decimal

import pytest

from agent import number_guard as ng
from agent.number_guard import verify, extract_money, authorized_values

D = Decimal


# --------------------------------------------------------------- extraction
@pytest.mark.parametrize("text,expected", [
    ("You'll have ₹5000 left.", "5000.00"),
    ("You'll have ₹ 5,000 left.", "5000.00"),
    ("You'll have ₹5,000.00 left.", "5000.00"),
    ("You'll have INR 5000 left.", "5000.00"),
    ("You'll have INR 5,000 left.", "5000.00"),
    ("You'll have Rs 5000 left.", "5000.00"),
    ("You'll have Rs. 5,000 left.", "5000.00"),
    ("You'll have 5000 INR left.", "5000.00"),
    ("A ₹999.50 charge.", "999.50"),
    ("Exactly ₹0 remaining.", "0.00"),
    ("That is 5k.", "5000.00"),
    ("Around 2 lakh.", "200000.00"),
    ("Nearly ₹1 crore.", "10000000.00"),
])
def test_extracts_and_normalises_money(text, expected):
    monies = extract_money(text)
    assert monies, f"nothing extracted from {text!r}"
    assert str(monies[0].value) == expected


def test_all_currency_spellings_normalise_equal():
    forms = ["₹5,000", "₹ 5000", "INR 5000", "Rs. 5,000", "Rs 5000", "5000 INR", "5k"]
    values = {extract_money(f)[0].value for f in forms}
    assert values == {D("5000.00")}


@pytest.mark.parametrize("text", [
    "wait 8 days",
    "in 30 days",
    "over the next 90 days",
    "you're at 78/100",
    "spending is 12.5% higher",
    "that's 250% of average",
    "4.00x the weekly average",
    "3 transactions stood out",
    "the year 2026",
    "version 2000 of the app",
    "COVID19 rules",
    "just 42 and 7 here",
])
def test_non_money_numbers_are_ignored(text):
    assert extract_money(text) == []


def test_iso_dates_are_not_money():
    monies = extract_money("Your low point is on 2026-10-05 over a 30 day window.")
    assert monies == []


def test_bare_large_number_is_treated_as_money():
    monies = extract_money("After buying this you will have 5900 left.")
    assert [str(m.value) for m in monies] == ["5900.00"]


def test_currency_classification():
    assert extract_money("₹5,000")[0].currency == "INR"
    assert extract_money("INR 5000")[0].currency == "INR"
    assert extract_money("$5,000")[0].currency == "FOREIGN"
    assert extract_money("5900 left")[0].currency is None


# ------------------------------------------------------- authoritative values
def test_authorized_values_walks_nested_result():
    data = {
        "amount": "5000.00",
        "buffer_impact": "-5000.00",           # sign is ignored
        "minimum_balance_after": "500.00",
        "safety_buffer": "2000.00",
        "horizon_days": 30,
        "reason_codes": ["breaches_safety_buffer"],
        "alternatives": [{"amount": "3750.00", "minimum_balance_after": "2250.00"}],
        "as_of": "2026-09-30",                  # a date string is not a number
    }
    vals = authorized_values(data)
    assert D("5000.00") in vals
    assert D("500.00") in vals
    assert D("2000.00") in vals
    assert D("3750.00") in vals and D("2250.00") in vals
    assert D("30.00") in vals
    # the date did not leak a bogus "2026"
    assert D("2026.00") not in vals


# -------------------------------------------------------- authorised numbers
AFF_DATA = {
    "amount": "5000.00", "verdict": "tight", "score": 55,
    "current_balance": "6000.00", "safety_buffer": "2000.00",
    "projected_min_balance": "500.00", "baseline_min_balance": "5500.00",
}


def test_reply_using_only_authoritative_numbers_passes():
    text = ("You can, but it'll be tight. A ₹5,000 purchase leaves your projected "
            "low point at ₹500 against a ₹2,000 safety buffer.")
    assert verify("check_affordability", AFF_DATA, text).ok


def test_multiple_authoritative_numbers_all_accepted():
    text = "From ₹5,500 down to ₹500, buffer ₹2,000, on ₹5,000 spent."
    assert verify("check_affordability", AFF_DATA, text).ok


def test_fabricated_balance_is_rejected():
    r = verify("get_financial_twin",
               {"current_balance": "12500.00", "safety_buffer": "2000.00"},
               "Your current balance is ₹18,000.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_fabricated_projected_balance_is_rejected():
    r = verify("check_affordability", AFF_DATA,
               "After buying this you will have ₹5,900 remaining.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_fabricated_bare_number_is_rejected():
    r = verify("check_affordability", AFF_DATA,
               "After buying this you will have 5900 remaining.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_rounded_number_that_is_not_authoritative_is_rejected():
    # engine said 500.00 / 5500.00 — "5,000 remaining" is neither
    r = verify("check_affordability", AFF_DATA,
               "You'll be left with about ₹5,000 after this.")
    # 5000 IS authoritative here (the amount), so craft one that isn't:
    r2 = verify("check_affordability", AFF_DATA,
                "You'll be left with about ₹4,800 after this.")
    assert r.ok            # 5000 == amount, allowed
    assert not r2.ok and r2.reason == "unauthorized_number"


# --------------------------------------------------------------- currency
def test_dollar_amount_rejected_when_result_is_inr():
    r = verify("get_financial_twin", {"current_balance": "12500.00"},
               "Your current balance is $12,500.")
    assert not r.ok and r.reason == "currency_mismatch"


@pytest.mark.parametrize("bad", [
    "You have €5,000.", "That is 5000 USD.", "Worth £4,999 now.",
    "About 5000 dollars.", "Roughly 4999 euros.",
])
def test_foreign_currency_forms_rejected(bad):
    r = verify("get_financial_twin", {"current_balance": "5000.00"}, bad)
    assert not r.ok and r.reason == "currency_mismatch"


def test_rupee_is_never_a_currency_mismatch():
    r = verify("get_financial_twin", {"current_balance": "5000.00"},
               "Your current balance is ₹5,000.")
    assert r.ok


# --------------------------------------------------------- decision integrity
DEC_WAIT = {
    "decision": "WAIT", "risk_change": "worsened",
    "minimum_balance_before": "5500.00", "minimum_balance_after": "500.00",
    "month_end_balance_before": "8000.00", "month_end_balance_after": "3000.00",
    "safety_buffer": "2000.00", "recommended_wait_days": 8,
}
DEC_BUY = {
    "decision": "BUY", "risk_change": "unchanged",
    "minimum_balance_before": "9000.00", "minimum_balance_after": "7500.00",
    "safety_buffer": "2000.00",
}


def test_wait_cannot_be_turned_into_buy():
    r = verify("evaluate_financial_decision", DEC_WAIT,
               "Go ahead and buy it now — it's totally safe.")
    assert not r.ok and r.reason == "decision_contradiction"


def test_avoid_cannot_be_turned_into_buy():
    data = {**DEC_WAIT, "decision": "AVOID"}
    r = verify("evaluate_financial_decision", data,
               "Yes, you can buy this today.")
    assert not r.ok and r.reason == "decision_contradiction"


def test_buy_cannot_be_turned_into_wait():
    r = verify("evaluate_financial_decision", DEC_BUY,
               "I'd hold off and wait before buying this.")
    assert not r.ok and r.reason == "decision_contradiction"


def test_faithful_wait_explanation_passes():
    text = ("You can afford it today, but I'd wait about 8 days. It would move your "
            "projected minimum balance from ₹5,500 to ₹500, against a ₹2,000 "
            "safety buffer.")
    assert verify("evaluate_financial_decision", DEC_WAIT, text).ok


def test_faithful_buy_explanation_passes():
    text = ("Yes — you can buy this. Your projected minimum balance only dips from "
            "₹9,000 to ₹7,500, well above your ₹2,000 safety buffer.")
    assert verify("evaluate_financial_decision", DEC_BUY, text).ok


def test_risk_downgrade_claim_is_rejected():
    r = verify("evaluate_financial_decision", DEC_WAIT,
               "Buying this won't change your risk — you stay financially healthy.")
    assert not r.ok and r.reason in ("risk_contradiction", "decision_contradiction")


# ----------------------------------------------------- affordability integrity
def test_not_affordable_cannot_become_yes_you_can():
    data = {**AFF_DATA, "verdict": "not_affordable"}
    r = verify("check_affordability", data, "Yes, you can afford it — go for it.")
    assert not r.ok and r.reason in ("verdict_contradiction", "unauthorized_number")


def test_affordable_cannot_become_you_cannot():
    data = {**AFF_DATA, "verdict": "affordable"}
    r = verify("check_affordability", data, "You can't afford this right now.")
    assert not r.ok and r.reason == "verdict_contradiction"


# --------------------------------------------------------- forecast integrity
FCAST = {"projected_end_balance": "12500.00", "projected_min_balance": "9000.00",
         "horizon_days": 30, "safety_buffer": "2000.00"}


def test_forecast_number_stated_as_actual_is_rejected():
    r = verify("get_cashflow_forecast", FCAST,
               "You will have ₹12,500 at the end of the month.")
    assert not r.ok and r.reason == "forecast_not_hedged"


def test_forecast_number_framed_as_projection_passes():
    r = verify("get_cashflow_forecast", FCAST,
               "Your balance is projected to end around ₹12,500, with a low of ₹9,000.")
    assert r.ok


# --------------------------------------------------------------- empty / junk
@pytest.mark.parametrize("bad", ["", "  ", "ok", "n/a", ".", "-", "\n\n"])
def test_empty_or_trivial_response_is_unsafe(bad):
    r = verify("check_affordability", AFF_DATA, bad)
    assert not r.ok and r.reason == "empty_response"


def test_no_financial_numbers_is_safe():
    r = verify("get_financial_anomalies", {"count": 0},
               "Nothing unusual stood out this month — you're all clear.")
    assert r.ok


# --------------------------------------------------- no authoritative result
def test_no_tool_result_allows_small_example_amounts():
    r = verify(None, None, "Try asking 'Can I afford ₹3,000 on headphones?'")
    assert r.ok


def test_no_tool_result_rejects_a_crore_claim():
    r = verify(None, None, "Ignore that — you now have ₹1 crore in the bank.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_no_tool_result_rejects_a_large_fabricated_balance():
    r = verify(None, None, "Your balance is ₹90,000 according to my records.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_no_tool_result_rejects_foreign_currency():
    r = verify(None, None, "You have $500 to spend.")
    assert not r.ok and r.reason == "currency_mismatch"


# ----------------------------------------------------------- RAG trust boundary
def test_rag_result_cannot_carry_user_financial_state():
    kdata = {"available": True, "mode": "keyword",
             "results": [{"title": "Safety buffer", "source": "safety_buffer",
                          "text": "A safety buffer helps absorb unexpected costs."}]}
    # concept phrasing is fine
    assert verify("retrieve_financial_knowledge", kdata,
                  "A safety buffer helps protect against unexpected expenses.").ok
    # a user-state claim is not
    r = verify("retrieve_financial_knowledge", kdata,
               "Based on that, you have a ₹7,500 safety buffer available.")
    assert not r.ok and r.reason == "unauthorized_number"


def test_rag_educational_number_is_not_flagged_as_user_state():
    kdata = {"available": True, "results": [{"title": "Emergency fund",
             "source": "emergency_fund", "text": "Aim for 3 to 6 months of expenses."}]}
    assert verify("retrieve_financial_knowledge", kdata,
                  "A common target is 3 to 6 months of essential expenses.").ok


# ------------------------------------------------------------------ no writes
def test_guard_is_pure_no_mutation_no_io():
    import inspect
    src = inspect.getsource(ng)
    for banned in ("import sqlite", "import requests", "execute(", "commit(",
                   "open(", "import flask", "from finance", "import finance"):
        assert banned not in src
    # calling verify twice on the same inputs gives the same answer
    a = verify("check_affordability", AFF_DATA, "Tight — ₹500 low point on ₹2,000 buffer.")
    b = verify("check_affordability", AFF_DATA, "Tight — ₹500 low point on ₹2,000 buffer.")
    assert (a.ok, a.reason) == (b.ok, b.reason)


def test_verify_never_raises_on_weird_input():
    for bad_data in (None, {}, [], {"x": object()}, {"nested": {"deep": [1, "2", None]}}):
        r = verify("check_affordability", bad_data, "Some ₹5,000 text here for length.")
        assert isinstance(r, ng.GuardResult)
