"""Deterministic bank-SMS transaction extraction.

    body  ->  reject filter  ->  direction + amount  ->  date / merchant /
              account / ref  ->  confidence  ->  ParsedSms

Pure: ``re`` + ``datetime`` + ``decimal`` + ``finance.money`` only. No Flask, no
DB, no network, no LLM. The parser never decides whether a transaction is
"true" — it only structures what the SMS unambiguously says, and flags anything
uncertain as ``needs_review`` so the user resolves it.
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

from finance.money import money
from ingestion import patterns as P

STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_REJECTED = "rejected"

DEBIT = "debit"
CREDIT = "credit"

# body length guard — real bank SMS are short; anything huge is not one.
MAX_BODY_LEN = 1000


@dataclass(frozen=True)
class ParsedSms:
    status: str                       # needs_confirmation | needs_review | rejected
    reason: str = ""                  # why review / why rejected
    direction: Optional[str] = None
    amount: Optional[Decimal] = None
    occurred_on: Optional[date] = None
    merchant: Optional[str] = None
    masked_account: Optional[str] = None
    bank_ref_id: Optional[str] = None
    template_id: Optional[str] = None

    @property
    def rejected(self) -> bool:
        return self.status == STATUS_REJECTED

    @property
    def usable(self) -> bool:
        """A transaction the user can act on (confirm or edit)."""
        return self.status in (STATUS_NEEDS_CONFIRMATION, STATUS_NEEDS_REVIEW)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "direction": self.direction,
            "amount": str(self.amount) if self.amount is not None else None,
            "occurred_on": self.occurred_on.isoformat() if self.occurred_on else None,
            "merchant": self.merchant,
            "masked_account": self.masked_account,
            "bank_ref_id": self.bank_ref_id,
            "template_id": self.template_id,
        }


def _reject(reason: str) -> ParsedSms:
    return ParsedSms(status=STATUS_REJECTED, reason=reason)


def _amount_from(text: str) -> Optional[Decimal]:
    m = P.AMOUNT_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    scale = (m.group(2) or "").lower()
    if scale in P.SCALE:
        value = value * P.SCALE[scale]
    if value <= 0:
        return None
    try:
        return money(value)
    except (ValueError, InvalidOperation):
        return None


def _norm_sep(s: str) -> str:
    return s.replace(".", "-").replace("/", "-").replace(" ", "-")


def _date_from(text: str) -> Optional[date]:
    seen_fmts = tuple(dict.fromkeys(_norm_sep(f) for f in P.DATE_FORMATS))
    for tok in P.DATE_TOKEN_RE.findall(text):
        cleaned = _norm_sep(tok.strip())
        for fmt in seen_fmts:
            try:
                d = datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
            if 2000 <= d.year <= 2100:
                return d
    return None


def _merchant_from(text: str) -> Optional[str]:
    m = P.MERCHANT_RE.search(text)
    if not m:
        return None
    name = P._MERCHANT_STRIP.sub("", m.group(1)).strip(" .-_")
    name = " ".join(name.split())
    if not name or len(name) < 2 or P.MERCHANT_NOISE_RE.match(name):
        return None
    return name[:120]


def _account_from(text: str) -> Optional[str]:
    m = P.ACCOUNT_RE.search(text)
    return m.group(1)[-6:] if m else None


def _ref_from(text: str) -> Optional[str]:
    for m in P.REF_RE.finditer(text):
        ref = m.group(1)
        # a real bank reference / RRN / UTR always contains a digit; this also
        # rejects English words the loose regex can catch ("refund", "number").
        if any(ch.isdigit() for ch in ref) and ref.lower() not in ("no", "id", "number"):
            return ref
    return None


def _template_id(text: str) -> Optional[str]:
    for t in P.TEMPLATES:
        if t["re"].search(text):
            return t["id"]
    return None


def _direction_from(text: str) -> Optional[str]:
    d = P.DEBIT_RE.search(text)
    c = P.CREDIT_RE.search(text)
    if d and c:
        return DEBIT if d.start() <= c.start() else CREDIT
    if d:
        return DEBIT
    if c:
        return CREDIT
    return None


def parse_sms(body: str) -> ParsedSms:
    """Structure a single bank SMS. Never raises."""
    if not body or not isinstance(body, str):
        return _reject("empty message")
    text = body.strip()
    if not text:
        return _reject("empty message")
    if len(text) > MAX_BODY_LEN:
        return _reject("message too long to be a bank alert")

    has_txn_kw = bool(P.TXN_KEYWORD_RE.search(text))
    completed = bool(P.COMPLETED_TXN_RE.search(text))

    # --- reject filters (deterministic, before extraction) ---
    # An OTP message is dropped unless it also reports a COMPLETED debit/credit
    # (some banks bundle a balance alert with an OTP). "OTP for txn of Rs X" has
    # no completed keyword -> rejected.
    if P.OTP_RE.search(text) and not completed:
        return _reject("looks like an OTP / verification message")
    if P.PROMO_RE.search(text) and not has_txn_kw:
        return _reject("looks like a promotional message")

    direction = _direction_from(text)
    amount = _amount_from(text)

    if direction is None and amount is None:
        return _reject("not a transaction message")
    if amount is None:
        return _reject("no amount found in the message")
    if direction is None:
        return ParsedSms(
            status=STATUS_NEEDS_REVIEW,
            reason="couldn't tell if this was money in or out — set it on confirm",
            amount=amount,
            occurred_on=_date_from(text),
            merchant=_merchant_from(text),
            masked_account=_account_from(text),
            bank_ref_id=_ref_from(text),
            template_id=_template_id(text),
        )

    occurred_on = _date_from(text)
    merchant = _merchant_from(text)
    masked_account = _account_from(text)
    ref = _ref_from(text)
    template_id = _template_id(text)

    # --- confidence -> status ---
    reasons = []
    if occurred_on is None:
        reasons.append("date not found")
    identifiable = bool(ref) or bool(merchant and masked_account)
    if not identifiable:
        reasons.append("merchant / reference not clear")

    if reasons:
        return ParsedSms(
            status=STATUS_NEEDS_REVIEW,
            reason="; ".join(reasons) + " — check the details before confirming",
            direction=direction, amount=amount, occurred_on=occurred_on,
            merchant=merchant, masked_account=masked_account,
            bank_ref_id=ref, template_id=template_id,
        )

    return ParsedSms(
        status=STATUS_NEEDS_CONFIRMATION,
        reason="",
        direction=direction, amount=amount, occurred_on=occurred_on,
        merchant=merchant, masked_account=masked_account,
        bank_ref_id=ref, template_id=template_id,
    )
