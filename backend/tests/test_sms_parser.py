"""Phase 15 — deterministic bank-SMS parser. Pure: no DB, no network, no LLM."""

from datetime import date
from decimal import Decimal

import pytest

from ingestion import parse_sms
from ingestion.sms_parser import (
    STATUS_NEEDS_CONFIRMATION, STATUS_NEEDS_REVIEW, STATUS_REJECTED, DEBIT, CREDIT,
)

D = Decimal

HDFC_DEBIT = ("Rs.5000.00 debited from a/c XX4821 on 10-09-26 to AMAZON. "
              "UPI Ref 402312345678. Not you? Call 18002586161")
SBI_CREDIT = ("Dear Customer, Rs.15000.00 credited to your A/c XXXXX1234 on "
              "05-Sep-2026 by transfer from SALARY. Avl Bal Rs.42350.10. Ref no 998877.")
CARD_DEBIT = ("Rs 800 spent on HDFC Bank Card xx9911 at UBER on 09-09-2026. "
              "Avl limit Rs 20000.")
NEFT_CREDIT = "Rs 2 lakh credited to a/c XX1234 on 01-09-2026 by NEFT. Ref 55667788."


# --------------------------------------------------------------- happy paths
def test_valid_debit_sms_is_needs_confirmation():
    p = parse_sms(HDFC_DEBIT)
    assert p.status == STATUS_NEEDS_CONFIRMATION
    assert p.direction == DEBIT
    assert p.amount == D("5000.00")
    assert p.occurred_on == date(2026, 9, 10)
    assert p.merchant == "AMAZON"
    assert p.masked_account == "4821"
    assert p.bank_ref_id == "402312345678"
    assert p.template_id == "hdfc_debit_v1"


def test_valid_credit_sms():
    p = parse_sms(SBI_CREDIT)
    assert p.status == STATUS_NEEDS_CONFIRMATION
    assert p.direction == CREDIT
    assert p.amount == D("15000.00")
    assert p.occurred_on == date(2026, 9, 5)
    assert p.bank_ref_id == "998877"


def test_amount_extraction_variants():
    assert parse_sms(CARD_DEBIT).amount == D("800.00")
    assert parse_sms(NEFT_CREDIT).amount == D("200000.00")           # "2 lakh"
    assert parse_sms("INR 1,234.56 debited a/c XX11 to FOO ref 12345678").amount == D("1234.56")
    assert parse_sms("Rs 5k spent at CAFE a/c XX22 ref 87654321 on 01-09-2026").amount == D("5000.00")


def test_scale_word_does_not_eat_the_next_word():
    # "5000.00 credited" must NOT be read as 5000 * crore
    assert parse_sms(SBI_CREDIT).amount == D("15000.00")


def test_merchant_extraction():
    assert parse_sms(HDFC_DEBIT).merchant == "AMAZON"
    assert parse_sms(CARD_DEBIT).merchant == "UBER"


def test_date_formats():
    for body, expected in [
        ("Rs 10 debited a/c XX1 to X on 10-09-26 ref 11111111", date(2026, 9, 10)),
        ("Rs 10 debited a/c XX1 to X on 10/09/2026 ref 11111111", date(2026, 9, 10)),
        ("Rs 10 debited a/c XX1 to X on 05-Sep-2026 ref 11111111", date(2026, 9, 5)),
        ("Rs 10 debited a/c XX1 to X on 2026-09-01 ref 11111111", date(2026, 9, 1)),
    ]:
        assert parse_sms(body).occurred_on == expected


def test_masked_account_last_digits_only():
    p = parse_sms(HDFC_DEBIT)
    assert p.masked_account == "4821" and len(p.masked_account) <= 6


# --------------------------------------------------------------- rejections
@pytest.mark.parametrize("body,why", [
    ("123456 is your OTP for txn of Rs 5000 at Amazon. Do not share it. -HDFCBK", "otp"),
    ("OTP 998877 for your purchase of Rs 2000. Never share your OTP.", "otp"),
    ("Get 50% OFF your next order! Use SAVE50. Limited time offer. -Zomato", "promo"),
    ("Pre-approved personal loan of Rs 5,00,000. Apply now! Lowest price.", "promo"),
    ("Your Amazon package will be delivered today between 10 AM - 2 PM.", "not a transaction"),
    ("Your account was accessed from a new device. If not you, call us.", "not a transaction"),
    ("", "empty"),
    ("   ", "empty"),
])
def test_non_transaction_messages_are_rejected(body, why):
    p = parse_sms(body)
    assert p.status == STATUS_REJECTED
    assert p.amount is None and p.direction is None


def test_otp_that_also_reports_a_completed_debit_is_kept():
    # some banks bundle a balance alert with an OTP
    p = parse_sms("Rs 100 debited a/c XX55 to SHOP on 01-09-2026 ref 12341234. "
                  "OTP 4455 for the next step.")
    assert p.status in (STATUS_NEEDS_CONFIRMATION, STATUS_NEEDS_REVIEW)
    assert p.amount == D("100.00") and p.direction == DEBIT


def test_huge_body_rejected():
    assert parse_sms("Rs 100 debited " + "x" * 2000).status == STATUS_REJECTED


# --------------------------------------------------------------- needs_review
def test_amount_without_direction_is_needs_review():
    p = parse_sms("Rs 2,000.00 transaction on a/c XX7788 on 12/09/2026.")
    assert p.status == STATUS_NEEDS_REVIEW
    assert p.amount == D("2000.00") and p.direction is None


def test_missing_date_is_needs_review():
    p = parse_sms("Rs 350 debited from a/c XX4821 to CAFE. UPI Ref 402312345678.")
    assert p.status == STATUS_NEEDS_REVIEW
    assert "date" in p.reason.lower()
    assert p.amount == D("350.00") and p.direction == DEBIT


def test_unclear_merchant_and_no_ref_is_needs_review():
    p = parse_sms("INR 2,000.00 credited to A/c no. XX7788 on 12/09/2026. Avbl Bal INR 8,900.00")
    assert p.status == STATUS_NEEDS_REVIEW


# --------------------------------------------------------------- robustness
def test_parser_never_raises_on_garbage():
    for junk in [None, 123, "\x00\x01", "₹₹₹", "debited " * 50, "Rs credited a/c"]:
        p = parse_sms(junk)
        assert p.status in (STATUS_NEEDS_CONFIRMATION, STATUS_NEEDS_REVIEW, STATUS_REJECTED)


def test_deterministic():
    a, b = parse_sms(HDFC_DEBIT).to_dict(), parse_sms(HDFC_DEBIT).to_dict()
    assert a == b


def test_to_dict_is_json_safe():
    import json
    json.dumps(parse_sms(HDFC_DEBIT).to_dict())


def test_module_is_pure():
    import inspect
    import ingestion.sms_parser as m
    src = inspect.getsource(m)
    for banned in ("import flask", "import requests", "execute_query", "from database",
                   "from finance_db", "ollama", "openai", "anthropic", "from agent",
                   "from decision", "from knowledge"):
        assert banned not in src
