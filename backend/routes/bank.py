"""Phase 15 — privacy-first bank SMS -> Financial Twin (REVIEW-ONLY).

A message is processed only when its sender matches an ENABLED bank_connections
row owned by the authenticated user AND it parses as a completed transaction.
Everything else is ignored (HTTP 202, never an error). Nothing enters the
Financial Twin automatically: every detected event is created as
``needs_confirmation`` / ``needs_review`` and the user must Confirm / Edit /
Ignore. Confirming inserts a row into the EXISTING ``transactions`` table via
``routes.transactions.insert_transaction`` — there is no parallel money store.

The raw SMS body is never persisted and never returned by any endpoint.
"""

import hashlib
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from database import execute_query
from date_filters import parse_iso_date
from finance.categorize import resolve_category_id
from finance.models import (
    CategorizationRule, Category, DIRECTIONS,
    SMS_NEEDS_CONFIRMATION, SMS_NEEDS_REVIEW, SMS_CONFIRMED, SMS_IGNORED,
    SMS_PENDING_STATUSES,
)
from ingestion import parse_sms, fingerprint
from middleware import token_required, bearer_token, student_from_token
from routes.transactions import insert_transaction, TXN_SELECT

bank_bp = Blueprint("bank", __name__)

MAX_SENDER_LEN = 40
MAX_BODY_LEN = 1200

CONN_COLS = (
    "id, student_id, bank_name, sender_id, masked_account, enabled, "
    "last_event_at, events_detected, created_at, updated_at"
)
EVENT_COLS = (
    "id, student_id, connection_id, status, direction, amount, occurred_on, "
    "occurred_at, merchant, masked_account, bank_ref_id, detect_reason, "
    "template_id, transaction_id, received_at, resolved_at"
)


# ------------------------------------------------------------------ helpers

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mask(acc):
    if not acc:
        return None
    digits = "".join(ch for ch in str(acc) if ch.isdigit())
    return digits[-6:] or None


def _conn_row(student_id, conn_id):
    return execute_query(
        f"SELECT {CONN_COLS} FROM bank_connections WHERE id = %s AND student_id = %s",
        (conn_id, student_id), fetch_one=True,
    )


def _pending_count(student_id):
    row = execute_query(
        "SELECT COUNT(*) AS n FROM bank_sms_events "
        "WHERE student_id = %s AND status IN ('needs_confirmation','needs_review')",
        (student_id,), fetch_one=True,
    )
    return int((row or {}).get("n") or 0)


def _conn_public(row, *, student_id=None):
    d = {
        "id": row["id"],
        "bank_name": row["bank_name"],
        "sender_id": row["sender_id"],
        "masked_account": row.get("masked_account"),
        "enabled": bool(row.get("enabled", True)),
        "last_event_at": row.get("last_event_at"),
        "events_detected": int(row.get("events_detected") or 0),
    }
    if student_id is not None:
        d["pending_review"] = _pending_count(student_id)
    return d


def _event_public(row):
    """Structured fields only — NEVER any raw message text."""
    return {
        "id": row["id"],
        "connection_id": row["connection_id"],
        "status": row["status"],
        "direction": row.get("direction"),
        "amount": (str(row["amount"]) if row.get("amount") is not None else None),
        "occurred_on": (row["occurred_on"].isoformat()
                        if hasattr(row.get("occurred_on"), "isoformat") else row.get("occurred_on")),
        "merchant": row.get("merchant"),
        "masked_account": row.get("masked_account"),
        "bank_ref_id": row.get("bank_ref_id"),
        "detect_reason": row.get("detect_reason"),
        "template_id": row.get("template_id"),
        "transaction_id": row.get("transaction_id"),
    }


def _amount_ok(raw):
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None, "amount must be a number"
    if v.is_nan() or v.is_infinite() or v <= 0:
        return None, "amount must be a positive number"
    return v, None


# ------------------------------------------------------------ connection CRUD

@bank_bp.route("/connections", methods=["GET"], strict_slashes=False)
@token_required
def list_connections(current_student):
    sid = current_student["id"]
    rows = execute_query(
        f"SELECT {CONN_COLS} FROM bank_connections WHERE student_id = %s ORDER BY id",
        (sid,), fetch_all=True,
    )
    if rows is None:
        return jsonify({"error": "Failed to fetch connections"}), 500
    return jsonify({
        "connections": [_conn_public(r) for r in rows],
        "pending_review": _pending_count(sid),
    })


@bank_bp.route("/connections", methods=["POST"], strict_slashes=False)
@token_required
def create_connection(current_student):
    sid = current_student["id"]
    data = request.get_json(silent=True) or {}
    bank_name = str(data.get("bank_name") or "").strip()
    sender_id = str(data.get("sender_id") or "").strip()
    if not bank_name:
        return jsonify({"error": "bank_name is required"}), 400
    if not sender_id or len(sender_id) > MAX_SENDER_LEN:
        return jsonify({"error": "sender_id is required (max 40 chars)"}), 400

    dup = execute_query(
        "SELECT id FROM bank_connections WHERE student_id = %s AND sender_id = %s",
        (sid, sender_id), fetch_one=True,
    )
    if dup is not None:
        return jsonify({"error": "a connection for that sender already exists"}), 409

    raw_token = secrets.token_urlsafe(24)
    new_id = execute_query(
        "INSERT INTO bank_connections "
        "(student_id, bank_name, sender_id, masked_account, enabled, ingest_token_hash) "
        "VALUES (%s, %s, %s, %s, TRUE, %s)",
        (sid, bank_name[:80], sender_id, _mask(data.get("masked_account")), _hash_token(raw_token)),
        commit=True,
    )
    if new_id is None:
        return jsonify({"error": "Failed to create connection"}), 500
    row = _conn_row(sid, new_id)
    body = _conn_public(row, student_id=sid)
    body["ingest_token"] = raw_token   # shown exactly once
    return jsonify(body), 201


@bank_bp.route("/connections/<int:conn_id>", methods=["PUT"])
@token_required
def update_connection(current_student, conn_id):
    sid = current_student["id"]
    if _conn_row(sid, conn_id) is None:
        return jsonify({"error": "Connection not found or unauthorized"}), 404
    data = request.get_json(silent=True) or {}
    sets, params = [], []
    if "enabled" in data:
        sets.append("enabled = %s")
        params.append(bool(data["enabled"]))
    if "bank_name" in data and str(data["bank_name"]).strip():
        sets.append("bank_name = %s")
        params.append(str(data["bank_name"]).strip()[:80])
    if "masked_account" in data:
        sets.append("masked_account = %s")
        params.append(_mask(data["masked_account"]))
    if not sets:
        return jsonify({"error": "no fields to update"}), 400
    params.append(conn_id)
    if execute_query(f"UPDATE bank_connections SET {', '.join(sets)} WHERE id = %s",
                     tuple(params), commit=True) is None:
        return jsonify({"error": "Failed to update connection"}), 500
    return jsonify(_conn_public(_conn_row(sid, conn_id), student_id=sid))


@bank_bp.route("/connections/<int:conn_id>/rotate-token", methods=["POST"])
@token_required
def rotate_token(current_student, conn_id):
    sid = current_student["id"]
    if _conn_row(sid, conn_id) is None:
        return jsonify({"error": "Connection not found or unauthorized"}), 404
    raw_token = secrets.token_urlsafe(24)
    if execute_query("UPDATE bank_connections SET ingest_token_hash = %s WHERE id = %s",
                     (_hash_token(raw_token), conn_id), commit=True) is None:
        return jsonify({"error": "Failed to rotate token"}), 500
    return jsonify({"id": conn_id, "ingest_token": raw_token})


@bank_bp.route("/connections/<int:conn_id>", methods=["DELETE"])
@token_required
def delete_connection(current_student, conn_id):
    sid = current_student["id"]
    if _conn_row(sid, conn_id) is None:
        return jsonify({"error": "Connection not found or unauthorized"}), 404
    if execute_query("DELETE FROM bank_connections WHERE id = %s", (conn_id,), commit=True) is None:
        return jsonify({"error": "Failed to delete connection"}), 500
    return jsonify({"message": "Connection removed"}), 200


# --------------------------------------------------------- SMS event ingestion

def _ingest_identity():
    """Resolve (student_id, connection_id_or_None). Accepts a per-connection
    X-Ingest-Token OR a normal user JWT. Returns (None, None) if neither."""
    ingest = request.headers.get("X-Ingest-Token")
    if ingest:
        row = execute_query(
            "SELECT id, student_id, enabled FROM bank_connections WHERE ingest_token_hash = %s",
            (_hash_token(ingest.strip()),), fetch_one=True,
        )
        if row is None or not row.get("enabled", True):
            return None, None
        return row["student_id"], row["id"]
    st = student_from_token(bearer_token())
    if st:
        return st["id"], None
    return None, None


@bank_bp.route("/sms-events", methods=["POST"], strict_slashes=False)
def ingest_sms_event():
    student_id, token_conn_id = _ingest_identity()
    if student_id is None:
        return jsonify({"error": "authentication required"}), 401

    data = request.get_json(silent=True) or {}
    sender = str(data.get("sender") or "").strip()
    body = data.get("body")
    if not sender or not isinstance(body, str) or not body.strip():
        return jsonify({"error": "sender and body are required"}), 400
    if len(body) > MAX_BODY_LEN:
        return jsonify({"ignored": "message too long to be a bank alert"}), 202

    # --- sender verification (deterministic) ---
    if token_conn_id is not None:
        conn = _conn_row(student_id, token_conn_id)
        if conn is None or not conn.get("enabled", True) or conn["sender_id"] != sender:
            return jsonify({"ignored": "sender does not match this connection"}), 202
    else:
        conn = execute_query(
            f"SELECT {CONN_COLS} FROM bank_connections "
            "WHERE student_id = %s AND sender_id = %s AND enabled = TRUE",
            (student_id, sender), fetch_one=True,
        )
        if conn is None:
            return jsonify({"ignored": "sender is not a configured, enabled bank"}), 202

    # --- transaction detection + extraction (deterministic, no LLM) ---
    parsed = parse_sms(body)
    if parsed.rejected:
        # nothing is stored for a message we are ignoring
        return jsonify({"ignored": parsed.reason}), 202

    fp = fingerprint(conn["id"], parsed)
    existing = execute_query(
        "SELECT id, status FROM bank_sms_events WHERE connection_id = %s AND fingerprint = %s",
        (conn["id"], fp), fetch_one=True,
    )
    if existing is not None:
        return jsonify({"duplicate": True, "event_id": existing["id"],
                        "status": existing["status"]}), 200

    new_id = execute_query(
        "INSERT INTO bank_sms_events "
        "(student_id, connection_id, status, direction, amount, occurred_on, "
        " merchant, masked_account, bank_ref_id, fingerprint, detect_reason, template_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            student_id, conn["id"], parsed.status, parsed.direction,
            str(parsed.amount) if parsed.amount is not None else None,
            parsed.occurred_on.isoformat() if parsed.occurred_on else None,
            parsed.merchant, parsed.masked_account or conn.get("masked_account"),
            parsed.bank_ref_id, fp, (parsed.reason or None), parsed.template_id,
        ),
        commit=True,
    )
    if new_id is None:
        return jsonify({"error": "could not record the transaction event"}), 500

    execute_query(
        "UPDATE bank_connections SET events_detected = events_detected + 1, "
        "last_event_at = CURRENT_TIMESTAMP WHERE id = %s",
        (conn["id"],), commit=True,
    )
    row = execute_query(f"SELECT {EVENT_COLS} FROM bank_sms_events WHERE id = %s",
                        (new_id,), fetch_one=True)
    return jsonify({"event": _event_public(row)}), 201


@bank_bp.route("/sms-events", methods=["GET"], strict_slashes=False)
@token_required
def list_sms_events(current_student):
    sid = current_student["id"]
    status = request.args.get("status")
    sql = f"SELECT {EVENT_COLS} FROM bank_sms_events WHERE student_id = %s"
    params = [sid]
    if status == "pending" or status is None:
        sql += " AND status IN ('needs_confirmation','needs_review')"
    elif status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT 100"
    rows = execute_query(sql, tuple(params), fetch_all=True)
    if rows is None:
        return jsonify({"error": "Failed to fetch events"}), 500
    return jsonify({"events": [_event_public(r) for r in rows]})


def _owned_pending_event(student_id, event_id):
    return execute_query(
        f"SELECT {EVENT_COLS} FROM bank_sms_events WHERE id = %s AND student_id = %s",
        (event_id, student_id), fetch_one=True,
    )


@bank_bp.route("/sms-events/<int:event_id>", methods=["PATCH"])
@token_required
def edit_sms_event(current_student, event_id):
    sid = current_student["id"]
    ev = _owned_pending_event(sid, event_id)
    if ev is None:
        return jsonify({"error": "Event not found or unauthorized"}), 404
    if ev["status"] not in SMS_PENDING_STATUSES:
        return jsonify({"error": "this event has already been resolved"}), 409

    data = request.get_json(silent=True) or {}
    sets, params = [], []
    if "amount" in data:
        amt, err = _amount_ok(data["amount"])
        if err:
            return jsonify({"error": err}), 400
        sets.append("amount = %s"); params.append(str(amt))
    if "direction" in data:
        d = str(data["direction"]).lower()
        if d not in DIRECTIONS:
            return jsonify({"error": "direction must be 'debit' or 'credit'"}), 400
        sets.append("direction = %s"); params.append(d)
    if "merchant" in data:
        sets.append("merchant = %s"); params.append(str(data["merchant"]).strip()[:120] or None)
    if "occurred_on" in data:
        try:
            sets.append("occurred_on = %s")
            params.append(parse_iso_date(data["occurred_on"]).isoformat())
        except ValueError:
            return jsonify({"error": "occurred_on must be a valid YYYY-MM-DD date"}), 400
    if not sets:
        return jsonify({"error": "no fields to update"}), 400
    params.append(event_id)
    if execute_query(f"UPDATE bank_sms_events SET {', '.join(sets)} WHERE id = %s",
                     tuple(params), commit=True) is None:
        return jsonify({"error": "Failed to update event"}), 500
    return jsonify({"event": _event_public(_owned_pending_event(sid, event_id))})


@bank_bp.route("/sms-events/<int:event_id>/ignore", methods=["POST"])
@token_required
def ignore_sms_event(current_student, event_id):
    sid = current_student["id"]
    ev = _owned_pending_event(sid, event_id)
    if ev is None:
        return jsonify({"error": "Event not found or unauthorized"}), 404
    if ev["status"] not in SMS_PENDING_STATUSES:
        return jsonify({"error": "this event has already been resolved"}), 409
    execute_query(
        "UPDATE bank_sms_events SET status = %s, resolved_at = CURRENT_TIMESTAMP WHERE id = %s",
        (SMS_IGNORED, event_id), commit=True,
    )
    return jsonify({"event": _event_public(_owned_pending_event(sid, event_id))})


@bank_bp.route("/sms-events/<int:event_id>/confirm", methods=["POST"])
@token_required
def confirm_sms_event(current_student, event_id):
    sid = current_student["id"]
    ev = _owned_pending_event(sid, event_id)
    if ev is None:
        return jsonify({"error": "Event not found or unauthorized"}), 404
    if ev["status"] not in SMS_PENDING_STATUSES:
        return jsonify({"error": "this event has already been resolved"}), 409

    o = request.get_json(silent=True) or {}

    # amount
    amount, err = _amount_ok(o["amount"] if "amount" in o else ev["amount"])
    if err or amount is None:
        return jsonify({"error": "Transaction details could not be verified — set an amount."}), 422

    # direction
    direction = str(o.get("direction") or ev.get("direction") or "").lower()
    if direction not in DIRECTIONS:
        return jsonify({"error": "Transaction details could not be verified — set debit or credit."}), 422

    # date
    if o.get("occurred_on"):
        try:
            occurred_on = parse_iso_date(o["occurred_on"])
        except ValueError:
            return jsonify({"error": "occurred_on must be a valid YYYY-MM-DD date"}), 400
    elif ev.get("occurred_on"):
        occurred_on = ev["occurred_on"] if hasattr(ev["occurred_on"], "isoformat") else parse_iso_date(str(ev["occurred_on"]))
    else:
        occurred_on = date.today()

    merchant = (str(o.get("merchant") or ev.get("merchant") or "Bank transaction").strip() or "Bank transaction")[:100]

    # category
    category_id = o.get("category_id")
    if category_id is not None:
        if execute_query("SELECT id FROM categories WHERE id = %s", (category_id,), fetch_one=True) is None:
            return jsonify({"error": "category_id does not exist"}), 400
    else:
        rule_rows = execute_query(
            "SELECT id, student_id, match_type, pattern, category_id, priority "
            "FROM categorization_rules WHERE student_id = %s OR student_id IS NULL "
            "ORDER BY priority, id", (sid,), fetch_all=True,
        ) or []
        cat_rows = execute_query(
            "SELECT id, name, is_default, student_id FROM categories "
            "WHERE student_id = %s OR student_id IS NULL", (sid,), fetch_all=True,
        ) or []
        rules = [CategorizationRule(id=r["id"], student_id=r.get("student_id"),
                                    match_type=r["match_type"], pattern=r["pattern"],
                                    category_id=r["category_id"], priority=r.get("priority", 100))
                 for r in rule_rows]
        cats = [Category(id=c["id"], name=c["name"],
                         is_default=bool(c.get("is_default")), student_id=c.get("student_id"))
                for c in cat_rows]
        category_id = resolve_category_id(merchant, rules=rules, categories=cats)
    if category_id is None:
        return jsonify({"error": "No category available — pass category_id."}), 422

    txn_id = insert_transaction(
        sid, amount=amount, direction=direction, merchant_name=merchant,
        category_id=category_id, payment_date=occurred_on.isoformat(),
        payment_method="bank_sms", notes=(ev.get("bank_ref_id") or None),
    )
    if txn_id is None:
        return jsonify({"error": "Failed to add the transaction"}), 500

    execute_query(
        "UPDATE bank_sms_events SET status = %s, transaction_id = %s, "
        "direction = %s, amount = %s, occurred_on = %s, merchant = %s, "
        "resolved_at = CURRENT_TIMESTAMP WHERE id = %s",
        (SMS_CONFIRMED, txn_id, direction, str(amount), occurred_on.isoformat(), merchant, event_id),
        commit=True,
    )
    return jsonify({
        "event": _event_public(_owned_pending_event(sid, event_id)),
        "transaction": execute_query(TXN_SELECT, (txn_id,), fetch_one=True),
    }), 201
