"""POST /api/simulation/what-if — auth, validation, schema. Repo faked."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import Account, Transaction, RecurringTransaction

AS_OF = "2026-09-09"


class FakeRepo:
    """opening 10000, no real transactions -> current_balance 10000;
    one recurring debit (id 7) of 1000 in 10 days."""

    def __init__(self):
        self.account = Account(1, Decimal("10000.00"), Decimal("2000.00"), date(2026, 9, 1))
        self.transactions = []
        self.recurring = [
            RecurringTransaction(id=7, student_id=1, label="Rent", merchant_name="LL",
                                 amount=Decimal("1000.00"), direction="debit", cadence="monthly",
                                 next_date=date(2026, 9, 19), day_of_month=19, active=True),
        ]
        self.budgets = {}

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        total = self.account.opening_balance
        for t in self.transactions:
            if as_of is None or t.payment_date <= as_of:
                total += t.signed_amount
        return total.quantize(Decimal("0.01"))

    def get_transactions(self, sid, start=None, end=None):
        return list(self.transactions)

    def get_recurring(self, sid, active_only=True):
        return list(self.recurring)

    def get_budgets(self, sid, month):
        return dict(self.budgets)


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr("routes.simulation.get_repository", lambda: repo)
    return repo


def _post(client, headers, body):
    return client.post("/api/simulation/what-if", json=body, headers=headers)


def test_requires_auth(client):
    assert client.post("/api/simulation/what-if", json={"type": "one_off_expense", "amount": "1"}).status_code == 401


def test_one_off_expense_happy_path(client, auth_headers, fake_repo):
    r = _post(client, auth_headers, {"type": "one_off_expense", "amount": "5000.00",
                                     "category": "Electronics", "as_of": AS_OF, "horizon_days": 30})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"scenario_input", "as_of", "horizon_days", "safety_buffer",
                         "baseline", "scenario", "comparison"}
    assert body["as_of"] == AS_OF
    assert body["baseline"]["starting_balance"] == "10000.00"
    # baseline dips to 9000 on the recurring date; scenario 5000 purchase today -> 4000
    assert body["baseline"]["min_balance"] == "9000.00"
    assert body["scenario"]["min_balance"] == "4000.00"
    assert body["comparison"]["min_balance_delta"] == "-5000.00"
    assert body["comparison"]["affordability_before"]["verdict"] in {"affordable", "tight", "not_affordable"}
    assert body["comparison"]["affordability_after"] is None
    for m in (body["safety_buffer"], body["baseline"]["min_balance"],
              body["comparison"]["end_balance_delta"]):
        assert isinstance(m, str) and len(m.split(".")[1]) == 2


def test_one_off_income_via_api(client, auth_headers, fake_repo):
    r = _post(client, auth_headers, {"type": "one_off_income", "amount": "3000", "as_of": AS_OF})
    assert r.status_code == 200
    assert r.get_json()["comparison"]["end_balance_delta"] == "3000.00"


def test_income_delta_via_api(client, auth_headers, fake_repo):
    r = _post(client, auth_headers, {"type": "income_delta", "monthly_amount": "3000",
                                     "as_of": AS_OF, "horizon_days": 70})
    assert r.status_code == 200
    assert r.get_json()["comparison"]["end_balance_delta"] == "9000.00"  # 3 monthly bumps


def test_recurring_modification_via_api(client, auth_headers, fake_repo):
    r = _post(client, auth_headers, {"type": "recurring_modification", "recurring_id": 7,
                                     "new_amount": "200", "as_of": AS_OF, "horizon_days": 30})
    assert r.status_code == 200
    body = r.get_json()
    assert body["baseline"]["min_balance"] == "9000.00"
    assert body["scenario"]["min_balance"] == "9800.00"


def test_recurring_modification_unknown_id_is_400(client, auth_headers, fake_repo):
    r = _post(client, auth_headers, {"type": "recurring_modification", "recurring_id": 999,
                                     "remove": True, "as_of": AS_OF})
    assert r.status_code == 400


@pytest.mark.parametrize("body", [
    {"type": "one_off_expense", "amount": "0"},
    {"type": "one_off_expense", "amount": "-1"},
    {"type": "one_off_expense"},
    {"type": "one_off_expense", "amount": "10", "date": "not-a-date"},
    {"type": "one_off_expense", "amount": "10", "as_of": "bad"},
    {"type": "one_off_expense", "amount": "10", "horizon_days": 9999},
    {"type": "one_off_expense", "amount": "10", "horizon_days": "lots"},
    {"type": "totally_unknown", "amount": "10"},
    {"amount": "10"},  # missing type
    {"type": "income_delta"},
])
def test_invalid_requests_are_400(client, auth_headers, fake_repo, body):
    assert _post(client, auth_headers, body).status_code == 400


def test_deterministic_via_api(client, auth_headers, fake_repo):
    body = {"type": "one_off_expense", "amount": "1234.56",
            "date": "2026-09-20", "as_of": AS_OF, "horizon_days": 45}
    a = _post(client, auth_headers, body).get_json()
    b = _post(client, auth_headers, body).get_json()
    assert a == b
