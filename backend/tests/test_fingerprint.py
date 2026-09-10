"""Phase 15 — deterministic dedup fingerprint."""

from datetime import date
from decimal import Decimal

from ingestion import parse_sms, fingerprint
from ingestion.sms_parser import ParsedSms

HDFC_DEBIT = ("Rs.5000.00 debited from a/c XX4821 on 10-09-26 to AMAZON. "
              "UPI Ref 402312345678. Not you? Call 18002586161")


def test_same_event_same_fingerprint():
    a = fingerprint(7, parse_sms(HDFC_DEBIT))
    b = fingerprint(7, parse_sms(HDFC_DEBIT))
    assert a == b and len(a) == 64


def test_reference_id_is_preferred():
    p = parse_sms(HDFC_DEBIT)
    # a re-send with a slightly different body but the same ref -> same fingerprint
    p2 = ParsedSms(status=p.status, direction=p.direction, amount=Decimal("5000.00"),
                   occurred_on=p.occurred_on, merchant="AMZ", masked_account="4821",
                   bank_ref_id="402312345678")
    assert fingerprint(7, p) == fingerprint(7, p2)


def test_different_connection_different_fingerprint():
    p = parse_sms(HDFC_DEBIT)
    assert fingerprint(7, p) != fingerprint(8, p)


def test_no_ref_falls_back_to_fields():
    base = ParsedSms(status="needs_confirmation", direction="debit", amount=Decimal("800.00"),
                     occurred_on=date(2026, 9, 9), merchant="UBER", masked_account="9911")
    same = ParsedSms(status="needs_confirmation", direction="debit", amount=Decimal("800.00"),
                     occurred_on=date(2026, 9, 9), merchant="uber", masked_account="9911")
    changed = ParsedSms(status="needs_confirmation", direction="debit", amount=Decimal("801.00"),
                        occurred_on=date(2026, 9, 9), merchant="UBER", masked_account="9911")
    assert fingerprint(1, base) == fingerprint(1, same)          # merchant case-insensitive
    assert fingerprint(1, base) != fingerprint(1, changed)       # amount change


def test_pure():
    import inspect
    import ingestion.fingerprint as m
    src = inspect.getsource(m)
    for banned in ("import flask", "import requests", "execute_query", "ollama", "from database"):
        assert banned not in src
