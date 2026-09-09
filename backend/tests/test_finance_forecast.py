"""Unit tests for the deterministic cash-flow forecast. Pure — no DB, no LLM."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import RecurringTransaction, Transaction
from finance.twin import TwinState
from finance.forecast import forecast, detect_recurring, TOOL_SPEC

AS_OF = date(2026, 9, 9)
D = Decimal


def make_twin(*, current_balance="10000.00", safety_buffer="2000.00", recurring=(), as_of=AS_OF):
    cb = D(current_balance)
    sb = D(safety_buffer)
    return TwinState(
        student_id=1, as_of=as_of, month=f"{as_of.year:04d}-{as_of.month:02d}",
        opening_balance=D("0.00"), current_balance=cb,
        month_income=D("0.00"), month_spending=D("0.00"), month_net=D("0.00"),
        month_discretionary_spending=D("0.00"),
        spending_by_category={}, budgets={}, recurring=tuple(recurring),
        safety_buffer=sb, committed_upcoming=D("0.00"),
        committed_upcoming_horizon_days=30, discretionary_buffer=cb - sb,
    )


def rec(amount, direction, next_date, *, cadence="monthly", rid=1, label="Rent", active=True,
        merchant="Landlord"):
    return RecurringTransaction(
        id=rid, student_id=1, label=label, merchant_name=merchant,
        amount=D(str(amount)), direction=direction, cadence=cadence,
        next_date=next_date, day_of_month=(next_date.day if cadence == "monthly" else None),
        weekday=None, active=active,
    )


def txn(amount, direction, payment_date, *, merchant="Acme", tid=1):
    return Transaction(
        id=tid, student_id=1, amount=D(str(amount)), direction=direction,
        merchant_name=merchant, category_id=1, category_name="Other",
        payment_date=payment_date, payment_method=None, notes=None,
    )


def monthly_history(merchant, amount, *, count, last=date(2026, 9, 1), direction="debit"):
    """`count` transactions ~1 month apart, ending at `last`."""
    out = []
    d = last
    for i in range(count):
        out.append(txn(amount, direction, d, merchant=merchant, tid=1000 + i))
        d = d - timedelta(days=30)
    return list(reversed(out))


# ------------------------------------------------------------------ 1-2 sparse

def test_empty_history_and_no_recurring_is_flat_and_low_confidence():
    f = forecast(make_twin(current_balance="5000.00"), [], horizon_days=30)
    assert f.confidence == "low"
    assert f.events == ()
    assert f.projected_min_balance == D("5000.00")
    assert f.projected_end_balance == D("5000.00")
    assert f.projected_income == D("0.00")
    assert f.projected_expenses == D("0.00")
    assert f.projected_net == D("0.00")
    assert f.assumptions[0].source == "none"
    assert "insufficient" in f.assumptions[0].note


def test_sparse_history_two_transactions_not_detected():
    hist = monthly_history("Netflix", "199", count=2)
    f = forecast(make_twin(), hist, horizon_days=90)
    assert all(a.source != "detected" for a in f.assumptions)
    assert f.confidence == "low"


# ------------------------------------------------------- 3-10 explicit recurring

def test_explicit_monthly_recurring_expense():
    twin = make_twin(current_balance="10000.00",
                     recurring=[rec("1000", "debit", date(2026, 9, 19))])
    f = forecast(twin, [], horizon_days=40)
    # occurrences: 09-19, 10-19
    assert [e.date for e in f.events] == [date(2026, 9, 19), date(2026, 10, 19)]
    assert f.projected_expenses == D("2000.00")
    assert f.projected_min_balance == D("8000.00")
    assert f.projected_min_balance_date == date(2026, 10, 19)
    assert f.projected_end_balance == D("8000.00")
    assert f.confidence == "high"
    assert f.events[0].source == "recurring" and f.events[0].confidence == "high"


def test_explicit_recurring_income():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00",
                     recurring=[rec("5000", "credit", date(2026, 9, 15), label="Salary",
                                    merchant="Employer")])
    f = forecast(twin, [], horizon_days=40)
    assert f.projected_income == D("10000.00")   # 09-15, 10-15
    assert f.projected_net == D("10000.00")
    assert f.projected_end_balance == D("11000.00")


def test_weekly_recurring():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00",
                     recurring=[rec("50", "debit", date(2026, 9, 12), cadence="weekly",
                                    label="Bus", merchant="Transit")])
    f = forecast(twin, [], horizon_days=21)
    # as_of 09-09, horizon end 09-30: 09-12, 09-19, 09-26 -> 3 x 50 (10-03 is out)
    assert [e.date for e in f.events] == [date(2026, 9, 12), date(2026, 9, 19), date(2026, 9, 26)]
    assert f.projected_expenses == D("150.00")


def test_multiple_recurring_transactions():
    twin = make_twin(current_balance="10000.00", recurring=[
        rec("1000", "debit", date(2026, 9, 19), rid=1, label="Rent", merchant="LL"),
        rec("5000", "credit", date(2026, 9, 25), rid=2, label="Salary", merchant="Emp"),
    ])
    f = forecast(twin, [], horizon_days=30)
    assert f.projected_income == D("5000.00")
    assert f.projected_expenses == D("1000.00")
    assert f.projected_net == D("4000.00")
    assert len(f.assumptions) == 2


def test_recurring_beyond_horizon_not_projected():
    twin = make_twin(recurring=[rec("1000", "debit", date(2026, 12, 1))])
    f = forecast(twin, [], horizon_days=30)
    assert f.events == ()
    assert f.assumptions[0].occurrences_in_horizon == 0


def test_recurring_exactly_on_horizon_boundary_included():
    d = AS_OF + timedelta(days=30)
    twin = make_twin(current_balance="5000.00", recurring=[rec("1000", "debit", d)])
    f = forecast(twin, [], horizon_days=30)
    assert [e.date for e in f.events] == [d]
    assert f.projection[-1].date == d
    assert f.projected_min_balance == D("4000.00")


def test_inactive_recurring_ignored():
    twin = make_twin(recurring=[rec("1000", "debit", date(2026, 9, 19), active=False)])
    f = forecast(twin, [], horizon_days=40)
    assert f.events == ()


# ------------------------------------------------- 11-13 calendar boundaries

def test_month_and_year_boundary_projection():
    twin = make_twin(current_balance="10000.00", as_of=date(2026, 12, 5),
                     recurring=[rec("500", "debit", date(2026, 12, 20))])
    f = forecast(twin, [], horizon_days=50)  # Dec 5 + 50d -> 2027-01-24
    assert [e.date for e in f.events] == [date(2026, 12, 20), date(2027, 1, 20)]


def test_february_day_of_month_clamp():
    twin = make_twin(current_balance="10000.00", as_of=date(2026, 1, 15),
                     recurring=[rec("500", "debit", date(2026, 1, 31))])
    f = forecast(twin, [], horizon_days=80)  # Jan 15 + 80d -> 2026-04-05
    assert [e.date for e in f.events] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


# --------------------------------------------- 14-20 detection & confidence

def test_high_confidence_detection_six_consistent_monthly():
    hist = monthly_history("Netflix", "199", count=6)
    det = detect_recurring(hist, as_of=AS_OF)
    assert len(det) == 1
    assert det[0].cadence == "monthly"
    assert det[0].amount == D("199.00")
    assert det[0].confidence == "high"
    assert det[0].observations == 6


def test_medium_confidence_detection_four_consistent():
    hist = monthly_history("Gym", "500", count=4)
    det = detect_recurring(hist, as_of=AS_OF)
    assert det[0].confidence == "medium"


def test_low_confidence_detection_three_consistent():
    hist = monthly_history("Cloud", "120", count=3)
    det = detect_recurring(hist, as_of=AS_OF)
    assert det and det[0].confidence == "low"


def test_inconsistent_cadence_not_detected():
    hist = [
        txn("100", "debit", date(2026, 6, 1), merchant="Erratic", tid=1),
        txn("100", "debit", date(2026, 6, 20), merchant="Erratic", tid=2),
        txn("100", "debit", date(2026, 9, 1), merchant="Erratic", tid=3),
    ]
    assert detect_recurring(hist, as_of=AS_OF) == []


def test_inconsistent_amounts_beyond_tolerance_not_detected():
    hist = [
        txn("100", "debit", date(2026, 6, 5), merchant="Wild", tid=1),
        txn("100", "debit", date(2026, 7, 5), merchant="Wild", tid=2),
        txn("500", "debit", date(2026, 8, 5), merchant="Wild", tid=3),
        txn("100", "debit", date(2026, 9, 4), merchant="Wild", tid=4),
    ]
    assert detect_recurring(hist, as_of=AS_OF) == []


def test_insufficient_observations_not_detected():
    assert detect_recurring(monthly_history("X", "10", count=2), as_of=AS_OF) == []


def test_detected_recurring_flows_into_forecast_events():
    hist = monthly_history("Netflix", "199", count=6)   # last on 2026-09-01
    twin = make_twin(current_balance="5000.00", safety_buffer="0.00")
    f = forecast(twin, hist, horizon_days=45)
    detected = [a for a in f.assumptions if a.source == "detected"]
    assert detected and detected[0].confidence == "high"
    assert any(e.source == "detected" and e.label == "Netflix" for e in f.events)
    # next occurrence after 2026-09-01 that is >= as_of: 2026-10-01 (then 2026-... none within 45d of 09-09? 10-01 in, 11-01 out)
    dates = [e.date for e in f.events]
    assert date(2026, 10, 1) in dates


def test_user_recurring_shadows_detected_same_merchant():
    hist = monthly_history("Landlord", "1000", count=6)
    twin = make_twin(recurring=[rec("1000", "debit", date(2026, 9, 19), merchant="Landlord")])
    f = forecast(twin, hist, horizon_days=40)
    assert all(a.source == "recurring" for a in f.assumptions)  # detected one dropped


def test_overall_confidence_is_lowest_assumption():
    hist = monthly_history("Cloud", "120", count=3)  # low
    twin = make_twin(recurring=[rec("1000", "debit", date(2026, 9, 19), merchant="LL")])  # high
    f = forecast(twin, hist, horizon_days=40)
    assert f.confidence == "low"


# ----------------------------------------------- 21-26 projected aggregates

def test_projected_aggregates_income_expense_net():
    twin = make_twin(current_balance="10000.00", recurring=[
        rec("1000", "debit", date(2026, 9, 19), rid=1, merchant="LL"),
        rec("300", "credit", date(2026, 9, 10), rid=2, label="Freelance", merchant="Client"),
    ])
    f = forecast(twin, [], horizon_days=30)
    assert f.projected_expenses == D("1000.00")
    assert f.projected_income == D("300.00")
    assert f.projected_net == D("-700.00")
    assert f.projected_end_balance == D("9300.00")


def test_min_balance_and_date_with_recovery():
    twin = make_twin(current_balance="3000.00", safety_buffer="0.00", recurring=[
        rec("2000", "debit", date(2026, 9, 12), rid=1, label="Bill", merchant="Util"),
        rec("5000", "credit", date(2026, 9, 20), rid=2, label="Pay", merchant="Emp"),
    ])
    f = forecast(twin, [], horizon_days=30)
    assert f.projected_min_balance == D("1000.00")           # after the 2000 bill
    assert f.projected_min_balance_date == date(2026, 9, 12)
    assert f.projected_end_balance == D("6000.00")           # after the 5000 pay


# --------------------------------------------------- 27-29 safety buffer

def test_safety_buffer_breach_and_date():
    twin = make_twin(current_balance="3000.00", safety_buffer="2500.00",
                     recurring=[rec("1000", "debit", date(2026, 9, 15))])
    f = forecast(twin, [], horizon_days=30)
    assert f.safety_buffer_breached is True
    assert f.breach_date == date(2026, 9, 15)
    assert f.projected_min_balance == D("2000.00")


def test_no_safety_buffer_breach():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00",
                     recurring=[rec("1000", "debit", date(2026, 9, 15))])
    f = forecast(twin, [], horizon_days=30)
    assert f.safety_buffer_breached is False
    assert f.breach_date is None


def test_breach_date_is_earliest_even_if_recovers():
    twin = make_twin(current_balance="3000.00", safety_buffer="2500.00", recurring=[
        rec("1000", "debit", date(2026, 9, 12), rid=1, label="A", merchant="A"),
        rec("5000", "credit", date(2026, 9, 15), rid=2, label="B", merchant="B"),
        rec("1000", "debit", date(2026, 9, 25), rid=3, label="C", merchant="C"),
    ])
    f = forecast(twin, [], horizon_days=30)
    assert f.breach_date == date(2026, 9, 12)   # earliest dip below 2500


# ---------------------------------------------------- 30-33 precision / errors

def test_decimal_precision_two_places_everywhere():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00",
                     recurring=[rec("33.333", "debit", date(2026, 9, 12), cadence="weekly")])
    d = forecast(twin, [], horizon_days=21).to_dict()
    monies = [d["starting_balance"], d["projected_min_balance"], d["projected_end_balance"],
              d["projected_income"], d["projected_expenses"], d["projected_net"], d["safety_buffer"]]
    monies += [p["balance"] for p in d["projection"]]
    monies += [e["amount"] for e in d["events"]]
    for m in monies:
        assert isinstance(m, str) and len(m.split(".")[1]) == 2


def test_deterministic_repeated_forecast():
    hist = monthly_history("Netflix", "199", count=6)
    twin = make_twin(current_balance="4321.00", safety_buffer="1500.00",
                     recurring=[rec("777.77", "debit", date(2026, 9, 19), merchant="LL")])
    a = forecast(twin, hist, horizon_days=60).to_dict()
    b = forecast(twin, hist, horizon_days=60).to_dict()
    assert a == b


@pytest.mark.parametrize("horizon", [0, -1, 366, 1000, "lots", 1.5, True, None])
def test_invalid_horizon_raises(horizon):
    with pytest.raises(ValueError):
        forecast(make_twin(), [], horizon_days=horizon)


def test_valid_horizon_bounds():
    assert forecast(make_twin(), [], horizon_days=1).horizon_days == 1
    assert forecast(make_twin(), [], horizon_days=365).horizon_days == 365


# ------------------------------------------------------------ schema / tool

def test_to_dict_schema():
    twin = make_twin(current_balance="3000.00", safety_buffer="2500.00",
                     recurring=[rec("1000", "debit", date(2026, 9, 15))])
    d = forecast(twin, [], horizon_days=30).to_dict()
    assert set(d) == {
        "as_of", "horizon_days", "starting_balance", "projected_min_balance",
        "projected_min_balance_date", "projected_end_balance", "projected_income",
        "projected_expenses", "projected_net", "confidence", "events", "assumptions",
        "safety_buffer", "safety_buffer_breached", "breach_date", "projection",
    }
    assert d["confidence"] in {"low", "medium", "high"}
    assert set(d["events"][0]) == {"date", "direction", "amount", "label", "source", "confidence"}
    assert set(d["assumptions"][0]) == {
        "label", "direction", "amount", "cadence", "next_date", "source",
        "confidence", "occurrences_in_horizon", "observations", "note",
    }
    assert d["as_of"] == "2026-09-09"
    assert d["breach_date"] == "2026-09-15"


def test_tool_spec_shape():
    assert TOOL_SPEC["name"] == "forecast_cashflow"
    assert set(TOOL_SPEC["parameters"]["properties"]) == {"horizon_days", "as_of"}
