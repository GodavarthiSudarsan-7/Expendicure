"""Immutable value objects for the finance layer.

These are plain dataclasses — no DB, no Flask. The repository is responsible
for turning database rows into these and for keeping every money field a
``Decimal``.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

DEBIT = "debit"
CREDIT = "credit"
DIRECTIONS = (DEBIT, CREDIT)

CADENCE_WEEKLY = "weekly"
CADENCE_MONTHLY = "monthly"
CADENCES = (CADENCE_WEEKLY, CADENCE_MONTHLY)

MATCH_CONTAINS = "contains"
MATCH_EQUALS = "equals"
MATCH_TYPES = (MATCH_CONTAINS, MATCH_EQUALS)

GOAL_ACTIVE = "active"
GOAL_ARCHIVED = "archived"
GOAL_ACHIEVED = "achieved"
GOAL_STATUSES = (GOAL_ACTIVE, GOAL_ARCHIVED, GOAL_ACHIEVED)

# --- Phase 15: bank SMS ingestion (review-only) --------------------------------
SMS_NEEDS_CONFIRMATION = "needs_confirmation"
SMS_NEEDS_REVIEW = "needs_review"
SMS_CONFIRMED = "confirmed"
SMS_IGNORED = "ignored"
SMS_REJECTED = "rejected"
SMS_EVENT_STATUSES = (
    SMS_NEEDS_CONFIRMATION, SMS_NEEDS_REVIEW, SMS_CONFIRMED, SMS_IGNORED, SMS_REJECTED,
)
# statuses a user can still act on
SMS_PENDING_STATUSES = (SMS_NEEDS_CONFIRMATION, SMS_NEEDS_REVIEW)


@dataclass(frozen=True)
class Account:
    student_id: int
    opening_balance: Decimal
    safety_buffer: Decimal
    as_of_date: date


@dataclass(frozen=True)
class Transaction:
    id: int
    student_id: int
    amount: Decimal  # always a positive magnitude
    direction: str  # "debit" (money out) | "credit" (money in)
    merchant_name: str
    category_id: Optional[int]
    category_name: Optional[str]
    payment_date: date
    payment_method: Optional[str] = None
    notes: Optional[str] = None

    @property
    def signed_amount(self) -> Decimal:
        """``+amount`` for credits, ``-amount`` for debits."""
        return self.amount if self.direction == CREDIT else -self.amount


@dataclass(frozen=True)
class RecurringTransaction:
    id: int
    student_id: int
    label: str
    merchant_name: str
    amount: Decimal
    direction: str
    cadence: str  # "weekly" | "monthly"
    next_date: date
    day_of_month: Optional[int] = None
    weekday: Optional[int] = None
    source: str = "user"  # "user" | "detected"
    confidence: Optional[Decimal] = None
    active: bool = True

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == CREDIT else -self.amount


@dataclass(frozen=True)
class CategorizationRule:
    id: int
    student_id: Optional[int]  # None => global default rule
    match_type: str  # "contains" | "equals"
    pattern: str
    category_id: int
    priority: int = 100


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    is_default: bool
    student_id: Optional[int] = None  # None => global default category


@dataclass(frozen=True)
class SavingsGoal:
    """A student's savings target. ``current_amount`` is the saved-so-far pot
    (kept <= ``target_amount``); ``monthly_contribution`` is the planned
    per-month top-up used to project completion. All money is ``Decimal``."""
    id: int
    student_id: int
    name: str
    target_amount: Decimal
    current_amount: Decimal
    monthly_contribution: Decimal
    target_date: date
    status: str = GOAL_ACTIVE  # "active" | "archived" | "achieved"

    @property
    def remaining_amount(self) -> Decimal:
        gap = self.target_amount - self.current_amount
        return gap if gap > 0 else Decimal("0.00")


@dataclass(frozen=True)
class BankConnection:
    """The user's trusted bank SMS source. Only messages whose sender matches an
    ``enabled`` connection are processed. ``ingest_token_hash`` is the sha256 of a
    one-time companion token (never the token itself)."""
    id: int
    student_id: int
    bank_name: str
    sender_id: str
    masked_account: Optional[str] = None
    enabled: bool = True
    ingest_token_hash: Optional[str] = None
    last_event_at: Optional[str] = None
    events_detected: int = 0


@dataclass(frozen=True)
class BankSmsEvent:
    """A transaction detected from a bank SMS, awaiting the user's Confirm / Edit
    / Ignore. Structured fields only — the raw SMS body is never stored. Money
    reaches the twin only via ``transaction_id`` once confirmed."""
    id: int
    student_id: int
    connection_id: int
    status: str
    direction: Optional[str] = None
    amount: Optional[Decimal] = None
    occurred_on: Optional[date] = None
    occurred_at: Optional[str] = None
    merchant: Optional[str] = None
    masked_account: Optional[str] = None
    bank_ref_id: Optional[str] = None
    fingerprint: str = ""
    detect_reason: Optional[str] = None
    template_id: Optional[str] = None
    transaction_id: Optional[int] = None
