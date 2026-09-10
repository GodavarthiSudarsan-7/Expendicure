"""Phase 15 — bank SMS → structured transaction (review-only).

Deterministic extraction of a single bank transaction notification into
structured fields. There is NO auto-confirm: the route layer always creates a
``needs_confirmation`` / ``needs_review`` event and the user must Confirm / Edit
/ Ignore before any money reaches the Financial Twin.

Layer position:  finance  <-  ingestion  <-  routes

``ingestion/`` imports only the standard library + ``finance.money``. It must not
import flask / requests / ollama / ai / agent / tools / decision / knowledge /
database / finance_db. It never touches the database, the network, or an LLM,
and it never stores the raw SMS body.
"""

from ingestion.sms_parser import (
    ParsedSms,
    parse_sms,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_NEEDS_REVIEW,
    STATUS_REJECTED,
    DEBIT,
    CREDIT,
)
from ingestion.fingerprint import fingerprint

__all__ = [
    "ParsedSms", "parse_sms", "fingerprint",
    "STATUS_NEEDS_CONFIRMATION", "STATUS_NEEDS_REVIEW", "STATUS_REJECTED",
    "DEBIT", "CREDIT",
]
