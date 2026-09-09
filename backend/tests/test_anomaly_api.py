"""GET /api/anomalies - auth, validation, schema. Repo faked."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from finance.models import Category, Transaction

AS_OF = date(2026, 9, 30)


def txn(amount, direction, days_before, *, merchant="Acme", cid=1, cname="Food", tid=1):
    return Transaction(
        id=tid, student_id=1, amount=Decimal(str(amount)), direction=direction,
        merchant_name=merchant, category_id=cid, category_name=cname,
        payment_date=AS_OF - timedelta(days=days_before),
    )


class FakeRepo:
    def __init__(self):
        # 5 historical debit peers of 100, one recent 400 -> amount_outlier high
        self.transactions = [txn("100", "debit", 20 + i, merchant=f"H{i}", tid=10 + i) for i in range(5)]
        self.transactions.append(txn("400", "debit", 1, merchant="Shop", tid=99))
        self.transactions.append(txn("600", "debit", 2, cname="Food", tid=100))  # budget_breach
        self.budgets = {"Food": Decimal("500")}
        self.categories = [Category(id=1, name="Food", is_default=True, student_id=None)]

    def get_transactions(self, sid, start=None, end=None):
        return [t for t in self.transactions
                if (start is None or t.payment_date >= start)
                and (end is None or t.payment_date <= end)]

    def get_budgets(self, sid, month):
        return dict(self.budgets)

    def get_categories(self, sid):
        return list(self.categories)

    # not used by the anomaly route but present on the real repo
    def get_account(self, sid):
        return None

    def compute_current_balance(self, sid, as_of=None):
        return Decimal("0.00")

    def get_recurring(self, sid, active_only=True):
        return []


@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr("routes.anomaly.get_repository", lambda: repo)
    return repo


def test_requires_auth(client):
    assert client.get("/api/anomalies").status_code == 401


def test_happy_path_schema(client, auth_headers, fake_repo):
    r = client.get("/api/anomalies?as_of=2026-09-30&history_days=90", headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"as_of", "history_days", "anomalies", "count",
                         "high_count", "medium_count", "low_count"}
    assert body["as_of"] == "2026-09-30"
    assert body["history_days"] == 90
    found = {a["type"] for a in body["anomalies"]}
    assert "amount_outlier" in found and "budget_breach" in found
    assert body["count"] == len(body["anomalies"])
    assert body["count"] == body["high_count"] + body["medium_count"] + body["low_count"]
    for a in body["anomalies"]:
        for k, v in a.items():
            if k in ("amount", "historical_median", "spent", "budget", "over_by"):
                assert isinstance(v, str) and len(v.split(".")[1]) == 2


def test_default_history_days_is_90(client, auth_headers, fake_repo):
    r = client.get("/api/anomalies?as_of=2026-09-30", headers=auth_headers)
    assert r.get_json()["history_days"] == 90


def test_default_as_of_is_today(client, auth_headers, fake_repo):
    r = client.get("/api/anomalies", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.get_json()["as_of"]) == 10


@pytest.mark.parametrize("qs", [
    "?history_days=0",
    "?history_days=-5",
    "?history_days=6",
    "?history_days=366",
    "?history_days=lots",
    "?history_days=1.5",
    "?as_of=30-09-2026",
    "?as_of=not-a-date",
])
def test_invalid_query_is_400(client, auth_headers, fake_repo, qs):
    assert client.get(f"/api/anomalies{qs}", headers=auth_headers).status_code == 400


def test_deterministic_via_api(client, auth_headers, fake_repo):
    a = client.get("/api/anomalies?as_of=2026-09-30", headers=auth_headers).get_json()
    b = client.get("/api/anomalies?as_of=2026-09-30", headers=auth_headers).get_json()
    assert a == b
