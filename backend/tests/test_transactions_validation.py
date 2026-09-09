"""Bad input to POST/PUT /api/transactions must return 400, never 500."""

import pytest

VALID = {
    "amount": "12.50",
    "merchant_name": "Campus Cafe",
    "category_id": 5,
    "payment_date": "2026-04-01",
}


@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    """Fake execute_query: category id 5 exists, everything else is inert."""

    def fake_execute_query(query, params=None, fetch_one=False, fetch_all=False,
                           commit=False, raise_on_error=False):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select id from categories where id"):
            return {"id": params[0]} if params and int(params[0]) == 5 else None
        if commit:
            return 123
        if fetch_one:
            return {
                "id": 123, "amount": "12.50", "merchant_name": "Campus Cafe",
                "payment_date": "2026-04-01", "payment_method": None, "notes": None,
                "category_name": "Books", "category_id": 5,
                "created_at": None, "updated_at": None,
            }
        if fetch_all:
            return []
        return None

    monkeypatch.setattr("routes.transactions.execute_query", fake_execute_query)


def post(client, headers, **overrides):
    body = dict(VALID)
    body.update(overrides)
    for key, value in list(body.items()):
        if value is None:
            body.pop(key)
    return client.post("/api/transactions", json=body, headers=headers)


def test_valid_transaction_created(client, auth_headers):
    resp = post(client, auth_headers)
    assert resp.status_code == 201


def test_missing_amount_is_400(client, auth_headers):
    resp = post(client, auth_headers, amount=None)
    assert resp.status_code == 400


def test_missing_category_is_400(client, auth_headers):
    resp = post(client, auth_headers, category_id=None)
    assert resp.status_code == 400


def test_negative_amount_is_400(client, auth_headers):
    resp = post(client, auth_headers, amount=-5)
    assert resp.status_code == 400


def test_zero_amount_is_400(client, auth_headers):
    resp = post(client, auth_headers, amount=0)
    assert resp.status_code == 400


def test_non_numeric_amount_is_400(client, auth_headers):
    resp = post(client, auth_headers, amount="abc")
    assert resp.status_code == 400


def test_bad_date_is_400(client, auth_headers):
    resp = post(client, auth_headers, payment_date="01/04/2026")
    assert resp.status_code == 400


def test_unknown_category_is_400(client, auth_headers):
    resp = post(client, auth_headers, category_id=999)
    assert resp.status_code == 400


def test_requires_auth(client):
    resp = client.post("/api/transactions", json=VALID)
    assert resp.status_code == 401


def test_update_unknown_category_is_400(client, auth_headers):
    resp = client.put("/api/transactions/1", json={"category_id": 999}, headers=auth_headers)
    assert resp.status_code == 400
