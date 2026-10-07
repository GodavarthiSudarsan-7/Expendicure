"""Deterministic pattern tables for bank-SMS parsing.

No LLM, no network, no DB. Just regexes and keyword lists. Kept in one place so
adding support for another bank's SMS format is a data change, not a code change.
"""

import re

# --------------------------------------------------------------- reject filters
# A message is dropped BEFORE any extraction if it looks like one of these and
# does not also carry a strong transaction keyword.
OTP_RE = re.compile(
    r"\b(otp|one[\s-]?time\s?password|verification code|security code|"
    r"do not share|don'?t share|never share (it|this|your otp)|"
    r"passcode|auth(entication)? code)\b",
    re.I,
)
PROMO_RE = re.compile(
    r"\b(\d+%\s*off|flat\s*\d+%|discount|cashback offer|mega sale|big sale|"
    r"coupon|promo code|pre[\s-]?approved|apply now|congratulations|you\s+won|"
    r"limited period|limited time|hurry|lowest price|best deal|festive offer|"
    r"upgrade your card|increase your limit|instant loan|personal loan offer)\b",
    re.I,
)

# --------------------------------------------------------------- direction
DEBIT_RE = re.compile(
    r"\b(debited|debit|spent|withdrawn|withdrawal|paid|payment of|purchase of|"
    r"purchased|sent|transferred to|transferred from|txn of|dr\b|deducted)\b",
    re.I,
)

# A balance statement, not a transaction: "Balance is Rs.X", "Bal: Rs.X".
# Requires "is" or ":" straight after the word, so the trailing "Avl Bal Rs.X"
# on a REAL debit/credit alert is not caught by this.
BALANCE_ONLY_RE = re.compile(
    r"\b(?:available\s+balance|avl\.?\s*balance|balance|bal)\b\s*(?:is\b|:)",
    re.I,
)
CREDIT_RE = re.compile(
    r"\b(credited|credit|received|deposited|refund(ed)?|added to|cr\b|"
    r"money added|cashback of)\b",
    re.I,
)
# any transaction keyword at all — used to rescue a message that also trips a
# promo keyword (e.g. "cashback of Rs 50 credited")
TXN_KEYWORD_RE = re.compile(
    r"\b(debited|credited|spent|withdrawn|deposited|received|paid|"
    r"transaction|txn|a/c|acct|account|upi|imps|neft|rtgs|ref no|avl bal|"
    r"available balance)\b",
    re.I,
)
# past-tense "this already happened" keywords. An OTP message that also mentions
# a transaction (e.g. "OTP for txn of Rs 5000 at Amazon") has NONE of these, so
# it is still rejected as an OTP rather than ingested.
COMPLETED_TXN_RE = re.compile(
    r"\b(debited|credited|spent|withdrawn|withdrawal|deposited|received|"
    r"refunded|transferred to|w/d|has been (debited|credited))\b",
    re.I,
)

# --------------------------------------------------------------- amount
# INR 1,234.56 / Rs. 1234 / ₹5,00,000 / Rs 50 / Rs 5k
# The scale word must be whitespace-separated AND word-bounded so it never eats
# the start of the next word (e.g. "5000.00 credited" must NOT read "cr").
# The currency token may be followed by '.', ':' or '-' before the digits.
# Union Bank writes "Rs:100.00"; others write "Rs.100.00" or "Rs 100.00".
# `\brs\b` keeps this anchored to the word "Rs" so "24 hrs" never matches.
# NOTE: kept byte-for-byte in step with the on-device Android parser
# (companion/android/.../SmsTransactionParser.kt) — the two are one contract.
AMOUNT_RE = re.compile(
    r"(?:\binr\b|\brs\b|₹)\s*[.:\-]?\s*"
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?:\s*(k|lakh|lac|crore|cr)\b)?",
    re.I,
)
SCALE = {"k": 1_000, "lakh": 100_000, "lac": 100_000, "cr": 10_000_000, "crore": 10_000_000}

# --------------------------------------------------------------- masked account
ACCOUNT_RE = re.compile(
    r"\b(?:a/?c|acct|account|card)\s*(?:no\.?|number|ending|ending in)?\s*"
    r"[:#]?\s*(?:x+|\*+|xx|no\s)?\s*(\d{3,6})\b",
    re.I,
)

# --------------------------------------------------------------- reference id
REF_RE = re.compile(
    r"\b(?:upi(?:\s*(?:ref(?:erence)?)?(?:\s*(?:no|id))?)?|ref(?:erence)?"
    r"(?:\s*(?:no|id))?|txn(?:\s*(?:no|id))?|transaction\s*(?:no|id)|"
    r"rrn|utr)\s*[:.\-#]?\s*([A-Za-z0-9]{6,40})\b",
    re.I,
)

# --------------------------------------------------------------- merchant
MERCHANT_RE = re.compile(
    r"\b(?:at|to|towards|via vpa|vpa|@)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 &._@'\-]{1,60}?)"
    # also stop at an opening bracket — "credited to payee@bank (UPI Ref no ...)".
    # Kept in step with the on-device Android parser.
    r"(?=\s+(?:on|ref|upi|txn|avl|bal|a/?c|dated|not you|call|if not|info)\b"
    r"|\s*\(|[.,;\n]|$)",
    re.I,
)
_MERCHANT_STRIP = re.compile(r"\b(on|ref|upi|txn|dated|avl bal|a/?c)\b.*$", re.I)
# a merchant capture that is really a stopword / an amount / an account
MERCHANT_NOISE_RE = re.compile(
    r"^(your|the|my|a/?c|acct|account|bank|self|upi|rs\.?|inr|₹|\d[\d,. ]*)$",
    re.I,
)

# --------------------------------------------------------------- date
DATE_TOKEN_RE = re.compile(
    r"\b(\d{1,2}[-/\. ](?:\d{1,2}|[A-Za-z]{3,9})[-/\. ]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})\b"
)
DATE_FORMATS = (
    "%d-%m-%Y", "%d-%m-%y", "%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y", "%d.%m.%y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d/%b/%Y", "%d/%b/%y",
    "%d-%B-%Y", "%d %B %Y", "%Y-%m-%d",
)

# --------------------------------------------------------------- bank templates
# Optional strict per-bank patterns. When one matches cleanly we tag the event
# with template_id (telemetry / display only — review-only mode routes every
# event to the user regardless). `sender_hint` is informational.
TEMPLATES = (
    # Union Bank first: its footer makes these unambiguous, and the looser
    # generic templates below would otherwise claim them. Debit before credit
    # because a UPI debit alert reads "... Debited ... and credited to <payee>".
    {
        "id": "union_debit_v1",
        "sender_hint": "UNIONB",
        "re": re.compile(
            r"\bdebited\b.*\bunion bank\b|\bunion bank\b.*\bdebited\b",
            re.I | re.S),
    },
    {
        "id": "union_credit_v1",
        "sender_hint": "UNIONB",
        "re": re.compile(
            r"\bcredited\b.*\bunion bank\b|\bunion bank\b.*\bcredited\b",
            re.I | re.S),
    },
    {
        "id": "hdfc_debit_v1",
        "sender_hint": "HDFCBK",
        "re": re.compile(
            r"(?:rs\.?|inr)\s*[\d,]+(?:\.\d{1,2})?\s+debited\s+from\s+a/?c\s*x*\d{3,6}.*?\bto\b",
            re.I | re.S),
    },
    {
        "id": "sbi_credit_v1",
        "sender_hint": "SBIINB",
        "re": re.compile(
            r"\bcredited\b.*?(?:rs\.?|inr)\s*[\d,]+(?:\.\d{1,2})?.*?\ba/?c\b",
            re.I | re.S),
    },
    {
        "id": "icici_txn_v1",
        "sender_hint": "ICICIB",
        "re": re.compile(
            r"\bacct?\s*x*\d{3,6}\b.*?(?:debited|credited)\b.*?(?:rs\.?|inr)\s*[\d,]+",
            re.I | re.S),
    },
    {
        "id": "upi_generic_v1",
        "sender_hint": None,
        "re": re.compile(
            r"\bupi\b.*?(?:debited|credited|paid|received).*?(?:rs\.?|inr|₹)\s*[\d,]+",
            re.I | re.S),
    },
)
