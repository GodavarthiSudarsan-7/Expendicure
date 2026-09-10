"""Registration must validate input and be atomic (no orphan account rows)."""

import pytest

from database import IntegrityError

VALID = {
    "name": "Alex Doe",
    "mobile_number": "+91 98765 43210",
    "username": "alexd",
    "password": "secret123",
}


def test_missing_field_is_400(client):
    resp = client.post("/api/auth/register", json={"name": "x"})
    assert resp.status_code == 400


def test_missing_mobile_is_400(client):
    resp = client.post("/api/auth/register",
                       json={"name": "x", "username": "u", "password": "p"})
    assert resp.status_code == 400


@pytest.mark.parametrize("bad", ["12345", "not-a-number", "+", "98765abc432", ""])
def test_invalid_mobile_is_400(client, monkeypatch, bad):
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)
    monkeypatch.setattr("routes.auth.run_transaction", lambda fn: 1)
    resp = client.post("/api/auth/register", json={**VALID, "mobile_number": bad})
    assert resp.status_code == 400


def test_no_student_id_required(client, monkeypatch):
    # a payload with NO student id must still register fine
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)
    monkeypatch.setattr("routes.auth.run_transaction", lambda fn: 1)
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code == 201


def test_duplicate_account_is_409(client, monkeypatch):
    # Pre-check finds an existing account/user.
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: {"id": 1})
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code == 409


def test_race_integrity_error_is_409_and_not_500(client, monkeypatch):
    # Pre-checks pass, but the transaction hits a unique constraint.
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)

    def boom(_fn):
        raise IntegrityError("Duplicate entry")

    monkeypatch.setattr("routes.auth.run_transaction", boom)
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code == 409


def test_transaction_failure_is_500(client, monkeypatch):
    from database import DatabaseError

    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)

    def boom(_fn):
        raise DatabaseError("no connection")

    monkeypatch.setattr("routes.auth.run_transaction", boom)
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code == 500


def test_happy_path_runs_single_transaction(client, monkeypatch):
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)
    calls = []

    def fake_run_transaction(fn):
        # Simulate a cursor so the inner _create closure executes end to end.
        class Cur:
            lastrowid = 42

            def execute(self, *args, **kwargs):
                calls.append(args[0].split()[0].upper())

        return fn(Cur())

    monkeypatch.setattr("routes.auth.run_transaction", fake_run_transaction)
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code == 201
    # Both inserts happened inside the one transaction.
    assert calls == ["INSERT", "INSERT"]


def test_register_requires_no_auth(client, monkeypatch):
    monkeypatch.setattr("routes.auth.execute_query", lambda *a, **k: None)
    monkeypatch.setattr("routes.auth.run_transaction", lambda fn: 1)
    resp = client.post("/api/auth/register", json=VALID)
    assert resp.status_code in (201, 500)  # not 401
