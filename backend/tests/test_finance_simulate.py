"""Unit tests for the deterministic what-if simulator. Pure — no DB, no LLM."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import RecurringTransaction
from finance.twin import TwinState
from finance.simulate import simulate, build_scenario, Scenario

AS_OF = date(2026, 9, 9)
D = Decimal


def make_twin(*, current_balance="10000.00", safety_buffer="2000.00", recurring=(),
              budgets=None, spending_by_category=None, committed_upcoming="0.00",
              discretionary_buffer=None, as_of=AS_OF):
    cb = D(current_balance)
    sb = D(safety_buffer)
    if discretionary_buffer is None:
        discretionary_buffer = cb - D(committed_upcoming) - sb
    return TwinState(
        student_id=1, as_of=as_of, month=f"{as_of.year:04d}-{as_of.month:02d}",
        opening_balance=D("0.00"), current_balance=cb,
        month_income=D("0.00"), month_spending=D("0.00"), month_net=D("0.00"),
        month_discretionary_spending=D("0.00"),
        spending_by_category=dict(spending_by_category or {}),
        budgets=dict(budgets or {}), recurring=tuple(recurring),
        safety_buffer=sb, committed_upcoming=D(committed_upcoming),
        committed_upcoming_horizon_days=30, discretionary_buffer=D(discretionary_buffer),
    )


def rec(amount, direction, next_date, *, rid=1):
    return RecurringTransaction(
        id=rid, student_id=1, label=f"rec{rid}", merchant_name="M",
        amount=D(str(amount)), direction=direction, cadence="monthly",
        next_date=next_date, day_of_month=next_date.day, active=True,
    )


# ------------------------------------------------------------------- baseline

def test_baseline_matches_plain_projection_and_is_scenario_independent():
    twin = make_twin(current_balance="5000.00",
                     recurring=[rec("1000", "debit", AS_OF + timedelta(days=10))])
    r1 = simulate(twin, {"type": "one_off_expense", "amount": "100"}, horizon_days=30)
    r2 = simulate(twin, {"type": "one_off_income", "amount": "999"}, horizon_days=30)
    assert r1.baseline.to_dict() == r2.baseline.to_dict()
    # baseline: 5000 flat then -1000 on day 10
    assert r1.baseline.min_balance == D("4000.00")
    assert r1.baseline.min_balance_date == AS_OF + timedelta(days=10)
    assert r1.baseline.end_balance == D("4000.00")


# ---------------------------------------------------------------- one-off

def test_one_off_expense_lowers_min_and_end_by_amount():
    twin = make_twin(current_balance="10000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "5000.00"}, horizon_days=30)
    assert r.scenario_side.min_balance == D("5000.00")
    assert r.min_balance_delta == D("-5000.00")
    assert r.end_balance_delta == D("-5000.00")


def test_one_off_income_raises_min_and_end_by_amount():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00")
    r = simulate(twin, {"type": "one_off_income", "amount": "5000.00"}, horizon_days=30)
    assert r.min_balance_delta == D("5000.00")
    assert r.end_balance_delta == D("5000.00")


def test_purchase_exactly_on_as_of():
    twin = make_twin(current_balance="3000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "1000", "date": AS_OF.isoformat()},
                 horizon_days=30)
    assert r.scenario_side.projection[0].balance == D("2000.00")
    assert r.scenario_side.min_balance_date == AS_OF


def test_future_purchase_within_horizon():
    twin = make_twin(current_balance="3000.00")
    d = AS_OF + timedelta(days=20)
    r = simulate(twin, {"type": "one_off_expense", "amount": "1000", "date": d.isoformat()},
                 horizon_days=30)
    # baseline flat 3000 until day 20; scenario dips to 2000 on day 20
    assert r.baseline.min_balance == D("3000.00")
    assert r.scenario_side.min_balance == D("2000.00")
    assert r.scenario_side.min_balance_date == d


def test_purchase_beyond_original_horizon_extends_projection():
    twin = make_twin(current_balance="3000.00")
    d = AS_OF + timedelta(days=90)
    r = simulate(twin, {"type": "one_off_expense", "amount": "1000", "date": d.isoformat()},
                 horizon_days=30)
    assert r.horizon_days == 90
    assert r.baseline.projection[-1].date == d
    assert r.scenario_side.projection[-1].date == d
    assert r.scenario_side.min_balance == D("2000.00")


# -------------------------------------------------------- recurring scenarios

def test_recurring_expense_monthly_occurrences_within_horizon():
    twin = make_twin(current_balance="10000.00")
    r = simulate(twin, {"type": "recurring_expense", "amount": "1000", "cadence": "monthly",
                        "start_date": AS_OF.isoformat()}, horizon_days=70)
    # occurrences: 09-09, 10-09, 11-09  -> 3 x 1000
    assert r.end_balance_delta == D("-3000.00")
    assert r.scenario_side.min_balance == D("7000.00")


def test_recurring_income_weekly_occurrences():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00")
    r = simulate(twin, {"type": "recurring_income", "amount": "100", "cadence": "weekly",
                        "start_date": AS_OF.isoformat()}, horizon_days=21)
    # weekly from as_of within 21 days: day 0, 7, 14, 21 -> 4 x 100
    assert r.end_balance_delta == D("400.00")


def test_recurring_expense_respects_end_date():
    twin = make_twin(current_balance="10000.00")
    r = simulate(twin, {"type": "recurring_expense", "amount": "1000", "cadence": "monthly",
                        "start_date": AS_OF.isoformat(),
                        "end_date": (AS_OF + timedelta(days=20)).isoformat()}, horizon_days=70)
    # only the 09-09 occurrence falls on/before the end_date
    assert r.end_balance_delta == D("-1000.00")


def test_income_delta_monthly():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00")
    r = simulate(twin, {"type": "income_delta", "monthly_amount": "3000"}, horizon_days=70)
    # +3000 on 09-09, 10-09, 11-09
    assert r.end_balance_delta == D("9000.00")
    assert r.min_balance_delta == D("3000.00")  # first bump raises the (flat) minimum


# --------------------------------------------------- recurring modification

def test_recurring_modification_new_amount():
    twin = make_twin(current_balance="5000.00",
                     recurring=[rec("1000", "debit", AS_OF + timedelta(days=5), rid=7)])
    r = simulate(twin, {"type": "recurring_modification", "recurring_id": 7,
                        "new_amount": "300"}, horizon_days=30)
    # baseline dips to 4000; scenario only to 4700
    assert r.baseline.min_balance == D("4000.00")
    assert r.scenario_side.min_balance == D("4700.00")
    assert r.min_balance_delta == D("700.00")


def test_recurring_modification_remove():
    twin = make_twin(current_balance="5000.00",
                     recurring=[rec("1000", "debit", AS_OF + timedelta(days=5), rid=7)])
    r = simulate(twin, {"type": "recurring_modification", "recurring_id": 7, "remove": True},
                 horizon_days=30)
    assert r.scenario_side.min_balance == D("5000.00")
    assert r.min_balance_delta == D("1000.00")


def test_recurring_modification_unknown_id_raises():
    twin = make_twin(recurring=[rec("1000", "debit", AS_OF + timedelta(days=5), rid=7)])
    with pytest.raises(ValueError):
        simulate(twin, {"type": "recurring_modification", "recurring_id": 999, "remove": True})


def test_recurring_modification_no_change_raises():
    twin = make_twin(recurring=[rec("1000", "debit", AS_OF + timedelta(days=5), rid=7)])
    with pytest.raises(ValueError):
        simulate(twin, {"type": "recurring_modification", "recurring_id": 7})


# ------------------------------------------------------------- comparison

def test_multiple_events_on_same_date_sum():
    # scenario recurring expense whose first occurrence coincides with an
    # existing twin recurring item's date
    d = AS_OF + timedelta(days=5)
    twin = make_twin(current_balance="10000.00", recurring=[rec("400", "debit", d, rid=1)])
    r = simulate(twin, {"type": "recurring_expense", "amount": "600", "cadence": "monthly",
                        "start_date": d.isoformat()}, horizon_days=20)
    # day 5: baseline -400 -> 9600 ; scenario -400 -600 -> 9000
    assert r.baseline.min_balance == D("9600.00")
    assert r.scenario_side.min_balance == D("9000.00")


def test_safety_buffer_impact_none():
    twin = make_twin(current_balance="10000.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "100"})
    assert r.safety_buffer_impact == "none"


def test_safety_buffer_impact_breached():
    twin = make_twin(current_balance="3000.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "2000"})  # min -> 1000
    assert r.safety_buffer_impact == "breached"


def test_safety_buffer_impact_restored():
    twin = make_twin(current_balance="1000.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_income", "amount": "5000"})  # min -> 6000
    assert r.safety_buffer_impact == "restored"


def test_safety_buffer_impact_deepened():
    twin = make_twin(current_balance="1500.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "500"})  # 1500 -> 1000, both < 2000
    assert r.safety_buffer_impact == "deepened"


def test_safety_buffer_impact_eased():
    twin = make_twin(current_balance="1000.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_income", "amount": "500"})  # 1000 -> 1500, both < 2000
    assert r.safety_buffer_impact == "eased"


# ------------------------------------------------------------- affordability

def test_affordability_before_populated_for_one_off_expense():
    twin = make_twin(current_balance="4000.00", safety_buffer="2000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "4000", "category": "Electronics"})
    assert r.affordability_before is not None
    assert r.affordability_before["verdict"] == "not_affordable"
    assert r.affordability_before["score"] == 25
    assert r.affordability_after is None


def test_affordability_none_for_non_purchase_scenarios():
    twin = make_twin()
    for scenario in (
        {"type": "one_off_income", "amount": "100"},
        {"type": "income_delta", "monthly_amount": "100"},
        {"type": "recurring_expense", "amount": "100", "cadence": "monthly"},
    ):
        r = simulate(twin, scenario)
        assert r.affordability_before is None
        assert r.affordability_after is None


# ----------------------------------------------------------- horizon / precision

def test_horizon_boundary_occurrence_on_last_day_included():
    twin = make_twin(current_balance="10000.00")
    d = AS_OF + timedelta(days=30)
    r = simulate(twin, {"type": "one_off_expense", "amount": "1000", "date": d.isoformat()},
                 horizon_days=30)
    assert r.scenario_side.projection[-1].date == d
    assert r.scenario_side.min_balance == D("9000.00")


def test_decimal_precision_two_places_everywhere():
    twin = make_twin(current_balance="1000.00", safety_buffer="0.00")
    r = simulate(twin, {"type": "recurring_expense", "amount": "0.10", "cadence": "weekly",
                        "start_date": AS_OF.isoformat()}, horizon_days=21)
    d = r.to_dict()
    monies = [d["baseline"]["min_balance"], d["scenario"]["min_balance"],
              d["comparison"]["min_balance_delta"], d["comparison"]["end_balance_delta"],
              d["safety_buffer"]]
    for p in d["scenario"]["projection"]:
        monies.append(p["balance"])
    for m in monies:
        assert isinstance(m, str) and len(m.split(".")[1]) == 2


def test_horizon_zero():
    twin = make_twin(current_balance="1000.00")
    r = simulate(twin, {"type": "one_off_expense", "amount": "100"}, horizon_days=0)
    assert len(r.scenario_side.projection) == 1
    assert r.scenario_side.projection[0].balance == D("900.00")


# ------------------------------------------------------------- invalid input

@pytest.mark.parametrize("scenario", [
    {"type": "one_off_expense", "amount": "0"},
    {"type": "one_off_expense", "amount": "-5"},
    {"type": "one_off_expense", "amount": "abc"},
    {"type": "one_off_expense"},  # missing amount
    {"type": "one_off_expense", "amount": "10", "date": "09-09-2026"},
    {"type": "one_off_expense", "amount": "10", "date": "2026-09-08"},  # before as_of
    {"type": "bogus_type", "amount": "10"},
    {"type": "recurring_expense", "amount": "10", "cadence": "yearly"},
    {"type": "recurring_expense", "amount": "10", "cadence": "monthly", "day_of_month": 40},
    {"type": "income_delta"},  # missing monthly_amount
    {"type": "income_delta", "monthly_amount": "0"},
    {"type": "income_delta", "monthly_amount": "-100"},
    {},  # missing type
])
def test_invalid_scenarios_raise_value_error(scenario):
    with pytest.raises(ValueError):
        simulate(make_twin(), scenario)


@pytest.mark.parametrize("horizon", [-1, 366, "lots", 1.5])
def test_invalid_horizon_raises(horizon):
    with pytest.raises(ValueError):
        simulate(make_twin(), {"type": "one_off_expense", "amount": "10"}, horizon_days=horizon)


def test_float_amount_rejected():
    with pytest.raises(ValueError):
        simulate(make_twin(), {"type": "one_off_expense", "amount": 100.5})


# ------------------------------------------------------------- misc

def test_simulate_has_no_repository_or_db_handle():
    import inspect
    sig = inspect.signature(simulate)
    assert list(sig.parameters)[0] == "twin"          # takes a value object, not a repo
    src = inspect.getsource(simulate)
    assert "execute_query" not in src and "get_repository" not in src


def test_deterministic_repeated_simulations():
    twin = make_twin(current_balance="3333.33", safety_buffer="1234.56",
                     recurring=[rec("777.77", "debit", AS_OF + timedelta(days=3), rid=2)])
    scenario = {"type": "recurring_modification", "recurring_id": 2, "new_amount": "500.00"}
    a = simulate(twin, scenario, horizon_days=45).to_dict()
    b = simulate(twin, scenario, horizon_days=45).to_dict()
    assert a == b


def test_to_dict_schema():
    twin = make_twin()
    d = simulate(twin, {"type": "one_off_expense", "amount": "5000", "category": "Electronics",
                        "date": (AS_OF + timedelta(days=11)).isoformat()}, horizon_days=30).to_dict()
    assert set(d) == {"scenario_input", "as_of", "horizon_days", "safety_buffer",
                      "baseline", "scenario", "comparison"}
    for side in ("baseline", "scenario"):
        assert set(d[side]) == {"starting_balance", "min_balance", "min_balance_date",
                                "end_balance", "projection"}
    assert set(d["comparison"]) == {"min_balance_delta", "end_balance_delta",
                                    "affordability_before", "affordability_after",
                                    "safety_buffer_impact", "changes"}
    assert d["scenario_input"]["type"] == "one_off_expense"
    assert d["scenario_input"]["amount"] == "5000.00"
    assert isinstance(d["comparison"]["changes"], list) and d["comparison"]["changes"]


def test_build_scenario_normalizes():
    s = build_scenario({"type": "one_off_expense", "amount": 5000, "category": "  X  "},
                       as_of=AS_OF)
    assert isinstance(s, Scenario)
    assert s.amount == D("5000.00")
    assert s.category == "X"
    assert s.date == AS_OF
