"""POST /api/transactions now accepts a debit/credit direction."""

import pytest

BASE = {
    "amount": "50.00",
    "merchant_name": "Allowance",
    "category_id": 5,
    "payment_date": "2026-04-01",
}


@pytest.fixture
def captured(monkeypatch):
    box = {}

    def fake_execute_query(query, params=None, fetch_one=False, fetch_all=False,
                           commit=False, raise_on_error=False):
        s = " ".join(query.split()).lower()
        if s.startswith("select id from categories where id"):
            return {"id": params[0]} if params and int(params[0]) == 5 else None
        if s.startswith("insert into transactions"):
            box["insert_params"] = params
            return 777
        if fetch_one:
            # echo the direction that was inserted
            return {
                "id": 777, "amount": "50.00",
                "direction": box.get("insert_params", [None, None, "debit"])[2],
                "merchant_name": "Allowance", "payment_date": "2026-04-01",
                "payment_method": None, "notes": None, "category_name": "Other",
                "category_id": 5, "created_at": None, "updated_at": None,
            }
        return None

    monkeypatch.setattr("routes.transactions.execute_query", fake_execute_query)
    return box


def _post(client, headers, **overrides):
    body = dict(BASE)
    body.update(overrides)
    return client.post("/api/transactions", json=body, headers=headers)


def test_direction_defaults_to_debit(client, auth_headers, captured):
    resp = _post(client, auth_headers)
    assert resp.status_code == 201
    assert captured["insert_params"][2] == "debit"
    assert resp.get_json()["direction"] == "debit"


def test_direction_credit_is_persisted(client, auth_headers, captured):
    resp = _post(client, auth_headers, direction="credit")
    assert resp.status_code == 201
    assert captured["insert_params"][2] == "credit"
    assert resp.get_json()["direction"] == "credit"


def test_direction_is_case_insensitive(client, auth_headers, captured):
    resp = _post(client, auth_headers, direction="CREDIT")
    assert resp.status_code == 201
    assert captured["insert_params"][2] == "credit"


def test_invalid_direction_is_400(client, auth_headers, captured):
    resp = _post(client, auth_headers, direction="sideways")
    assert resp.status_code == 400
