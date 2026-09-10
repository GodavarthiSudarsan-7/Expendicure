"""Deterministic dedup fingerprint for a parsed bank-SMS event.

Bank SMS get re-delivered. Two events with the same fingerprint are the same
transaction. Prefer the bank's own reference id; fall back to a hash of the
stable extracted fields. Pure ``hashlib`` only.
"""

import hashlib
import re
from decimal import Decimal
from typing import Optional


def _norm_merchant(m: Optional[str]) -> str:
    if not m:
        return ""
    return re.sub(r"[^a-z0-9]+", "", m.lower())


def _norm_amount(a) -> str:
    if a is None:
        return ""
    try:
        return f"{Decimal(str(a)):.2f}"
    except Exception:  # pragma: no cover - defensive
        return str(a)


def fingerprint(connection_id, parsed) -> str:
    """A stable 64-char hex digest identifying this transaction for
    ``connection_id``. ``parsed`` is a :class:`ingestion.sms_parser.ParsedSms`
    (or any object exposing the same attributes)."""
    ref = (getattr(parsed, "bank_ref_id", None) or "").strip()
    if ref:
        basis = f"conn={connection_id}|ref={ref.lower()}"
    else:
        basis = "|".join((
            f"conn={connection_id}",
            f"dir={getattr(parsed, 'direction', None) or ''}",
            f"amt={_norm_amount(getattr(parsed, 'amount', None))}",
            f"date={getattr(parsed, 'occurred_on', None).isoformat() if getattr(parsed, 'occurred_on', None) else ''}",
            f"acct={getattr(parsed, 'masked_account', None) or ''}",
            f"mrc={_norm_merchant(getattr(parsed, 'merchant', None))}",
        ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
