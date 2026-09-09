"""POST /api/affordability/check — auth, validation, structured body. Repo faked."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Account, Transaction, RecurringTransaction


class FakeRepo:
    """Enough to build a twin: opening 3000, one 400 debit -> current 2600."""

    def __init__(self):
        self.account = Account(1, Decimal("3000.00"), Decimal("2000.00"), date(2026, 9, 1))
        self.transactions = [
            Transaction(id=1, student_id=1, amount=Decimal("400.00"), direction="debit",
                        merchant_name="Shop", category_id=1, category_name="Food",
                        payment_date=date(2026, 9, 3)),
        ]
        self.recurring = []
        self.budgets = {"Food": Decimal("100.00")}

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
    monkeypatch.setattr("routes.affordability.get_repository", lambda: repo)
    return repo


def test_requires_auth(client):
    assert client.post("/api/affordability/check", json={"amount": 100}).status_code == 401


def test_missing_amount_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check", json={}, headers=auth_headers)
    assert r.status_code == 400


def test_zero_amount_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check", json={"amount": 0}, headers=auth_headers)
    assert r.status_code == 400


def test_negative_amount_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check", json={"amount": -10}, headers=auth_headers)
    assert r.status_code == 400


def test_bad_as_of_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 100, "as_of": "09-09-2026"}, headers=auth_headers)
    assert r.status_code == 400


def test_bad_date_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 100, "date": "nope"}, headers=auth_headers)
    assert r.status_code == 400


def test_bad_horizon_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 100, "horizon_days": "lots"}, headers=auth_headers)
    assert r.status_code == 400
    r2 = client.post("/api/affordability/check",
                     json={"amount": 100, "horizon_days": 9999}, headers=auth_headers)
    assert r2.status_code == 400


def test_past_purchase_date_is_400(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 100, "as_of": "2026-09-09", "date": "2026-09-01"},
                    headers=auth_headers)
    assert r.status_code == 400


def test_happy_path_structured_result(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 4000, "category": "Electronics", "as_of": "2026-09-09"},
                    headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    # current_balance 2600, buffer 2000, amount 4000 -> min -1400
    assert body["current_balance"] == "2600.00"
    assert body["projected_min_balance"] == "-1400.00"
    assert body["verdict"] == "not_affordable"
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert "safety_buffer" in body["breaches"] and "overdraft" in body["breaches"]
    assert body["category"] == "Electronics"
    for k in ("amount", "projected_min_balance", "safety_buffer", "current_balance"):
        assert isinstance(body[k], str) and len(body[k].split(".")[1]) == 2


def test_affordable_case_via_api(client, auth_headers, fake_repo):
    r = client.post("/api/affordability/check",
                    json={"amount": 50, "as_of": "2026-09-09"}, headers=auth_headers)
    body = r.get_json()
    # current 2600, buffer 2000, amount 50 -> min 2550, margin 550 >= 10% of 50 -> affordable
    assert body["projected_min_balance"] == "2550.00"
    assert body["verdict"] == "affordable"
