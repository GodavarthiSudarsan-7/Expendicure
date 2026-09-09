"""The Financial Digital Twin.

A deterministic, queryable snapshot of one student's financial state, assembled
entirely from Phase 2 database data via :class:`finance.repository.FinanceRepository`.

Rules:
- Every number here is plain arithmetic on database-sourced values.
- No Flask, no DB driver, no LLM. The repository is injected.
- All money is ``Decimal``, quantized to 2 places at the boundary.

This object is the source of truth that later AI/agent tools will query; the
LLM must never compute these numbers itself.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, Optional, Tuple

from finance.models import CREDIT, DEBIT, RecurringTransaction
from finance.money import ZERO, money
from finance.repository import FinanceRepository

# --- configuration (single source of truth; override per call if needed) -----

# Spending in these categories is treated as essential, i.e. NOT discretionary.
# Comparison is case-insensitive and whitespace-trimmed.
DEFAULT_NON_DISCRETIONARY_CATEGORIES = frozenset({"Rent", "Rations", "Health"})

# Look-ahead window for "committed upcoming expenses".
DEFAULT_COMMITTED_HORIZON_DAYS = 30

# Fallback safety buffer used only when the student has no account row AND the
# caller does not pass one.
DEFAULT_SAFETY_BUFFER = ZERO

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class TwinState:
    student_id: int
    as_of: date
    month: str  # "YYYY-MM" derived from as_of

    opening_balance: Decimal
    current_balance: Decimal

    month_income: Decimal
    month_spending: Decimal
    month_net: Decimal
    month_discretionary_spending: Decimal

    spending_by_category: Dict[str, Decimal]  # only categories with debit spend > 0
    budgets: Dict[str, Decimal]               # category_name -> monthly_limit for `month`
    recurring: Tuple[RecurringTransaction, ...]

    safety_buffer: Decimal
    committed_upcoming: Decimal
    committed_upcoming_horizon_days: int
    discretionary_buffer: Decimal


def _norm(name: Optional[str]) -> str:
    return (name or "").strip().casefold()


def build_twin_state(
    repo: FinanceRepository,
    student_id: int,
    *,
    as_of: Optional[date] = None,
    default_safety_buffer: Decimal = DEFAULT_SAFETY_BUFFER,
    non_discretionary_categories: Iterable[str] = DEFAULT_NON_DISCRETIONARY_CATEGORIES,
    committed_upcoming_horizon_days: int = DEFAULT_COMMITTED_HORIZON_DAYS,
) -> TwinState:
    """Assemble the digital twin for ``student_id`` as of ``as_of`` (default: today)."""
    as_of = as_of or date.today()
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    month_first = date(as_of.year, as_of.month, 1)

    # --- balances -----------------------------------------------------------
    account = repo.get_account(student_id)
    opening_balance = account.opening_balance if account else ZERO
    safety_buffer = account.safety_buffer if account else money(default_safety_buffer)
    current_balance = repo.compute_current_balance(student_id, as_of=as_of)

    # --- month-to-date activity -------------------------------------------------
    # First day of as_of's month through as_of, inclusive. The twin is a snapshot
    # of KNOWN financial reality as of `as_of`; transactions dated after `as_of`
    # (even within the same month) belong to forecasting, not the twin.
    month_txns = repo.get_transactions(student_id, start=month_first, end=as_of)
    non_disc = frozenset(_norm(c) for c in non_discretionary_categories)

    month_income = ZERO
    month_spending = ZERO
    month_discretionary_spending = ZERO
    spending_by_category: Dict[str, Decimal] = {}

    for txn in month_txns:
        if txn.direction == CREDIT:
            month_income += txn.amount
            continue
        # debit
        month_spending += txn.amount
        category = txn.category_name or UNCATEGORIZED
        spending_by_category[category] = spending_by_category.get(category, ZERO) + txn.amount
        if _norm(category) not in non_disc:
            month_discretionary_spending += txn.amount

    month_income = money(month_income)
    month_spending = money(month_spending)
    month_discretionary_spending = money(month_discretionary_spending)
    month_net = money(month_income - month_spending)
    spending_by_category = {k: money(v) for k, v in spending_by_category.items()}

    # --- budgets & recurring ---------------------------------------------------
    budgets = repo.get_budgets(student_id, month)
    recurring = tuple(repo.get_recurring(student_id, active_only=True))

    # --- committed upcoming expenses ----------------------------------------
    # Outflow of each active recurring debit whose next occurrence falls in
    # [as_of, as_of + horizon). One occurrence per item — multi-occurrence
    # expansion is forecasting (a later phase), not the twin snapshot.
    horizon_end = as_of + timedelta(days=committed_upcoming_horizon_days)
    committed_upcoming = ZERO
    for rec in recurring:
        if rec.direction != DEBIT:
            continue
        if as_of <= rec.next_date < horizon_end:
            committed_upcoming += rec.amount
    committed_upcoming = money(committed_upcoming)

    # --- discretionary buffer ---------------------------------------------------
    # What the student can freely spend after covering known upcoming
    # commitments and preserving the safety buffer. May be negative.
    discretionary_buffer = money(current_balance - committed_upcoming - safety_buffer)

    return TwinState(
        student_id=student_id,
        as_of=as_of,
        month=month,
        opening_balance=money(opening_balance),
        current_balance=money(current_balance),
        month_income=month_income,
        month_spending=month_spending,
        month_net=month_net,
        month_discretionary_spending=month_discretionary_spending,
        spending_by_category=spending_by_category,
        budgets=budgets,
        recurring=recurring,
        safety_buffer=money(safety_buffer),
        committed_upcoming=committed_upcoming,
        committed_upcoming_horizon_days=committed_upcoming_horizon_days,
        discretionary_buffer=discretionary_buffer,
    )
