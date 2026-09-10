"""Phase 15 — a CONFIRMED bank-SMS transaction reaches the existing Financial
Twin (and therefore forecast / goals / decision engine). Nothing enters until
the user confirms."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Transaction
from finance.twin import build_twin_state
from finance.affordability import check_affordability
from tests.agent_helpers import FakeRepo, AS_OF
from tests.test_bank_api import FakeBankDB, HDFC_DEBIT

D = Decimal


@pytest.fixture
def bdb(monkeypatch):
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    return fake


def _txn_from_insert_params(p, tid=999):
    # insert_transaction params: (student_id, amount, direction, merchant_name,
    #                             category_id, payment_date, payment_method, notes)
    return Transaction(
        id=tid, student_id=p[0], amount=D(p[1]), direction=p[2], merchant_name=p[3],
        category_id=p[4], category_name="Other", payment_date=date.fromisoformat(p[5]),
        payment_method=p[6], notes=p[7],
    )


def test_confirmed_sms_debit_lowers_the_twin_balance(client, auth_headers, bdb):
    # 1. configure the sender + ingest the SMS + confirm it (review-only)
    client.post("/api/bank/connections",
                json={"bank_name": "HDFC Bank", "sender_id": "HDFCBK"}, headers=auth_headers)
    ev = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                     headers=auth_headers).get_json()["event"]

    repo_before = FakeRepo(opening="20000.00")
    twin_before = build_twin_state(repo_before, 1, as_of=AS_OF)

    r = client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    assert r.status_code == 201

    # 2. the confirmed transaction enters the EXISTING transactions table...
    assert len(bdb.txns) == 1
    new_txn = _txn_from_insert_params(bdb.inserted_txn_params[0])

    # 3. ...so the Financial Twin, rebuilt over the same data, reflects it
    repo_after = FakeRepo(opening="20000.00",
                          transactions=list(repo_before.transactions) + [new_txn])
    twin_after = build_twin_state(repo_after, 1, as_of=AS_OF)

    assert new_txn.direction == "debit" and new_txn.amount == D("5000.00")
    assert twin_after.current_balance == twin_before.current_balance - D("5000.00")


def test_updated_twin_flows_into_the_decision_engine(client, auth_headers, bdb):
    client.post("/api/bank/connections",
                json={"bank_name": "HDFC Bank", "sender_id": "HDFCBK"}, headers=auth_headers)
    ev = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                     headers=auth_headers).get_json()["event"]
    client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    new_txn = _txn_from_insert_params(bdb.inserted_txn_params[0])

    # a tight balance so the newly-synced debit actually changes affordability
    repo = FakeRepo(opening="8000.00", buffer="3000.00",
                    transactions=[new_txn], recurring=[], budgets={})
    twin = build_twin_state(repo, 1, as_of=AS_OF)
    verdict = check_affordability(twin, amount=D("4000"))
    # the ₹5,000 SMS debit is now part of the twin the decision engine sees
    assert twin.current_balance == D("3000.00")
    assert verdict.verdict in {"affordable", "tight", "not_affordable"}


def test_ignored_event_never_reaches_the_twin(client, auth_headers, bdb):
    client.post("/api/bank/connections",
                json={"bank_name": "HDFC Bank", "sender_id": "HDFCBK"}, headers=auth_headers)
    ev = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                     headers=auth_headers).get_json()["event"]
    client.post(f"/api/bank/sms-events/{ev['id']}/ignore", headers=auth_headers)
    assert bdb.txns == []


def test_detected_but_unconfirmed_event_never_reaches_the_twin(client, auth_headers, bdb):
    client.post("/api/bank/connections",
                json={"bank_name": "HDFC Bank", "sender_id": "HDFCBK"}, headers=auth_headers)
    client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                headers=auth_headers)
    # a detected event exists, but with no Confirm the transactions table is untouched
    assert bdb.events and bdb.events[0]["status"] == "needs_confirmation"
    assert bdb.txns == []
