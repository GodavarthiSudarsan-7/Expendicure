"""Security audit: cross-user access, identity spoofing, token handling.

Every test here ATTEMPTS an attack and asserts it fails. Identity must always
come from the authenticated token, never from a request body, a query string,
or an LLM-supplied tool argument.
"""

import hashlib
from datetime import date

import pytest

OTHER_USER = 999


# ----------------------------------------------- identity comes from the token

def test_decision_api_ignores_a_body_supplied_identity(client, auth_headers, monkeypatch):
    """POST /api/affordability/check mode=decision must scope to the token."""
    from finance.models import Account
    from finance.money import money

    seen = []

    class Repo:
        def get_account(self, sid):
            seen.append(sid)
            return Account(sid, money("100000.00"), money("20000.00"), date(2026, 10, 5))

        def compute_current_balance(self, sid, as_of=None):
            seen.append(sid)
            return money("100000.00")

        def get_transactions(self, sid, start=None, end=None):
            seen.append(sid)
            return []

        def get_recurring(self, sid, active_only=True):
            seen.append(sid)
            return []

        def get_budgets(self, sid, month):
            return {}

        def get_savings_goals(self, sid, status=None):
            seen.append(sid)
            return []

    monkeypatch.setattr("routes.affordability.get_repository", lambda: Repo())
    r = client.post("/api/affordability/check", json={
        "mode": "decision", "amount": "1000",
        "student_id": OTHER_USER, "user_id": OTHER_USER, "id": OTHER_USER,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert seen and set(seen) == {1}, f"leaked to {set(seen) - {1}}"


def test_every_decision_endpoint_requires_authentication(client):
    for method, path, body in [
        ("post", "/api/affordability/check", {"amount": "100", "mode": "decision"}),
        ("post", "/api/affordability/check", {"amount": "100"}),
        ("get", "/api/twin/state", None),
        ("get", "/api/forecast", None),
        ("get", "/api/goals", None),
        ("get", "/api/reports/financial-profile", None),
        ("get", "/api/bank/connections", None),
        ("post", "/api/agent/chat", {"message": "hi"}),
    ]:
        fn = getattr(client, method)
        resp = fn(path, json=body) if body is not None else fn(path)
        assert resp.status_code == 401, f"{method.upper()} {path} was not protected"


def test_a_forged_token_is_rejected(client):
    bad = {"Authorization": "Bearer not.a.real.token"}
    assert client.get("/api/twin/state", headers=bad).status_code == 401
    assert client.post("/api/affordability/check",
                       json={"amount": "100", "mode": "decision"},
                       headers=bad).status_code == 401


def test_a_token_signed_with_the_wrong_secret_is_rejected(client):
    import jwt as pyjwt
    forged = pyjwt.encode({"student_id": OTHER_USER}, "attacker-secret", algorithm="HS256")
    r = client.get("/api/twin/state", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


# ------------------------------------------------------ LLM cannot claim identity

def test_no_tool_accepts_an_identity_argument():
    """An LLM must not be able to name a user. No tool schema may expose one."""
    from tools import build_default_registry
    reg = build_default_registry(lambda: None)
    forbidden = {"user_id", "student_id", "account_id", "owner_id", "id"}
    for spec in reg.catalog():
        leaked = forbidden & set((spec.get("schema") or {}).keys())
        assert not leaked, f"tool {spec['name']} exposes {leaked}"


def test_a_tool_call_carrying_an_identity_is_refused():
    from datetime import date as _d
    from tools import build_default_registry, make_context
    reg = build_default_registry(lambda: None)
    ctx = make_context(1, as_of=_d(2026, 10, 5), repo_factory=lambda: None)
    res = reg.run("plan_purchase_decision", ctx,
                  {"amount": 1000, "student_id": OTHER_USER})
    assert res.ok is False and "not allowed" in (res.error or "")


# --------------------------------------------------------- bank connections

def test_bank_connection_of_another_user_is_a_404(client, auth_headers, monkeypatch):
    from tests.test_bank_api import FakeBankDB
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    # a connection owned by someone else
    fake.conns.append({
        "id": 1, "student_id": OTHER_USER, "bank_name": "HDFC", "sender_id": "HDFCBK",
        "masked_account": None, "enabled": True, "ingest_token_hash": "x",
        "last_event_at": None, "events_detected": 0, "created_at": None, "updated_at": None,
    })
    assert client.put("/api/bank/connections/1", json={"enabled": False},
                      headers=auth_headers).status_code == 404
    assert client.delete("/api/bank/connections/1", headers=auth_headers).status_code == 404
    assert client.post("/api/bank/connections/1/rotate-token",
                       headers=auth_headers).status_code == 404
    assert client.get("/api/bank/connections", headers=auth_headers).get_json()["connections"] == []


def test_a_bank_event_of_another_user_cannot_be_confirmed(client, auth_headers, monkeypatch):
    from tests.test_bank_api import FakeBankDB
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    fake.events.append({
        "id": 1, "student_id": OTHER_USER, "connection_id": 1, "status": "needs_confirmation",
        "direction": "debit", "amount": "500.00", "occurred_on": date(2026, 10, 1),
        "occurred_at": None, "merchant": "X", "masked_account": None, "bank_ref_id": "r1",
        "fingerprint": "f", "detect_reason": None, "template_id": None,
        "transaction_id": None, "received_at": None, "resolved_at": None,
    })
    for path in ("/api/bank/sms-events/1/confirm", "/api/bank/sms-events/1/ignore"):
        assert client.post(path, json={}, headers=auth_headers).status_code == 404
    assert client.patch("/api/bank/sms-events/1", json={"amount": "1"},
                        headers=auth_headers).status_code == 404
    assert fake.txns == [], "another user's event must never create a transaction"


# ---------------------------------------------------------------- ingest token

def test_the_ingest_token_is_only_ever_stored_hashed(client, auth_headers, monkeypatch):
    from tests.test_bank_api import FakeBankDB
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    body = client.post("/api/bank/connections",
                       json={"bank_name": "HDFC", "sender_id": "HDFCBK"},
                       headers=auth_headers).get_json()
    raw = body["ingest_token"]
    stored = fake.conns[0]["ingest_token_hash"]
    assert raw and raw != stored
    assert stored == hashlib.sha256(raw.encode()).hexdigest()
    # and it is never echoed again
    listed = client.get("/api/bank/connections", headers=auth_headers).get_json()
    assert "ingest_token" not in listed["connections"][0]


def test_rotating_the_token_invalidates_the_old_one(client, auth_headers, monkeypatch):
    from tests.test_bank_api import FakeBankDB
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    created = client.post("/api/bank/connections",
                          json={"bank_name": "HDFC", "sender_id": "HDFCBK"},
                          headers=auth_headers).get_json()
    old = created["ingest_token"]
    new = client.post(f"/api/bank/connections/{created['id']}/rotate-token",
                      headers=auth_headers).get_json()["ingest_token"]
    assert new != old
    HDFC = "Rs.500.00 debited from a/c XX1234 on 10-10-26 to SHOP. UPI Ref 999888777666"
    assert client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC},
                       headers={"X-Ingest-Token": old}).status_code == 401
    assert client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC},
                       headers={"X-Ingest-Token": new}).status_code == 201


# --------------------------------------------------------------- goals / reports

def test_another_users_goal_is_invisible(client, auth_headers, monkeypatch):
    rows = {"g": [{"id": 5, "student_id": OTHER_USER, "name": "Theirs",
                   "target_amount": "1", "current_amount": "0",
                   "monthly_contribution": "1", "target_date": date(2027, 1, 1),
                   "status": "active", "created_at": None, "updated_at": None}]}

    def q(sql, params=None, **kw):
        s = " ".join(sql.split()).lower()
        p = params or ()
        if s.startswith("select") and "from savings_goals" in s:
            # the route always scopes by student_id; honour that faithfully
            return [r for r in rows["g"] if r["student_id"] in p] if kw.get("fetch_all") \
                else next((r for r in rows["g"] if r["student_id"] in p), None)
        return [] if kw.get("fetch_all") else None

    monkeypatch.setattr("routes.goals.execute_query", q)
    assert client.get("/api/goals", headers=auth_headers).get_json() == []
    assert client.get("/api/goals/5", headers=auth_headers).status_code == 404


def test_the_report_is_built_for_the_token_holder_only(client, auth_headers, monkeypatch):
    from tests.test_reports_export import FakeRepo
    seen = []
    repo = FakeRepo()
    real = repo.get_transactions

    def spy(sid, start=None, end=None):
        seen.append(sid)
        return real(sid, start, end)

    repo.get_transactions = spy
    monkeypatch.setattr("routes.reports.get_repository", lambda: repo)
    monkeypatch.setattr("routes.reports.execute_query", lambda *a, **k: {"first_date": None})
    client.get(f"/api/reports/financial-profile?student_id={OTHER_USER}", headers=auth_headers)
    assert seen and set(seen) == {1}


# ---------------------------------------------------------------- SQL safety

def test_no_route_builds_sql_by_interpolating_request_data():
    """Every query must be parameterised. Flag f-strings/concatenation that mix
    SQL with a value expression rather than a fixed column list."""
    import os
    import re

    offenders = []
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "routes")
    risky = re.compile(r"""(?:execute_query|cursor\.execute)\s*\(\s*f["']""")
    for name in os.listdir(root):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if risky.search(line):
                    # an f-string is allowed only to inject a FIXED column list
                    if not re.search(r"\{(?:CONN_COLS|EVENT_COLS|GOAL_SELECT|TXN_SELECT|"
                                     r"MIGRATIONS_TABLE|', '\.join\(sets\))\}", line):
                        offenders.append(f"routes/{name}:{i}")
    assert offenders == [], offenders


# --------------------------------------------------------- malformed input

@pytest.mark.parametrize("body", [
    {}, {"amount": None}, {"amount": "abc", "mode": "decision"},
    {"amount": "1e400", "mode": "decision"},
    {"amount": "100", "mode": "decision", "installment_options": "nope"},
    {"amount": "100", "mode": "decision", "desired_completion_date": "33-99-11"},
    {"amount": "100", "mode": "<script>alert(1)</script>"},
])
def test_malformed_decision_input_never_500s(client, auth_headers, monkeypatch, body):
    from tests.test_affordability_decision_api import FakeRepo
    monkeypatch.setattr("routes.affordability.get_repository", lambda: FakeRepo())
    r = client.post("/api/affordability/check", json=body, headers=auth_headers)
    assert r.status_code in (200, 400), r.status_code
    if r.status_code == 400:
        assert "error" in r.get_json()


def test_a_huge_payload_is_rejected_not_crashed(client, auth_headers, monkeypatch):
    from tests.test_affordability_decision_api import FakeRepo
    monkeypatch.setattr("routes.affordability.get_repository", lambda: FakeRepo())
    r = client.post("/api/affordability/check", json={
        "mode": "decision", "amount": "100", "description": "x" * 50_000,
        "installment_options": [{"first_payment_date": "2026-10-21",
                                 "number_of_payments": 3, "payment_amount": "1",
                                 "total_payable": "3"}] * 50,
    }, headers=auth_headers)
    assert r.status_code in (200, 400)


# ------------------------------------------------------------- no raw SMS stored

def test_no_backend_table_or_response_can_hold_a_raw_sms_body():
    """`bank_sms_events` has structured columns only, and no endpoint echoes a
    body. Verified against the migration and the route module."""
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "database", "migrations", "008_bank_sms_events.sql"),
              encoding="utf-8") as fh:
        ddl = fh.read().lower()
    for banned in ("body", "raw_sms", "message_text", "sms_text", "raw_body"):
        assert not re.search(rf"^\s*{banned}\s+\w", ddl, re.M), f"column '{banned}' exists"

    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "routes", "bank.py"), encoding="utf-8") as fh:
        src = fh.read()
    # the public serialiser must not expose a body under any key
    serialiser = src.split("def _event_public")[1].split("def ")[0]
    assert '"body"' not in serialiser and "body" not in serialiser.replace("# ", "")
