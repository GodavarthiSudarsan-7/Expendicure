"""POST /api/affordability/check in `mode=decision`.

Asserts the route is a thin shell (auth, validate, load, call, serialise), that
the legacy affordability shape is untouched, and that the canonical decision
object reaches the wire intact. Repo is faked — no DB.
"""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Account, RecurringTransaction, SavingsGoal
from finance.money import money

AS_OF = date(2026, 10, 5)


class FakeRepo:
    def __init__(self, *, balance="10000.00", buffer="5000.00", recurring=None,
                 goals=None, **prefs):
        self.account = Account(1, money(balance), money(buffer), AS_OF, **prefs)
        self.recurring = list(recurring or [])
        self.goals = list(goals or [])
        self.transactions = []

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        return self.account.opening_balance

    def get_transactions(self, sid, start=None, end=None):
        return list(self.transactions)

    def get_recurring(self, sid, active_only=True):
        return list(self.recurring)

    def get_budgets(self, sid, month):
        return {}

    def get_savings_goals(self, sid, status=None):
        return list(self.goals)


def rec(label, amount, direction="debit", *, day=25, rid=1, flexibility="essential"):
    return RecurringTransaction(
        id=rid, student_id=1, label=label, merchant_name=label,
        amount=Decimal(str(amount)), direction=direction, cadence="monthly",
        next_date=date(2026, 10, day), day_of_month=day, weekday=None,
        active=True, flexibility=flexibility,
    )


@pytest.fixture
def repo(monkeypatch):
    holder = {}

    def install(r):
        holder["repo"] = r
        monkeypatch.setattr("routes.affordability.get_repository", lambda: r)
        return r

    install(FakeRepo())
    return install


def post(client, headers, **body):
    body.setdefault("as_of", AS_OF.isoformat())
    return client.post("/api/affordability/check", json=body, headers=headers)


# ------------------------------------------------------------ backward compat

def test_requires_auth(client, repo):
    assert client.post("/api/affordability/check", json={"amount": "100"}).status_code == 401


def test_default_mode_returns_the_unchanged_affordability_shape(client, auth_headers, repo):
    r = post(client, auth_headers, amount="1000")
    assert r.status_code == 200
    body = r.get_json()
    assert "verdict" in body and "score" in body
    assert "affordability_status" not in body       # NOT the decision object


def test_explicit_affordability_mode_matches_the_default(client, auth_headers, repo):
    a = post(client, auth_headers, amount="1000").get_json()
    b = post(client, auth_headers, amount="1000", mode="affordability").get_json()
    assert a == b


def test_unknown_mode_is_rejected(client, auth_headers, repo):
    assert post(client, auth_headers, amount="1000", mode="wishful").status_code == 400


# -------------------------------------------------------- the decision object

CANONICAL_KEYS = {
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation", "requested_amount", "request_date",
    "desired_completion_date", "currency", "minimum_balance_required",
    "minimum_projected_balance", "minimum_projected_balance_date",
    "forecast_horizon_days", "safety_check_passed", "safety_failure_reasons",
    "candidate_plans", "selected_plan", "goal_impact", "baseline_check",
    "invariant_violations",
}


def test_decision_mode_returns_the_canonical_object(client, auth_headers, repo):
    repo(FakeRepo(balance="300000.00", buffer="20000.00"))
    r = post(client, auth_headers, amount="60000", mode="decision")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == CANONICAL_KEYS
    assert body["affordability_status"] == "affordable_now"
    assert body["recommended_payment_method"] == "full_payment"
    assert body["amount_safe_to_pay"] == "60000.00"
    assert body["currency"] == "INR"
    assert body["forecast_horizon_days"] == 90


def test_decision_mode_reflects_the_users_own_recurring_commitments(client, auth_headers, repo):
    repo(FakeRepo(balance="10000.00", buffer="5000.00",
                  recurring=[rec("Salary", 40_000, "credit", day=25)]))
    body = post(client, auth_headers, amount="40000", mode="decision").get_json()
    assert body["affordability_status"] == "affordable_with_plan"
    assert body["recommended_payment_method"] == "partial_payment"
    assert body["amount_safe_to_pay"] == "5000.00"
    assert len(body["payment_plan"]["payments"]) == 2


def test_decision_mode_is_user_scoped(client, auth_headers, repo):
    """Identity comes from the token; a body-supplied id is ignored."""
    seen = {}
    r = FakeRepo(balance="300000.00", buffer="20000.00")
    real = r.get_savings_goals

    def spy(sid, status=None):
        seen["sid"] = sid
        return real(sid, status)

    r.get_savings_goals = spy
    repo(r)
    post(client, auth_headers, amount="1000", mode="decision", student_id=999, user_id=999)
    assert seen["sid"] == 1


def test_goals_are_loaded_and_goal_impact_is_populated(client, auth_headers, repo):
    g = SavingsGoal(id=7, student_id=1, name="Laptop", target_amount=money(100_000),
                    current_amount=money(80_000), monthly_contribution=money(5_000),
                    target_date=date(2027, 6, 1), status="active")
    repo(FakeRepo(balance="300000.00", buffer="20000.00", goals=[g]))
    body = post(client, auth_headers, amount="50000", mode="decision").get_json()
    assert body["goal_impact"]["available"] is True
    assert body["goal_impact"]["goal_name"] == "Laptop"


def test_explanation_facts_are_serialised(client, auth_headers, repo):
    repo(FakeRepo(balance="300000.00", buffer="20000.00"))
    body = post(client, auth_headers, amount="60000", mode="decision").get_json()
    facts = {f["code"]: f["value"] for f in body["decision_explanation"]}
    assert facts["requested_amount"] == "60000.00"
    assert facts["minimum_balance"] == "20000.00"
    assert facts["spending_changes"] == "none"
    for f in body["decision_explanation"]:
        assert set(f) == {"code", "label", "value", "kind"}


# ------------------------------------------------------- supplied EMI options

def test_installment_options_are_accepted_and_evaluated(client, auth_headers, repo):
    repo(FakeRepo(balance="5000.00", buffer="1000.00",
                  recurring=[rec("Salary", 10_000, "credit", day=20, rid=1),
                             rec("Rent", 8_000, day=22, rid=2)],
                  accepts_installments=True, accepts_partial_payment=False))
    body = post(client, auth_headers, amount="9000", mode="decision",
                installment_options=[{
                    "option_id": "emi3", "first_payment_date": "2026-10-21",
                    "number_of_payments": 3, "payment_amount": "3000",
                    "total_payable": "9000", "interval_days": 30,
                }]).get_json()
    assert body["recommended_payment_method"] == "installments"
    assert body["payment_plan"]["option_id"] == "emi3"
    assert len(body["payment_plan"]["payments"]) == 3


@pytest.mark.parametrize("bad", [
    "notalist",
    [{"number_of_payments": 3, "payment_amount": "1", "total_payable": "3"}],      # no date
    [{"first_payment_date": "2026-10-21", "payment_amount": "1"}],                 # no count
    [{"first_payment_date": "nope", "number_of_payments": 3,
      "payment_amount": "1", "total_payable": "3"}],
    [{"first_payment_date": "2026-10-21", "number_of_payments": 0,
      "payment_amount": "1", "total_payable": "3"}],
    [{"first_payment_date": "2026-10-21", "number_of_payments": 3,
      "payment_amount": "-5", "total_payable": "3"}],
    [{"first_payment_date": "2026-10-21", "number_of_payments": 3,
      "payment_amount": "1", "total_payable": "3", "interval_days": 0}],
])
def test_malformed_installment_options_are_400_never_500(client, auth_headers, repo, bad):
    r = post(client, auth_headers, amount="1000", mode="decision", installment_options=bad)
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_too_many_installment_options_rejected(client, auth_headers, repo):
    opt = {"first_payment_date": "2026-10-21", "number_of_payments": 3,
           "payment_amount": "1", "total_payable": "3"}
    r = post(client, auth_headers, amount="1000", mode="decision",
             installment_options=[opt] * 11)
    assert r.status_code == 400


# ------------------------------------------------------------- input validation

def test_amount_is_required(client, auth_headers, repo):
    assert post(client, auth_headers, mode="decision").status_code == 400


@pytest.mark.parametrize("body,field", [
    ({"amount": "abc"}, "amount"),
    ({"amount": "0"}, "amount"),
    ({"amount": "-5"}, "amount"),
    ({"amount": "100", "desired_completion_date": "soon"}, "desired_completion_date"),
    ({"amount": "100", "horizon_days": "many"}, "horizon_days"),
    ({"amount": "100", "horizon_days": 0}, "horizon_days"),
    ({"amount": "100", "horizon_days": 999}, "horizon_days"),
    ({"amount": "100", "minimum_balance": "lots"}, "minimum_balance"),
    ({"amount": "100", "minimum_balance": "-1"}, "minimum_balance"),
    ({"amount": "100", "goal_id": "seven"}, "goal_id"),
])
def test_malformed_decision_input_is_400_never_500(client, auth_headers, repo, body, field):
    r = post(client, auth_headers, mode="decision", **body)
    assert r.status_code == 400, f"{field} should have been rejected"
    assert "error" in r.get_json()


def test_deadline_and_minimum_balance_reach_the_engine(client, auth_headers, repo):
    repo(FakeRepo(balance="100000.00", buffer="20000.00"))
    body = post(client, auth_headers, amount="90000", mode="decision",
                minimum_balance="80000", desired_completion_date="2026-12-31").get_json()
    assert body["minimum_balance_required"] == "80000.00"
    assert body["desired_completion_date"] == "2026-12-31"
    assert body["amount_safe_to_pay"] == "20000.00"


def test_not_affordable_is_a_200_with_a_null_plan_not_an_error(client, auth_headers, repo):
    repo(FakeRepo(balance="20000.00", buffer="10000.00",
                  accepts_partial_payment=False, allows_flexible_cuts=False))
    r = post(client, auth_headers, amount="500000", mode="decision")
    assert r.status_code == 200
    body = r.get_json()
    assert body["affordability_status"] == "not_affordable"
    assert body["payment_plan"] is None
    assert body["safety_check_passed"] is False


# ----------------------------------------------------- the route stays a shell

def test_route_module_contains_no_financial_arithmetic():
    import inspect
    import re
    import routes.affordability as mod

    body = re.sub(r'""".*?"""', "", inspect.getsource(mod), flags=re.S)
    body = "\n".join(l.split("#")[0] for l in body.splitlines())
    # no money()/Decimal() wrapped around an expression doing arithmetic
    assert [l.strip() for l in body.splitlines()
            if re.search(r"money\([^)]*[-*/]", l)] == []
    # the only subtraction permitted is the history window (a date, not money)
    arith = [l.strip() for l in body.splitlines() if " - " in l]
    assert all("timedelta" in l for l in arith), arith
