"""Phase 15 — /api/bank routes. DB stubbed. REVIEW-ONLY: nothing enters the
transactions table without an explicit user Confirm."""

import hashlib

import pytest


def _norm(sql):
    return " ".join(sql.split()).lower()


class FakeBankDB:
    """In-memory stand-in for bank_connections + bank_sms_events + categories +
    categorization_rules + transactions. Monkeypatched onto routes.bank and
    routes.transactions."""

    def __init__(self):
        self.conns = []      # dicts
        self.events = []
        self.txns = []
        self.categories = [
            {"id": 1, "name": "Food", "is_default": 1, "student_id": None},
            {"id": 8, "name": "Other", "is_default": 1, "student_id": None},
        ]
        self.rules = [
            {"id": 1, "student_id": None, "match_type": "contains", "pattern": "amazon",
             "category_id": 8, "priority": 10},
        ]
        self._cid = self._eid = self._tid = 0
        self.inserted_txn_params = []

    # -- helpers --
    def _conn(self, cid):
        return next((c for c in self.conns if c["id"] == cid), None)

    def _event(self, eid):
        return next((e for e in self.events if e["id"] == eid), None)

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False,
                      commit=False, raise_on_error=False):
        s = _norm(query)
        p = params or ()

        # ---------------- bank_connections
        if s.startswith("select id, student_id, bank_name, sender_id, masked_account, enabled, last_event_at, events_detected, created_at, updated_at from bank_connections where id = %s and student_id"):
            c = self._conn(p[0])
            return c if (c and c["student_id"] == p[1]) else None
        if s.startswith("select id, student_id, bank_name") and "where student_id = %s order by id" in s:
            return [c for c in self.conns if c["student_id"] == p[0]]
        if s.startswith("select id from bank_connections where student_id = %s and sender_id = %s"):
            return next(({"id": c["id"]} for c in self.conns
                         if c["student_id"] == p[0] and c["sender_id"] == p[1]), None)
        if s.startswith("select id, student_id, enabled from bank_connections where ingest_token_hash = %s"):
            return next(({"id": c["id"], "student_id": c["student_id"], "enabled": c["enabled"]}
                         for c in self.conns if c.get("ingest_token_hash") == p[0]), None)
        if s.startswith("select id, student_id, bank_name") and "and sender_id = %s and enabled = true" in s:
            return next((c for c in self.conns
                         if c["student_id"] == p[0] and c["sender_id"] == p[1] and c["enabled"]), None)
        if s.startswith("insert into bank_connections"):
            self._cid += 1
            self.conns.append({
                "id": self._cid, "student_id": p[0], "bank_name": p[1], "sender_id": p[2],
                "masked_account": p[3], "enabled": True, "ingest_token_hash": p[4],
                "last_event_at": None, "events_detected": 0,
                "created_at": None, "updated_at": None,
            })
            return self._cid
        if s.startswith("update bank_connections set ingest_token_hash = %s where id = %s"):
            self._conn(p[1])["ingest_token_hash"] = p[0]
            return 1
        if s.startswith("update bank_connections set events_detected = events_detected + 1"):
            c = self._conn(p[0]); c["events_detected"] += 1; c["last_event_at"] = "now"
            return 1
        if s.startswith("update bank_connections set"):
            c = self._conn(p[-1])
            if c is not None:
                cols = [seg.split("=")[0].strip()
                        for seg in s.split("set", 1)[1].split("where")[0].split(",")]
                for col, val in zip(cols, p[:-1]):
                    c[col] = bool(val) if col == "enabled" else val
            return 1
        if s.startswith("delete from bank_connections where id = %s"):
            self.conns = [c for c in self.conns if c["id"] != p[0]]
            self.events = [e for e in self.events if e["connection_id"] != p[0]]
            return 1

        # ---------------- bank_sms_events
        if s.startswith("select count(*) as n from bank_sms_events where student_id = %s and status in"):
            n = sum(1 for e in self.events
                    if e["student_id"] == p[0] and e["status"] in ("needs_confirmation", "needs_review"))
            return {"n": n}
        if s.startswith("select id, status from bank_sms_events where connection_id = %s and fingerprint = %s"):
            return next(({"id": e["id"], "status": e["status"]} for e in self.events
                         if e["connection_id"] == p[0] and e["fingerprint"] == p[1]), None)
        if s.startswith("insert into bank_sms_events"):
            self._eid += 1
            self.events.append({
                "id": self._eid, "student_id": p[0], "connection_id": p[1], "status": p[2],
                "direction": p[3], "amount": p[4], "occurred_on": p[5], "occurred_at": None,
                "merchant": p[6], "masked_account": p[7], "bank_ref_id": p[8],
                "fingerprint": p[9], "detect_reason": p[10], "template_id": p[11],
                "transaction_id": None, "received_at": None, "resolved_at": None,
            })
            return self._eid
        if s.startswith("select id, student_id, connection_id, status, direction, amount, occurred_on, occurred_at, merchant, masked_account, bank_ref_id, detect_reason, template_id, transaction_id, received_at, resolved_at from bank_sms_events where id = %s and student_id"):
            e = self._event(p[0])
            return e if (e and e["student_id"] == p[1]) else None
        if s.startswith("select id, student_id, connection_id, status, direction, amount, occurred_on, occurred_at, merchant, masked_account, bank_ref_id, detect_reason, template_id, transaction_id, received_at, resolved_at from bank_sms_events where id = %s"):
            return self._event(p[0])
        if s.startswith("select id, student_id, connection_id, status") and "where student_id = %s" in s:
            out = [e for e in self.events if e["student_id"] == p[0]]
            if "status in" in s:
                out = [e for e in out if e["status"] in ("needs_confirmation", "needs_review")]
            elif "status = %s" in s:
                out = [e for e in out if e["status"] == p[1]]
            return list(reversed(out))
        if s.startswith("update bank_sms_events set"):
            e = self._event(p[-1])
            if e is None:
                return 1
            if "status = %s" in s and "transaction_id = %s" in s:
                e.update(status=p[0], transaction_id=p[1], direction=p[2],
                         amount=p[3], occurred_on=p[4], merchant=p[5], resolved_at="now")
            elif "status = %s" in s:
                e["status"] = p[0]; e["resolved_at"] = "now"
            else:
                # field edit
                cols = [seg.split("=")[0].strip() for seg in s.split("set", 1)[1].split("where")[0].split(",")]
                for col, val in zip(cols, p[:-1]):
                    e[col] = val
            return 1

        # ---------------- categories / rules
        if s.startswith("select id, student_id, match_type, pattern, category_id, priority from categorization_rules"):
            return list(self.rules)
        if s.startswith("select id, name, is_default, student_id from categories where student_id"):
            return list(self.categories)
        if s.startswith("select id from categories where id = %s"):
            return next(({"id": c["id"]} for c in self.categories if c["id"] == p[0]), None)

        # ---------------- transactions
        if s.startswith("insert into transactions"):
            self._tid += 1
            self.inserted_txn_params.append(p)
            self.txns.append({"id": self._tid, "student_id": p[0], "amount": p[1],
                              "direction": p[2], "merchant_name": p[3], "category_id": p[4],
                              "payment_date": p[5], "payment_method": p[6], "notes": p[7]})
            return self._tid
        if s.startswith("select t.id, t.amount, t.direction") and "from transactions t" in s:
            t = next((x for x in self.txns if x["id"] == p[0]), None)
            if not t:
                return None
            return {**t, "category_name": "Other", "created_at": None, "updated_at": None}

        raise AssertionError(f"unhandled SQL: {s}")


@pytest.fixture
def bdb(monkeypatch):
    fake = FakeBankDB()
    monkeypatch.setattr("routes.bank.execute_query", fake.execute_query)
    monkeypatch.setattr("routes.transactions.execute_query", fake.execute_query)
    return fake


HDFC_DEBIT = ("Rs.5000.00 debited from a/c XX4821 on 10-09-26 to AMAZON. "
              "UPI Ref 402312345678. Not you? Call 18002586161")


def _make_connection(client, auth_headers, bdb, sender="HDFCBK", bank="HDFC Bank"):
    r = client.post("/api/bank/connections",
                    json={"bank_name": bank, "sender_id": sender, "masked_account": "XX4821"},
                    headers=auth_headers)
    assert r.status_code == 201
    return r.get_json()


# ============================================================ connection CRUD
def test_connection_requires_auth(client, bdb):
    assert client.get("/api/bank/connections").status_code == 401
    assert client.post("/api/bank/connections", json={}).status_code == 401


def test_create_and_list_connection(client, auth_headers, bdb):
    body = _make_connection(client, auth_headers, bdb)
    assert body["bank_name"] == "HDFC Bank" and body["sender_id"] == "HDFCBK"
    assert body["masked_account"] == "4821"          # masked to last digits
    assert "ingest_token" in body and len(body["ingest_token"]) > 20

    lst = client.get("/api/bank/connections", headers=auth_headers).get_json()
    assert len(lst["connections"]) == 1
    assert "ingest_token" not in lst["connections"][0]   # never re-exposed
    assert lst["pending_review"] == 0


def test_create_rejects_blank_fields(client, auth_headers, bdb):
    assert client.post("/api/bank/connections", json={"sender_id": "X"}, headers=auth_headers).status_code == 400
    assert client.post("/api/bank/connections", json={"bank_name": "B"}, headers=auth_headers).status_code == 400


def test_duplicate_sender_rejected(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/connections",
                    json={"bank_name": "HDFC", "sender_id": "HDFCBK"}, headers=auth_headers)
    assert r.status_code == 409


def test_toggle_and_rotate_and_delete(client, auth_headers, bdb):
    c = _make_connection(client, auth_headers, bdb)
    cid = c["id"]
    assert client.put(f"/api/bank/connections/{cid}", json={"enabled": False},
                      headers=auth_headers).get_json()["enabled"] is False
    r = client.post(f"/api/bank/connections/{cid}/rotate-token", headers=auth_headers)
    assert r.status_code == 200 and r.get_json()["ingest_token"] != c["ingest_token"]
    assert client.delete(f"/api/bank/connections/{cid}", headers=auth_headers).status_code == 200


def test_cannot_touch_another_users_connection(client, auth_headers, bdb):
    # a connection owned by student 2
    bdb.conns.append({"id": 99, "student_id": 2, "bank_name": "X", "sender_id": "OTHER",
                      "masked_account": None, "enabled": True, "ingest_token_hash": "h",
                      "last_event_at": None, "events_detected": 0})
    assert client.put("/api/bank/connections/99", json={"enabled": False}, headers=auth_headers).status_code == 404
    assert client.delete("/api/bank/connections/99", headers=auth_headers).status_code == 404
    assert client.post("/api/bank/connections/99/rotate-token", headers=auth_headers).status_code == 404


# ============================================================ ingestion
def test_ingest_valid_debit_creates_needs_confirmation_event(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 201
    ev = r.get_json()["event"]
    assert ev["status"] == "needs_confirmation"
    assert ev["direction"] == "debit" and ev["amount"] == "5000.00"
    assert ev["merchant"] == "AMAZON" and ev["occurred_on"] == "2026-09-10"
    assert ev["bank_ref_id"] == "402312345678"
    # nothing entered the transactions table
    assert bdb.txns == []
    # connection counter bumped
    assert bdb.conns[0]["events_detected"] == 1


def test_ingest_valid_credit(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb, sender="SBIINB", bank="SBI")
    body = ("Dear Customer, Rs.15000.00 credited to your A/c XXXXX1234 on 05-Sep-2026 "
            "by NEFT. Avl Bal Rs.42350.10. Ref no 99887766.")
    ev = client.post("/api/bank/sms-events", json={"sender": "SBIINB", "body": body},
                     headers=auth_headers).get_json()["event"]
    assert ev["direction"] == "credit" and ev["amount"] == "15000.00"


def test_unconfigured_sender_is_ignored_not_an_error(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "SOMERANDOM", "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 202 and "ignored" in r.get_json()
    assert bdb.events == []


def test_disabled_connection_is_ignored(client, auth_headers, bdb):
    c = _make_connection(client, auth_headers, bdb)
    client.put(f"/api/bank/connections/{c['id']}", json={"enabled": False}, headers=auth_headers)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 202 and bdb.events == []


@pytest.mark.parametrize("body", [
    "123456 is your OTP for txn of Rs 5000 at Amazon. Do not share it. -HDFCBK",
    "Get 50% OFF! Use SAVE50. Limited time offer.",
    "Your parcel will arrive today between 10 AM and 2 PM.",
])
def test_otp_and_promo_and_noise_are_ignored(client, auth_headers, bdb, body):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": body},
                    headers=auth_headers)
    assert r.status_code == 202 and "ignored" in r.get_json()
    assert bdb.events == []


def test_malformed_body_never_500s(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    for body in ["\x00\x01\x02", "debited " * 400, "Rs credited a/c"]:
        r = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": body},
                        headers=auth_headers)
        assert r.status_code in (201, 202)


def test_missing_body_or_sender_is_400(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    assert client.post("/api/bank/sms-events", json={"sender": "HDFCBK"}, headers=auth_headers).status_code == 400
    assert client.post("/api/bank/sms-events", json={"body": "x"}, headers=auth_headers).status_code == 400


def test_duplicate_sms_is_deduped(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    first = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                        headers=auth_headers)
    assert first.status_code == 201
    again = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                        headers=auth_headers)
    assert again.status_code == 200 and again.get_json()["duplicate"] is True
    assert len(bdb.events) == 1


def test_ingest_with_ingest_token_header(client, bdb, monkeypatch):
    # create a connection as the logged-in user, grab its token, then ingest with
    # ONLY the X-Ingest-Token (no JWT) — the companion's path
    from tests.conftest import FAKE_STUDENT
    monkeypatch.setattr("middleware.execute_query", lambda *a, **k: dict(FAKE_STUDENT))
    import jwt as pyjwt
    from config import Config
    jwt_hdr = {"Authorization": "Bearer " + pyjwt.encode({"student_id": 1}, Config.SECRET_KEY, algorithm="HS256")}
    c = client.post("/api/bank/connections", json={"bank_name": "HDFC", "sender_id": "HDFCBK"},
                    headers=jwt_hdr).get_json()

    r = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                    headers={"X-Ingest-Token": c["ingest_token"]})
    assert r.status_code == 201 and r.get_json()["event"]["amount"] == "5000.00"


def test_bad_ingest_token_is_401(client, bdb):
    r = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                    headers={"X-Ingest-Token": "not-a-real-token"})
    assert r.status_code == 401


def test_ingest_token_wrong_sender_is_ignored(client, bdb, monkeypatch):
    from tests.conftest import FAKE_STUDENT
    monkeypatch.setattr("middleware.execute_query", lambda *a, **k: dict(FAKE_STUDENT))
    import jwt as pyjwt
    from config import Config
    jwt_hdr = {"Authorization": "Bearer " + pyjwt.encode({"student_id": 1}, Config.SECRET_KEY, algorithm="HS256")}
    c = client.post("/api/bank/connections", json={"bank_name": "HDFC", "sender_id": "HDFCBK"},
                    headers=jwt_hdr).get_json()
    r = client.post("/api/bank/sms-events", json={"sender": "OTHERBANK", "body": HDFC_DEBIT},
                    headers={"X-Ingest-Token": c["ingest_token"]})
    assert r.status_code == 202


# ============================================================ structured ingest
# The companion parses the SMS on the phone and posts a `transaction` object;
# the raw body never leaves the device. The backend re-validates everything.

def _structured(direction="debit", **over):
    txn = {
        "amount": "5000.00", "direction": direction, "merchant": "AMAZON",
        "masked_account": "4821", "bank_ref": "402312345678",
        "occurred_on": "2026-09-10", "template_id": "hdfc_debit_v1",
        "parse_status": "confident",
    }
    txn.update(over)
    return txn


def test_structured_payload_creates_event_without_a_raw_body(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "transaction": _structured()}, headers=auth_headers)
    assert r.status_code == 201
    ev = r.get_json()["event"]
    assert ev["status"] == "needs_confirmation"
    assert ev["direction"] == "debit" and ev["amount"] == "5000.00"
    assert ev["merchant"] == "AMAZON" and ev["occurred_on"] == "2026-09-10"
    assert ev["bank_ref_id"] == "402312345678" and ev["template_id"] == "hdfc_debit_v1"
    assert bdb.txns == []                       # review-only, nothing auto-inserted
    assert bdb.conns[0]["events_detected"] == 1


def test_structured_missing_amount_is_400(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    for bad in ({}, {"amount": "0"}, {"amount": "-5"}, {"amount": "abc"}):
        r = client.post("/api/bank/sms-events",
                        json={"sender": "HDFCBK", "transaction": bad}, headers=auth_headers)
        assert r.status_code == 400
    assert bdb.events == []


def test_structured_without_direction_needs_review(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    txn = _structured()
    txn.pop("direction")
    ev = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "transaction": txn},
                     headers=auth_headers).get_json()["event"]
    assert ev["status"] == "needs_review" and ev["direction"] is None
    assert ev["amount"] == "5000.00"


def test_structured_thin_fields_stay_in_review_even_if_client_claims_confident(client, auth_headers, bdb):
    # client sends parse_status "confident" but supplies neither a ref nor
    # merchant+account nor a date -> the server re-derives and keeps it in review
    _make_connection(client, auth_headers, bdb)
    txn = _structured(parse_status="confident")
    for k in ("bank_ref", "merchant", "masked_account", "occurred_on"):
        txn.pop(k, None)
    ev = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "transaction": txn},
                     headers=auth_headers).get_json()["event"]
    assert ev["status"] == "needs_review"


def test_structured_bad_direction_value_falls_back_to_review(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    ev = client.post("/api/bank/sms-events",
                     json={"sender": "HDFCBK", "transaction": _structured(direction="sideways")},
                     headers=auth_headers).get_json()["event"]
    assert ev["status"] == "needs_review" and ev["direction"] is None


def test_structured_payload_dedupes_by_bank_ref(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    first = client.post("/api/bank/sms-events",
                        json={"sender": "HDFCBK", "transaction": _structured()}, headers=auth_headers)
    assert first.status_code == 201
    again = client.post("/api/bank/sms-events",
                        json={"sender": "HDFCBK", "transaction": _structured(merchant="AMZN")},
                        headers=auth_headers)
    assert again.status_code == 200 and again.get_json()["duplicate"] is True
    assert len(bdb.events) == 1


def test_structured_and_raw_of_the_same_txn_dedupe_together(client, auth_headers, bdb):
    # raw HDFC_DEBIT and the structured form carry the same UPI ref -> one event
    _make_connection(client, auth_headers, bdb)
    raw = client.post("/api/bank/sms-events", json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                      headers=auth_headers)
    assert raw.status_code == 201
    dup = client.post("/api/bank/sms-events",
                      json={"sender": "HDFCBK", "transaction": _structured()}, headers=auth_headers)
    assert dup.status_code == 200 and dup.get_json()["duplicate"] is True
    assert len(bdb.events) == 1


def test_structured_unconfigured_sender_is_ignored(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "NOPE", "transaction": _structured()}, headers=auth_headers)
    assert r.status_code == 202 and bdb.events == []


def test_structured_event_can_be_confirmed(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb)
    ev = client.post("/api/bank/sms-events",
                     json={"sender": "HDFCBK", "transaction": _structured()},
                     headers=auth_headers).get_json()["event"]
    r = client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    assert r.status_code == 201
    assert r.get_json()["event"]["status"] == "confirmed"
    assert len(bdb.txns) == 1 and bdb.txns[0]["amount"] == "5000.00"


# ============================================================ review flow
def _detect(client, auth_headers, bdb, body=HDFC_DEBIT, sender="HDFCBK"):
    _make_connection(client, auth_headers, bdb, sender=sender)
    return client.post("/api/bank/sms-events", json={"sender": sender, "body": body},
                       headers=auth_headers).get_json()["event"]


def test_confirm_inserts_into_transactions_table(client, auth_headers, bdb):
    ev = _detect(client, auth_headers, bdb)
    r = client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    assert r.status_code == 201
    body = r.get_json()
    assert body["event"]["status"] == "confirmed"
    assert body["event"]["transaction_id"] is not None
    # the transaction reached the EXISTING table with the right values
    assert len(bdb.txns) == 1
    p = bdb.inserted_txn_params[0]
    assert p[0] == 1 and p[1] == "5000.00" and p[2] == "debit" and p[3] == "AMAZON"
    assert p[6] == "bank_sms"                         # payment_method marker
    assert p[4] == 8                                  # categorised via 'amazon' rule -> Other(8)


def test_confirm_with_edits_overrides_extracted_values(client, auth_headers, bdb):
    ev = _detect(client, auth_headers, bdb)
    r = client.post(f"/api/bank/sms-events/{ev['id']}/confirm",
                    json={"amount": "4750.00", "merchant": "Amazon India", "direction": "debit"},
                    headers=auth_headers)
    assert r.status_code == 201
    p = bdb.inserted_txn_params[0]
    assert p[1] == "4750.00" and p[3] == "Amazon India"


def test_ignore_does_not_create_a_transaction(client, auth_headers, bdb):
    ev = _detect(client, auth_headers, bdb)
    r = client.post(f"/api/bank/sms-events/{ev['id']}/ignore", headers=auth_headers)
    assert r.status_code == 200 and r.get_json()["event"]["status"] == "ignored"
    assert bdb.txns == []


def test_cannot_confirm_twice(client, auth_headers, bdb):
    ev = _detect(client, auth_headers, bdb)
    client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    again = client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    assert again.status_code == 409
    assert len(bdb.txns) == 1


def test_needs_review_event_requires_a_direction_to_confirm(client, auth_headers, bdb):
    body = "Rs 2,000.00 transaction on a/c XX7788 on 12/09/2026."   # no direction word
    ev = _detect(client, auth_headers, bdb, body=body)
    assert ev["status"] == "needs_review"
    bad = client.post(f"/api/bank/sms-events/{ev['id']}/confirm", json={}, headers=auth_headers)
    assert bad.status_code == 422
    ok = client.post(f"/api/bank/sms-events/{ev['id']}/confirm",
                     json={"direction": "debit"}, headers=auth_headers)
    assert ok.status_code == 201 and bdb.txns[0]["direction"] == "debit"


def test_edit_pending_event(client, auth_headers, bdb):
    ev = _detect(client, auth_headers, bdb)
    r = client.patch(f"/api/bank/sms-events/{ev['id']}",
                     json={"merchant": "AMZN", "amount": "5001.00"}, headers=auth_headers)
    assert r.status_code == 200 and r.get_json()["event"]["merchant"] == "AMZN"


def test_confirm_ignore_require_ownership(client, auth_headers, bdb):
    # event belonging to student 2
    bdb.events.append({"id": 77, "student_id": 2, "connection_id": 1, "status": "needs_confirmation",
                       "direction": "debit", "amount": "9.00", "occurred_on": "2026-09-01",
                       "occurred_at": None, "merchant": "X", "masked_account": None,
                       "bank_ref_id": None, "fingerprint": "z", "detect_reason": None,
                       "template_id": None, "transaction_id": None,
                       "received_at": None, "resolved_at": None})
    assert client.post("/api/bank/sms-events/77/confirm", json={}, headers=auth_headers).status_code == 404
    assert client.post("/api/bank/sms-events/77/ignore", headers=auth_headers).status_code == 404
    assert client.patch("/api/bank/sms-events/77", json={"merchant": "hacked"}, headers=auth_headers).status_code == 404
    assert bdb.txns == []


def test_list_events_only_shows_own_and_pending_by_default(client, auth_headers, bdb):
    _detect(client, auth_headers, bdb)
    bdb.events.append({"id": 88, "student_id": 2, "connection_id": 1, "status": "needs_confirmation",
                       "fingerprint": "q", "direction": None, "amount": None, "occurred_on": None,
                       "occurred_at": None, "merchant": None, "masked_account": None,
                       "bank_ref_id": None, "detect_reason": None, "template_id": None,
                       "transaction_id": None, "received_at": None, "resolved_at": None})
    r = client.get("/api/bank/sms-events", headers=auth_headers).get_json()
    assert [e["id"] for e in r["events"]] == [1]


# ==================================================== sender normalisation
# Real-world blocker: the web app stored the sender as "hdfcbk" while the
# Android companion posted "HDFCBK", and the exact `!=` comparison rejected
# every real bank SMS with 202 "sender does not match". Comparison is now
# case/whitespace-insensitive — and NOTHING more: the allowlist is unchanged.

def test_sender_normalisation_helper_is_case_and_space_insensitive():
    from routes.bank import _normalise_sender, _sender_matches
    assert _normalise_sender("  hdfcbk ") == "HDFCBK"
    assert _normalise_sender(None) == ""
    assert _sender_matches("hdfcbk", "HDFCBK")
    assert _sender_matches("HDFCBK", "  hdfcbk  ")
    assert _sender_matches("HdFcBk", "hDfCbK")


def test_sender_normalisation_never_broadens_the_allowlist():
    from routes.bank import _sender_matches
    # carrier decoration is resolved on the phone, never here
    assert not _sender_matches("HDFCBK", "VM-HDFCBK")
    assert not _sender_matches("HDFCBK", "AD-HDFCBK-S")
    # no substring / prefix / suffix matching
    assert not _sender_matches("HDFCBK", "HDFCBKX")
    assert not _sender_matches("HDFCBK", "MYHDFCBK")
    assert not _sender_matches("HDFCBK", "HDFC")
    assert not _sender_matches("HDFCBK", "ICICIB")
    # an empty configured sender can never match anything
    assert not _sender_matches("", "HDFCBK")
    assert not _sender_matches(None, "")


def test_ingest_exact_sender_match_is_accepted(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb, sender="HDFCBK")
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 201
    assert len(bdb.events) == 1


@pytest.mark.parametrize("configured,posted", [
    ("hdfcbk", "HDFCBK"),   # the exact real-world failure
    ("HDFCBK", "hdfcbk"),
    ("HdFcBk", "hdfcbk"),
    ("HDFCBK", "  HDFCBK  "),
])
def test_ingest_sender_match_is_case_insensitive(client, auth_headers, bdb, configured, posted):
    _make_connection(client, auth_headers, bdb, sender=configured)
    r = client.post("/api/bank/sms-events",
                    json={"sender": posted, "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 201, r.get_json()
    assert len(bdb.events) == 1


@pytest.mark.parametrize("posted", ["VM-HDFCBK", "AD-HDFCBK-S", "HDFCBKX", "MYHDFCBK", "HDFC"])
def test_ingest_near_miss_senders_are_still_rejected(client, auth_headers, bdb, posted):
    _make_connection(client, auth_headers, bdb, sender="hdfcbk")
    r = client.post("/api/bank/sms-events",
                    json={"sender": posted, "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 202 and "ignored" in r.get_json()
    assert bdb.events == []


def test_ingest_unrelated_sender_is_rejected_regardless_of_case(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb, sender="hdfcbk")
    for posted in ("icicib", "ICICIB", "SOMERANDOM"):
        r = client.post("/api/bank/sms-events",
                        json={"sender": posted, "body": HDFC_DEBIT}, headers=auth_headers)
        assert r.status_code == 202
    assert bdb.events == []


def test_disabled_connection_still_ignored_with_case_difference(client, auth_headers, bdb):
    c = _make_connection(client, auth_headers, bdb, sender="hdfcbk")
    client.put(f"/api/bank/connections/{c['id']}", json={"enabled": False}, headers=auth_headers)
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT}, headers=auth_headers)
    assert r.status_code == 202 and bdb.events == []


def _token_headers(client, monkeypatch, sender):
    """Create a connection over JWT, return its X-Ingest-Token header."""
    from tests.conftest import FAKE_STUDENT
    monkeypatch.setattr("middleware.execute_query", lambda *a, **k: dict(FAKE_STUDENT))
    import jwt as pyjwt
    from config import Config
    jwt_hdr = {"Authorization": "Bearer " + pyjwt.encode(
        {"student_id": 1}, Config.SECRET_KEY, algorithm="HS256")}
    c = client.post("/api/bank/connections",
                    json={"bank_name": "HDFC", "sender_id": sender},
                    headers=jwt_hdr).get_json()
    return {"X-Ingest-Token": c["ingest_token"]}


def test_ingest_token_path_is_case_insensitive(client, bdb, monkeypatch):
    hdr = _token_headers(client, monkeypatch, "hdfcbk")
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT}, headers=hdr)
    assert r.status_code == 201 and r.get_json()["event"]["amount"] == "5000.00"


def test_ingest_token_path_still_rejects_a_different_sender(client, bdb, monkeypatch):
    hdr = _token_headers(client, monkeypatch, "hdfcbk")
    r = client.post("/api/bank/sms-events",
                    json={"sender": "ICICIB", "body": HDFC_DEBIT}, headers=hdr)
    assert r.status_code == 202 and bdb.events == []


def test_token_validation_is_unaffected_by_normalisation(client, bdb, monkeypatch):
    _token_headers(client, monkeypatch, "hdfcbk")
    # right sender, wrong token -> still 401, never 202/201
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "body": HDFC_DEBIT},
                    headers={"X-Ingest-Token": "not-a-real-token"})
    assert r.status_code == 401
    # no credential at all -> 401
    assert client.post("/api/bank/sms-events",
                       json={"sender": "HDFCBK", "body": HDFC_DEBIT}).status_code == 401
    assert bdb.events == []


def test_structured_ingest_works_with_case_differing_sender(client, auth_headers, bdb):
    """The companion's preferred path: on-device parse, no raw body, and the
    sender arrives in a different case than the stored connection."""
    _make_connection(client, auth_headers, bdb, sender="hdfcbk")
    r = client.post("/api/bank/sms-events",
                    json={"sender": "HDFCBK", "transaction": _structured()},
                    headers=auth_headers)
    assert r.status_code == 201, r.get_json()
    ev = r.get_json()["event"]
    assert ev["status"] == "needs_confirmation"
    assert ev["direction"] == "debit" and ev["amount"] == "5000.00"
    assert ev["merchant"] == "AMAZON" and ev["bank_ref_id"] == "402312345678"
    # still review-only: no money moved
    assert bdb.txns == []


def test_structured_ingest_case_difference_still_dedupes(client, auth_headers, bdb):
    _make_connection(client, auth_headers, bdb, sender="hdfcbk")
    first = client.post("/api/bank/sms-events",
                        json={"sender": "HDFCBK", "transaction": _structured()},
                        headers=auth_headers)
    again = client.post("/api/bank/sms-events",
                        json={"sender": "hdfcbk", "transaction": _structured()},
                        headers=auth_headers)
    assert first.status_code == 201
    assert again.status_code == 200 and again.get_json()["duplicate"] is True
    assert len(bdb.events) == 1
