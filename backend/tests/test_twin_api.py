"""GET /api/twin/state — auth, shape, as_of handling. Repository is faked."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Account, Transaction, RecurringTransaction


class FakeRepo:
    def __init__(self):
        self.account = Account(1, Decimal("1000.00"), Decimal("300.00"), date(2026, 4, 1))
        self.transactions = [
            Transaction(id=1, student_id=1, amount=Decimal("5000.00"), direction="credit",
                        merchant_name="Allowance", category_id=8, category_name="Other",
                        payment_date=date(2026, 4, 1)),
            Transaction(id=2, student_id=1, amount=Decimal("400.00"), direction="debit",
                        merchant_name="Landlord", category_id=5, category_name="Rent",
                        payment_date=date(2026, 4, 2)),
            Transaction(id=3, student_id=1, amount=Decimal("120.00"), direction="debit",
                        merchant_name="Cafe", category_id=1, category_name="Food",
                        payment_date=date(2026, 4, 3)),
        ]
        self.recurring = [
            RecurringTransaction(id=1, student_id=1, label="Rent", merchant_name="Landlord",
                                 amount=Decimal("400.00"), direction="debit", cadence="monthly",
                                 next_date=date(2026, 4, 20), day_of_month=20, active=True),
        ]
        self.budgets = {"Food": Decimal("200.00")}

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        total = self.account.opening_balance
        for t in self.transactions:
            if as_of is None or t.payment_date <= as_of:
                total += t.signed_amount
        return total.quantize(Decimal("0.01"))

    def get_transactions(self, sid, start=None, end=None):
        return [t for t in self.transactions
                if (start is None or t.payment_date >= start)
                and (end is None or t.payment_date <= end)]

    def get_recurring(self, sid, active_only=True):
        return list(self.recurring)

    def get_budgets(self, sid, month):
        return dict(self.budgets)


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr("routes.twin.get_repository", lambda: repo)
    return repo


def test_requires_auth(client):
    assert client.get("/api/twin/state").status_code == 401


def test_returns_full_twin_shape(client, auth_headers, fake_repo):
    resp = client.get("/api/twin/state?as_of=2026-04-15", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ["student_id", "as_of", "month", "opening_balance", "current_balance",
                "month_income", "month_spending", "month_net",
                "month_discretionary_spending", "spending_by_category", "budgets",
                "recurring", "safety_buffer", "committed_upcoming",
                "committed_upcoming_horizon_days", "discretionary_buffer"]:
        assert key in body, key

    assert body["as_of"] == "2026-04-15"
    assert body["month"] == "2026-04"
    assert body["opening_balance"] == "1000.00"
    # 1000 + 5000 - 400 - 120
    assert body["current_balance"] == "5480.00"
    assert body["month_income"] == "5000.00"
    assert body["month_spending"] == "520.00"
    assert body["month_net"] == "4480.00"
    # Rent is essential; only Food (120) is discretionary
    assert body["month_discretionary_spending"] == "120.00"
    assert body["spending_by_category"] == {"Rent": "400.00", "Food": "120.00"}
    assert body["budgets"] == {"Food": "200.00"}
    assert body["safety_buffer"] == "300.00"
    assert body["committed_upcoming"] == "400.00"
    # 5480 - 400 - 300
    assert body["discretionary_buffer"] == "4780.00"
    assert isinstance(body["recurring"], list) and body["recurring"][0]["label"] == "Rent"
    # every money value is a 2dp string
    for v in [body["opening_balance"], body["current_balance"], body["month_net"],
              body["discretionary_buffer"], *body["spending_by_category"].values()]:
        assert isinstance(v, str) and v.split(".")[1] and len(v.split(".")[1]) == 2


def test_bad_as_of_is_400(client, auth_headers, fake_repo):
    resp = client.get("/api/twin/state?as_of=15-04-2026", headers=auth_headers)
    assert resp.status_code == 400


def test_default_as_of_is_today(client, auth_headers, fake_repo):
    resp = client.get("/api/twin/state", headers=auth_headers)
    assert resp.status_code == 200
    assert body_month_len(resp) == 7


def body_month_len(resp):
    return len(resp.get_json()["month"])
