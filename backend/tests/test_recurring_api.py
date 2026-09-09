"""CRUD + validation for /api/recurring. DB stubbed."""

import pytest

MONTHLY = {
    "label": "Rent",
    "merchant_name": "Landlord",
    "amount": "350.00",
    "direction": "debit",
    "cadence": "monthly",
    "day_of_month": 1,
    "next_date": "2026-05-01",
}


class FakeRecurringDB:
    def __init__(self):
        self.rows = {}
        self._next_id = 1
        self.owned = True  # whether _owned_row finds the row

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select id from recurring_transactions where id = %s and student_id"):
            return {"id": params[0]} if self.owned else None
        if s.startswith("insert into recurring_transactions"):
            rid = self._next_id
            self._next_id += 1
            self.rows[rid] = params
            return rid
        if s.startswith("update recurring_transactions set"):
            return 1
        if s.startswith("delete from recurring_transactions"):
            return 1
        if s.startswith("select id, student_id, label"):
            if fetch_all:
                return []
            return {"id": params[0], "label": "Rent", "amount": "350.00",
                    "direction": "debit", "cadence": "monthly", "next_date": "2026-05-01",
                    "day_of_month": 1, "weekday": None, "active": 1, "source": "user",
                    "confidence": None, "student_id": 1,
                    "created_at": None, "updated_at": None}
        raise AssertionError(f"unexpected query: {s}")


@pytest.fixture
def rdb(monkeypatch):
    fake = FakeRecurringDB()
    monkeypatch.setattr("routes.recurring.execute_query", fake.execute_query)
    return fake


def test_create_monthly_ok(client, auth_headers, rdb):
    resp = client.post("/api/recurring", json=MONTHLY, headers=auth_headers)
    assert resp.status_code == 201


def test_create_requires_label(client, auth_headers, rdb):
    body = dict(MONTHLY); body.pop("label")
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_create_rejects_bad_cadence(client, auth_headers, rdb):
    body = dict(MONTHLY); body["cadence"] = "yearly"
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_create_rejects_negative_amount(client, auth_headers, rdb):
    body = dict(MONTHLY); body["amount"] = "-10"
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_create_rejects_bad_next_date(client, auth_headers, rdb):
    body = dict(MONTHLY); body["next_date"] = "05-01-2026"
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_monthly_requires_day_of_month(client, auth_headers, rdb):
    body = dict(MONTHLY); body.pop("day_of_month")
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_weekly_requires_weekday(client, auth_headers, rdb):
    body = {"label": "Bus", "merchant_name": "Transit", "amount": "12", "direction": "debit",
            "cadence": "weekly", "next_date": "2026-05-04"}
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_day_of_month_out_of_range(client, auth_headers, rdb):
    body = dict(MONTHLY); body["day_of_month"] = 40
    assert client.post("/api/recurring", json=body, headers=auth_headers).status_code == 400


def test_list_recurring_ok(client, auth_headers, rdb):
    resp = client.get("/api/recurring", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_update_not_owned_is_404(client, auth_headers, rdb):
    rdb.owned = False
    resp = client.put("/api/recurring/9", json={"amount": "400"}, headers=auth_headers)
    assert resp.status_code == 404


def test_update_owned_ok(client, auth_headers, rdb):
    resp = client.put("/api/recurring/1", json={"amount": "400.00"}, headers=auth_headers)
    assert resp.status_code == 200


def test_delete_owned_ok(client, auth_headers, rdb):
    resp = client.delete("/api/recurring/1", headers=auth_headers)
    assert resp.status_code == 200


def test_recurring_requires_auth(client):
    assert client.get("/api/recurring").status_code == 401
