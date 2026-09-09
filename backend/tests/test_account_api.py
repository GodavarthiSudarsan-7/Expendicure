"""/api/account — GET defaults, PUT validation, derived current_balance.
DB layer is stubbed; no MySQL."""

from datetime import date
from decimal import Decimal

import pytest


class FakeDB:
    """Minimal in-memory stand-in for the two tables the account route touches."""

    def __init__(self):
        self.account_row = None  # dict or None
        self.txn_totals = []     # list of {"direction","total"}

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select student_id, opening_balance"):
            return dict(self.account_row) if self.account_row else None
        if s.startswith("select id from accounts where student_id"):
            return {"id": 1} if self.account_row else None
        if s.startswith("select direction, coalesce(sum(amount), 0) as total"):
            return list(self.txn_totals)
        if s.startswith("insert into accounts"):
            self.account_row = {
                "student_id": params[0],
                "opening_balance": params[1],
                "safety_buffer": params[2],
                "as_of_date": date.fromisoformat(params[3]),
            }
            return 1
        if s.startswith("update accounts set"):
            # params = [*values, student_id]; reflect them onto the row
            return 1
        raise AssertionError(f"unexpected query: {s}")


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr("routes.account.execute_query", fake.execute_query)
    monkeypatch.setattr("finance_db.execute_query", fake.execute_query)
    return fake


def test_get_account_defaults_when_absent(client, auth_headers, db):
    resp = client.get("/api/account", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["exists"] is False
    assert body["opening_balance"] == "0.00"
    assert body["current_balance"] == "0.00"
    assert body["safety_buffer"] == "2000.00"  # Config.SAFETY_BUFFER default


def test_get_account_current_balance_uses_transactions(client, auth_headers, db):
    db.account_row = {
        "student_id": 1, "opening_balance": "1000.00", "safety_buffer": "200.00",
        "as_of_date": date(2026, 4, 1),
    }
    db.txn_totals = [
        {"direction": "credit", "total": Decimal("5000.00")},
        {"direction": "debit", "total": Decimal("1200.00")},
    ]
    resp = client.get("/api/account", headers=auth_headers)
    body = resp.get_json()
    assert body["exists"] is True
    assert body["current_balance"] == "4800.00"  # 1000 + 5000 - 1200


def test_put_account_creates_row(client, auth_headers, db):
    resp = client.put(
        "/api/account",
        json={"opening_balance": "1500", "safety_buffer": "300", "as_of_date": "2026-04-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert db.account_row is not None
    assert resp.get_json()["opening_balance"] == "1500.00"


def test_put_account_rejects_negative(client, auth_headers, db):
    resp = client.put("/api/account", json={"opening_balance": "-5"}, headers=auth_headers)
    assert resp.status_code == 400


def test_put_account_rejects_bad_date(client, auth_headers, db):
    resp = client.put("/api/account", json={"as_of_date": "01/04/2026"}, headers=auth_headers)
    assert resp.status_code == 400


def test_put_account_rejects_non_numeric(client, auth_headers, db):
    resp = client.put("/api/account", json={"safety_buffer": "abc"}, headers=auth_headers)
    assert resp.status_code == 400


def test_account_requires_auth(client):
    assert client.get("/api/account").status_code == 401
    assert client.put("/api/account", json={}).status_code == 401
