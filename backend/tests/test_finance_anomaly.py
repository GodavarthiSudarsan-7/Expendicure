"""Unit tests for the deterministic anomaly engine. Pure — no DB, no LLM."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import Transaction
from finance.anomaly import (
    detect_anomalies,
    AnomalyResult,
    Anomaly,
    TOOL_SPEC,
    NEW_LARGE_MERCHANT_MIN,
)

AS_OF = date(2026, 9, 30)
D = Decimal
_ID = [0]


def t(amount, direction, days_before, *, merchant="Acme", category_id=1, category_name="Food",
      tid=None):
    _ID[0] += 1
    return Transaction(
        id=tid if tid is not None else _ID[0],
        student_id=1, amount=D(str(amount)), direction=direction, merchant_name=merchant,
        category_id=category_id, category_name=category_name,
        payment_date=AS_OF - timedelta(days=days_before),
    )


def types(result):
    return [a.type for a in result.anomalies]


def of_type(result, typ):
    return [a for a in result.anomalies if a.type == typ]


# ============================================================ amount_outlier

def _outlier_history(median_amount="100", n=5, direction="debit"):
    # n same-direction peers spread across the history window
    return [t(median_amount, direction, 20 + i, merchant=f"Hist{i}") for i in range(n)]


def test_amount_outlier_normal_transaction_not_flagged():
    txns = _outlier_history() + [t("120", "debit", 1, merchant="Shop")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier") == []


def test_amount_outlier_exactly_2_5x_is_medium():
    txns = _outlier_history("100") + [t("250", "debit", 1, merchant="Shop", tid=999)]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier")
    assert len(hits) == 1
    assert hits[0].severity == "medium"
    assert hits[0].fields["ratio"] == D("2.50")
    assert hits[0].fields["transaction_id"] == 999
    assert hits[0].fields["historical_median"] == D("100.00")


def test_amount_outlier_below_threshold_not_flagged():
    txns = _outlier_history("100") + [t("249", "debit", 1, merchant="Shop")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier") == []


def test_amount_outlier_high_severity_at_4x():
    txns = _outlier_history("100") + [t("400", "debit", 1, merchant="Shop")]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier")
    assert hits[0].severity == "high"


def test_amount_outlier_insufficient_history_not_flagged():
    txns = _outlier_history("100", n=4) + [t("500", "debit", 1)]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier") == []


def test_amount_outlier_direction_separation():
    # 5 debit peers of 100, plus a large CREDIT -> not a debit-median outlier
    txns = _outlier_history("100", direction="debit") + [t("9999", "credit", 1, merchant="X")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier") == []


def test_amount_outlier_decimal_precision():
    txns = _outlier_history("100.005") + [t("300.00", "debit", 1)]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier")
    assert hits and hits[0].fields["historical_median"] == D("100.01")  # 100.005 -> money -> 100.01
    d = hits[0].to_dict()
    assert d["amount"] == "300.00" and len(d["historical_median"].split(".")[1]) == 2


def test_amount_outlier_only_recent_transactions_checked():
    # a big spike 40 days ago is outside the recent window -> not flagged
    txns = _outlier_history("100") + [t("999", "debit", 40, merchant="Old")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier") == []


# ============================================================ category_spike

def test_category_spike_normal_not_flagged():
    txns = [
        t("100", "debit", 3, category_name="Food"),   # recent
        t("100", "debit", 10, category_name="Food"),  # bucket0
        t("100", "debit", 17, category_name="Food"),  # bucket1
    ]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike") == []


def test_category_spike_flagged_high():
    txns = [
        t("400", "debit", 3, category_name="Food"),    # recent = 400
        t("100", "debit", 10, category_name="Food"),   # bucket0
        t("100", "debit", 17, category_name="Food"),   # bucket1  -> weekly_avg 100
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike")
    assert len(hits) == 1
    assert hits[0].fields["category"] == "Food"
    assert hits[0].fields["recent_spending"] == D("400.00")
    assert hits[0].fields["historical_weekly_average"] == D("100.00")
    assert hits[0].fields["ratio"] == D("4.00")
    assert hits[0].severity == "high"
    assert hits[0].fields["transaction_count"] == 1


def test_category_spike_exactly_threshold_is_medium():
    txns = [
        t("175", "debit", 3, category_name="Food"),
        t("100", "debit", 10, category_name="Food"),
        t("100", "debit", 17, category_name="Food"),
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike")
    assert hits[0].fields["ratio"] == D("1.75")
    assert hits[0].severity == "medium"


def test_category_spike_insufficient_history_not_flagged():
    txns = [
        t("400", "debit", 3, category_name="Food"),
        t("100", "debit", 10, category_name="Food"),  # only 1 historical bucket
    ]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike") == []


def test_category_spike_debit_only():
    txns = [
        t("400", "credit", 3, category_name="Food"),   # income, ignored
        t("100", "debit", 10, category_name="Food"),
        t("100", "debit", 17, category_name="Food"),
    ]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike") == []


def test_category_spike_multiple_categories_only_spiking_one():
    txns = [
        t("400", "debit", 3, category_name="Food"),
        t("100", "debit", 10, category_name="Food"),
        t("100", "debit", 17, category_name="Food"),
        t("50", "debit", 3, category_name="Travel"),
        t("50", "debit", 10, category_name="Travel"),
        t("50", "debit", 17, category_name="Travel"),
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike")
    assert [h.fields["category"] for h in hits] == ["Food"]


def test_category_spike_window_boundary():
    # a Food debit exactly 7 days before as_of is on the recent/bucket edge:
    # filter is (as_of-7, as_of] so day-7 is NOT recent, it is bucket0
    txns = [
        t("100", "debit", 7, category_name="Food"),    # bucket0 (not recent)
        t("100", "debit", 14, category_name="Food"),   # bucket1
        t("500", "debit", 6, category_name="Food"),    # recent
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "category_spike")
    assert hits and hits[0].fields["recent_spending"] == D("500.00")


# ========================================================= duplicate_transaction

def test_duplicate_exact_same_day():
    txns = [
        t("1499", "debit", 2, merchant="ABC Store", tid=101),
        t("1499", "debit", 2, merchant="ABC store!", tid=102),  # normalises the same
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction")
    assert len(hits) == 1
    assert sorted(hits[0].fields["transaction_ids"]) == [101, 102]
    assert hits[0].severity == "medium"
    assert hits[0].fields["amount"] == D("1499.00")


def test_duplicate_one_day_apart_is_low():
    txns = [t("50", "debit", 3, merchant="Bus", tid=1), t("50", "debit", 2, merchant="Bus", tid=2)]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction")
    assert hits[0].severity == "low"


def test_duplicate_three_matching_produce_one_group():
    txns = [
        t("20", "debit", 3, merchant="Cafe", tid=1),
        t("20", "debit", 3, merchant="Cafe", tid=2),
        t("20", "debit", 2, merchant="Cafe", tid=3),
    ]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction")
    assert len(hits) == 1
    assert sorted(hits[0].fields["transaction_ids"]) == [1, 2, 3]


def test_duplicate_different_merchant_not_grouped():
    txns = [t("50", "debit", 2, merchant="A"), t("50", "debit", 2, merchant="B")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction") == []


def test_duplicate_different_amount_not_grouped():
    txns = [t("50", "debit", 2, merchant="A"), t("51", "debit", 2, merchant="A")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction") == []


def test_duplicate_different_direction_not_grouped():
    txns = [t("50", "debit", 2, merchant="A"), t("50", "credit", 2, merchant="A")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction") == []


def test_duplicate_three_days_apart_not_flagged():
    txns = [t("50", "debit", 6, merchant="A", tid=1), t("50", "debit", 2, merchant="A", tid=2)]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction") == []


def test_duplicate_no_false_positive_on_unique_transactions():
    txns = [t("10", "debit", 1, merchant="A"), t("20", "debit", 2, merchant="B"),
            t("30", "debit", 3, merchant="C")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "duplicate_transaction") == []


# ============================================================ budget_breach

def test_budget_breach_under_budget():
    txns = [t("400", "debit", 2, category_name="Food")]
    r = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF)
    assert of_type(r, "budget_breach") == []


def test_budget_breach_exactly_budget_not_flagged():
    txns = [t("500", "debit", 2, category_name="Food")]
    r = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF)
    assert of_type(r, "budget_breach") == []


def test_budget_breach_over_budget_medium():
    txns = [t("600", "debit", 2, category_name="Food")]
    hits = of_type(detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF), "budget_breach")
    assert len(hits) == 1
    assert hits[0].fields["spent"] == D("600.00")
    assert hits[0].fields["budget"] == D("500.00")
    assert hits[0].fields["over_by"] == D("100.00")
    assert hits[0].fields["ratio"] == D("1.20")
    assert hits[0].severity == "medium"


def test_budget_breach_over_25_percent_is_high():
    txns = [t("700", "debit", 2, category_name="Food")]
    hits = of_type(detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF), "budget_breach")
    assert hits[0].fields["ratio"] == D("1.40")
    assert hits[0].severity == "high"


def test_budget_breach_multiple_categories():
    txns = [t("600", "debit", 2, category_name="Food"),
            t("900", "debit", 2, category_name="Travel", category_id=2)]
    hits = of_type(detect_anomalies(
        txns, budgets={"Food": D("500"), "Travel": D("400")}, as_of=AS_OF), "budget_breach")
    assert sorted(h.fields["category"] for h in hits) == ["Food", "Travel"]


def test_budget_breach_only_categories_with_budget():
    txns = [t("9999", "debit", 2, category_name="Yacht", category_id=3)]
    r = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF)
    assert of_type(r, "budget_breach") == []


def test_budget_breach_respects_month_boundary():
    # a big Food debit in the previous month is not counted for this month's budget
    prev_month = date(AS_OF.year, AS_OF.month, 1) - timedelta(days=3)
    txns = [
        Transaction(id=1, student_id=1, amount=D("9999"), direction="debit", merchant_name="X",
                    category_id=1, category_name="Food", payment_date=prev_month),
        t("100", "debit", 2, category_name="Food"),
    ]
    r = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF)
    assert of_type(r, "budget_breach") == []


def test_budget_breach_no_budgets_configured():
    txns = [t("9999", "debit", 2, category_name="Food")]
    assert of_type(detect_anomalies(txns, budgets={}, as_of=AS_OF), "budget_breach") == []


# ========================================================= new_large_merchant

def _debit_history(amount="500", n=5):
    return [t(amount, "debit", 20 + i, merchant=f"Known{i}") for i in range(n)]


def test_new_large_merchant_flagged_medium():
    # median 500 -> threshold = max(1000, 2000) = 2000 ; amount 3000 -> medium
    txns = _debit_history("500") + [t("3000", "debit", 1, merchant="New Electronics", tid=777)]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant")
    assert len(hits) == 1
    assert hits[0].fields["merchant"] == "New Electronics"
    assert hits[0].fields["transaction_id"] == 777
    assert hits[0].fields["large_threshold"] == D("2000.00")
    assert hits[0].severity == "medium"


def test_new_large_merchant_high_at_2x_threshold():
    txns = _debit_history("500") + [t("4000", "debit", 1, merchant="New Electronics")]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant")
    assert hits[0].severity == "high"


def test_new_large_merchant_median_threshold_dominates():
    # median 2000 -> threshold = max(4000, 2000) = 4000
    txns = _debit_history("2000") + [t("4000", "debit", 1, merchant="Boutique")]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant")
    assert hits[0].fields["large_threshold"] == D("4000.00")
    assert hits[0].fields["historical_median_debit"] == D("2000.00")


def test_new_large_merchant_existing_merchant_not_flagged():
    txns = _debit_history("500") + [
        t("100", "debit", 60, merchant="Boutique"),                 # seen before
        t("5000", "debit", 1, merchant="Boutique"),
    ]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant") == []


def test_new_large_merchant_insufficient_history():
    txns = _debit_history("500", n=4) + [t("9000", "debit", 1, merchant="New")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant") == []


def test_new_large_merchant_below_threshold_not_flagged():
    txns = _debit_history("500") + [t("1500", "debit", 1, merchant="New")]  # < 2000 floor
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant") == []


def test_new_large_merchant_boundary_exact_threshold():
    txns = _debit_history("500") + [t(str(NEW_LARGE_MERCHANT_MIN), "debit", 1, merchant="New")]
    hits = of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant")
    assert len(hits) == 1


def test_new_large_merchant_credit_ignored():
    txns = _debit_history("500") + [t("9000", "credit", 1, merchant="New Payout")]
    assert of_type(detect_anomalies(txns, as_of=AS_OF), "new_large_merchant") == []


# =============================================================== general

def test_empty_history_no_anomalies():
    r = detect_anomalies([], as_of=AS_OF)
    assert isinstance(r, AnomalyResult)
    assert r.count == 0 and r.anomalies == ()
    d = r.to_dict()
    assert d["count"] == 0 and d["high_count"] == 0 and d["medium_count"] == 0 and d["low_count"] == 0


def test_deterministic_repeated_calls():
    txns = _outlier_history("100") + _debit_history("500", n=3) + [
        t("300", "debit", 1, merchant="Shop"),
        t("1499", "debit", 2, merchant="ABC", tid=501),
        t("1499", "debit", 2, merchant="ABC", tid=502),
    ]
    a = detect_anomalies(txns, budgets={"Food": D("100")}, as_of=AS_OF).to_dict()
    b = detect_anomalies(txns, budgets={"Food": D("100")}, as_of=AS_OF).to_dict()
    assert a == b


def test_inputs_not_mutated():
    txns = _outlier_history("100") + [t("300", "debit", 1)]
    snapshot = [(x.id, x.amount, x.direction, x.payment_date) for x in txns]
    detect_anomalies(txns, budgets={"Food": D("10")}, as_of=AS_OF)
    assert [(x.id, x.amount, x.direction, x.payment_date) for x in txns] == snapshot


def test_to_dict_money_is_two_decimal_strings():
    txns = _outlier_history("100") + [t("600", "debit", 2, category_name="Food")]
    d = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF).to_dict()
    for a in d["anomalies"]:
        for k, v in a.items():
            if k in ("amount", "historical_median", "spent", "budget", "over_by",
                     "recent_spending", "historical_weekly_average", "large_threshold",
                     "historical_median_debit"):
                assert isinstance(v, str) and len(v.split(".")[1]) == 2


def test_result_schema():
    d = detect_anomalies([], as_of=AS_OF, history_days=45).to_dict()
    assert set(d) == {"as_of", "history_days", "anomalies", "count",
                      "high_count", "medium_count", "low_count"}
    assert d["as_of"] == "2026-09-30"
    assert d["history_days"] == 45


def test_anomaly_schema_fields():
    txns = _outlier_history("100") + [t("400", "debit", 1, merchant="Shop")]
    a = of_type(detect_anomalies(txns, as_of=AS_OF), "amount_outlier")[0].to_dict()
    assert a["type"] == "amount_outlier"
    assert a["severity"] in {"low", "medium", "high"}
    assert "reason" in a and isinstance(a["reason"], str)
    assert set(a) >= {"type", "severity", "reason", "transaction_id", "amount",
                      "historical_median", "ratio", "merchant", "date", "direction"}


def test_counts_add_up():
    txns = (_outlier_history("100")
            + [t("400", "debit", 1, merchant="Shop")]                     # amount_outlier high
            + [t("700", "debit", 2, category_name="Food")]                # budget_breach high
            + [t("1499", "debit", 3, merchant="ABC", tid=601),
               t("1499", "debit", 3, merchant="ABC", tid=602)])          # duplicate medium
    r = detect_anomalies(txns, budgets={"Food": D("500")}, as_of=AS_OF)
    d = r.to_dict()
    assert d["count"] == d["high_count"] + d["medium_count"] + d["low_count"]
    assert d["count"] == len(d["anomalies"])


@pytest.mark.parametrize("bad", [0, -1, 6, 366, 1000, "lots", 1.5, True, None])
def test_invalid_history_days_raises(bad):
    with pytest.raises(ValueError):
        detect_anomalies([], as_of=AS_OF, history_days=bad)


def test_valid_history_days_bounds():
    assert detect_anomalies([], as_of=AS_OF, history_days=7).history_days == 7
    assert detect_anomalies([], as_of=AS_OF, history_days=365).history_days == 365


def test_engine_has_no_db_handle():
    import inspect
    src = inspect.getsource(detect_anomalies)
    assert "execute_query" not in src and "get_repository" not in src
    params = list(inspect.signature(detect_anomalies).parameters)
    assert params[0] == "transactions"


def test_tool_spec_shape():
    assert TOOL_SPEC["name"] == "detect_anomalies"
    assert set(TOOL_SPEC["parameters"]["properties"]) == {"history_days", "as_of"}
