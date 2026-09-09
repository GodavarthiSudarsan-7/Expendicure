"""GET /api/forecast — auth, validation, schema. Repo faked."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Account, RecurringTransaction, Transaction


class FakeRepo:
    def __init__(self):
        self.account = Account(1, Decimal("10000.00"), Decimal("2000.00"), date(2026, 9, 1))
        self.recurring = [
            RecurringTransaction(id=1, student_id=1, label="Rent", merchant_name="Landlord",
                                 amount=Decimal("1000.00"), direction="debit", cadence="monthly",
                                 next_date=date(2026, 9, 19), day_of_month=19, weekday=None,
                                 active=True),
        ]
        self.transactions = []

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        return self.account.opening_balance

    def get_transactions(self, sid, start=None, end=None):
        return [t for t in self.transactions
                if (start is None or t.payment_date >= start)
                and (end is None or t.payment_date <= end)]

    def get_recurring(self, sid, active_only=True):
        return list(self.recurring)

    def get_budgets(self, sid, month):
        return {}


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr("routes.forecast.get_repository", lambda: repo)
    return repo


def test_requires_auth(client):
    assert client.get("/api/forecast").status_code == 401


def test_happy_path_schema(client, auth_headers, fake_repo):
    r = client.get("/api/forecast?as_of=2026-09-09&horizon_days=40", headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {
        "as_of", "horizon_days", "starting_balance", "projected_min_balance",
        "projected_min_balance_date", "projected_end_balance", "projected_income",
        "projected_expenses", "projected_net", "confidence", "events", "assumptions",
        "safety_buffer", "safety_buffer_breached", "breach_date", "projection",
    }
    assert body["as_of"] == "2026-09-09"
    assert body["horizon_days"] == 40
    assert body["starting_balance"] == "10000.00"
    # rent 09-19 and 10-19 within 40d
    assert [e["date"] for e in body["events"]] == ["2026-09-19", "2026-10-19"]
    assert body["projected_expenses"] == "2000.00"
    assert body["projected_min_balance"] == "8000.00"
    assert body["confidence"] == "high"
    assert body["safety_buffer_breached"] is False
    for m in (body["starting_balance"], body["projected_min_balance"], body["projected_net"]):
        assert isinstance(m, str) and len(m.split(".")[1]) == 2


def test_default_horizon_is_30(client, auth_headers, fake_repo):
    r = client.get("/api/forecast?as_of=2026-09-09", headers=auth_headers)
    assert r.get_json()["horizon_days"] == 30


def test_default_as_of_is_today(client, auth_headers, fake_repo):
    r = client.get("/api/forecast", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.get_json()["as_of"]) == 10


@pytest.mark.parametrize("qs", [
    "?horizon_days=0",
    "?horizon_days=-5",
    "?horizon_days=366",
    "?horizon_days=lots",
    "?horizon_days=1.5",
    "?as_of=09-09-2026",
    "?as_of=not-a-date",
])
def test_invalid_query_is_400(client, auth_headers, fake_repo, qs):
    assert client.get(f"/api/forecast{qs}", headers=auth_headers).status_code == 400


def test_deterministic_via_api(client, auth_headers, fake_repo):
    a = client.get("/api/forecast?as_of=2026-09-09&horizon_days=60", headers=auth_headers).get_json()
    b = client.get("/api/forecast?as_of=2026-09-09&horizon_days=60", headers=auth_headers).get_json()
    assert a == b
