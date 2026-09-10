"""Read access to the data the deterministic finance engine needs.

The repository does NOT import Flask or a DB driver. It is constructed with a
``query`` callable so it can be unit-tested with a plain function and wired to
the real database by a thin adapter (``backend/finance_db.py``).

``query`` contract::

    query(sql: str, params: tuple = (), *, one: bool = False)
        one=False -> list[dict]   (may be empty)
        one=True  -> dict | None

Column names in the returned dicts match the SQL. Money columns may already be
``Decimal`` (mysql-connector returns ``Decimal`` for DECIMAL columns); the
repository coerces defensively regardless.
"""

from datetime import date
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from finance.models import (
    Account,
    BankConnection,
    BankSmsEvent,
    CategorizationRule,
    Category,
    RecurringTransaction,
    SavingsGoal,
    Transaction,
    CREDIT,
    DEBIT,
    GOAL_ACTIVE,
)
from finance.money import money, to_decimal, ZERO


def _as_date(value):
    if isinstance(value, date):
        return value
    if value is None:
        return None
    return date.fromisoformat(str(value))


def _as_bool(value):
    return bool(value) and str(value) not in ("0", "False", "false")


class FinanceRepository:
    def __init__(self, query: Callable):
        self._query = query

    # ------------------------------------------------------------------ account
    def get_account(self, student_id: int) -> Optional[Account]:
        row = self._query(
            "SELECT student_id, opening_balance, safety_buffer, as_of_date "
            "FROM accounts WHERE student_id = %s",
            (student_id,),
            one=True,
        )
        if not row:
            return None
        return Account(
            student_id=row["student_id"],
            opening_balance=money(row["opening_balance"]),
            safety_buffer=money(row["safety_buffer"]),
            as_of_date=_as_date(row["as_of_date"]),
        )

    # ------------------------------------------------------------- transactions
    def get_transactions(
        self,
        student_id: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[Transaction]:
        sql = (
            "SELECT t.id, t.student_id, t.amount, t.direction, t.merchant_name, "
            "       t.category_id, c.name AS category_name, t.payment_date, "
            "       t.payment_method, t.notes "
            "FROM transactions t "
            "LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.student_id = %s"
        )
        params = [student_id]
        if start is not None:
            sql += " AND t.payment_date >= %s"
            params.append(start)
        if end is not None:
            sql += " AND t.payment_date <= %s"
            params.append(end)
        sql += " ORDER BY t.payment_date, t.id"

        rows = self._query(sql, tuple(params)) or []
        return [
            Transaction(
                id=row["id"],
                student_id=row["student_id"],
                amount=money(row["amount"]),
                direction=row["direction"] or DEBIT,
                merchant_name=row["merchant_name"],
                category_id=row.get("category_id"),
                category_name=row.get("category_name"),
                payment_date=_as_date(row["payment_date"]),
                payment_method=row.get("payment_method"),
                notes=row.get("notes"),
            )
            for row in rows
        ]

    # --------------------------------------------------------------- recurring
    def get_recurring(
        self, student_id: int, active_only: bool = True
    ) -> List[RecurringTransaction]:
        sql = (
            "SELECT id, student_id, label, merchant_name, amount, direction, "
            "       cadence, day_of_month, weekday, next_date, source, "
            "       confidence, active "
            "FROM recurring_transactions WHERE student_id = %s"
        )
        params = [student_id]
        if active_only:
            sql += " AND active = TRUE"
        sql += " ORDER BY next_date, id"

        rows = self._query(sql, tuple(params)) or []
        result = []
        for row in rows:
            confidence = row.get("confidence")
            result.append(
                RecurringTransaction(
                    id=row["id"],
                    student_id=row["student_id"],
                    label=row["label"],
                    merchant_name=row["merchant_name"],
                    amount=money(row["amount"]),
                    direction=row["direction"] or DEBIT,
                    cadence=row["cadence"],
                    next_date=_as_date(row["next_date"]),
                    day_of_month=row.get("day_of_month"),
                    weekday=row.get("weekday"),
                    source=row.get("source") or "user",
                    confidence=to_decimal(confidence) if confidence is not None else None,
                    active=_as_bool(row.get("active", True)),
                )
            )
        return result

    # ----------------------------------------------------------------- budgets
    def get_budgets(self, student_id: int, month: str) -> Dict[str, Decimal]:
        """``{category_name: monthly_limit}`` for the given ``"YYYY-MM"`` month."""
        rows = self._query(
            "SELECT c.name AS category_name, b.monthly_limit "
            "FROM budgets b JOIN categories c ON b.category_id = c.id "
            "WHERE b.student_id = %s AND b.month = %s "
            "ORDER BY c.name",
            (student_id, month),
        ) or []
        return {row["category_name"]: money(row["monthly_limit"]) for row in rows}

    # ---------------------------------------------------- categorization rules
    def get_categorization_rules(self, student_id: int) -> List[CategorizationRule]:
        """Global rules (student_id IS NULL) plus this student's own rules,
        highest priority first (lower number = higher priority)."""
        rows = self._query(
            "SELECT id, student_id, match_type, pattern, category_id, priority "
            "FROM categorization_rules "
            "WHERE student_id = %s OR student_id IS NULL "
            "ORDER BY priority, id",
            (student_id,),
        ) or []
        return [
            CategorizationRule(
                id=row["id"],
                student_id=row.get("student_id"),
                match_type=row["match_type"],
                pattern=row["pattern"],
                category_id=row["category_id"],
                priority=row["priority"],
            )
            for row in rows
        ]

    # -------------------------------------------------------------- categories
    def get_categories(self, student_id: int) -> List[Category]:
        rows = self._query(
            "SELECT id, name, is_default, student_id FROM categories "
            "WHERE student_id = %s OR student_id IS NULL "
            "ORDER BY name",
            (student_id,),
        ) or []
        return [
            Category(
                id=row["id"],
                name=row["name"],
                is_default=_as_bool(row.get("is_default")),
                student_id=row.get("student_id"),
            )
            for row in rows
        ]

    # ----------------------------------------------------------- savings goals
    def get_savings_goals(
        self, student_id: int, *, status: Optional[str] = GOAL_ACTIVE
    ) -> List[SavingsGoal]:
        """The student's savings goals. ``status=None`` returns every status;
        otherwise only rows with that status. Ownership is always scoped by
        ``student_id`` — a goal is never returned for another student."""
        sql = (
            "SELECT id, student_id, name, target_amount, current_amount, "
            "       monthly_contribution, target_date, status "
            "FROM savings_goals WHERE student_id = %s"
        )
        params = [student_id]
        if status is not None:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY target_date, id"

        rows = self._query(sql, tuple(params)) or []
        return [self._goal_from_row(row) for row in rows]

    def get_savings_goal(self, student_id: int, goal_id: int) -> Optional[SavingsGoal]:
        """One goal by id, but only if it belongs to ``student_id``."""
        row = self._query(
            "SELECT id, student_id, name, target_amount, current_amount, "
            "       monthly_contribution, target_date, status "
            "FROM savings_goals WHERE id = %s AND student_id = %s",
            (goal_id, student_id),
            one=True,
        )
        return self._goal_from_row(row) if row else None

    @staticmethod
    def _goal_from_row(row) -> SavingsGoal:
        return SavingsGoal(
            id=row["id"],
            student_id=row["student_id"],
            name=row["name"],
            target_amount=money(row["target_amount"]),
            current_amount=money(row["current_amount"]),
            monthly_contribution=money(row["monthly_contribution"]),
            target_date=_as_date(row["target_date"]),
            status=row.get("status") or GOAL_ACTIVE,
        )

    # ------------------------------------------------------ bank connections (Phase 15)
    def get_bank_connections(self, student_id: int, *, enabled_only: bool = False):
        """The student's configured bank SMS sources. Read-only; ownership is
        always scoped by ``student_id``."""
        sql = (
            "SELECT id, student_id, bank_name, sender_id, masked_account, enabled, "
            "       ingest_token_hash, last_event_at, events_detected "
            "FROM bank_connections WHERE student_id = %s"
        )
        params = [student_id]
        if enabled_only:
            sql += " AND enabled = TRUE"
        sql += " ORDER BY id"
        rows = self._query(sql, tuple(params)) or []
        return [
            BankConnection(
                id=r["id"], student_id=r["student_id"], bank_name=r["bank_name"],
                sender_id=r["sender_id"], masked_account=r.get("masked_account"),
                enabled=_as_bool(r.get("enabled", True)),
                ingest_token_hash=r.get("ingest_token_hash"),
                last_event_at=(r["last_event_at"].isoformat()
                               if r.get("last_event_at") is not None
                               and hasattr(r["last_event_at"], "isoformat")
                               else r.get("last_event_at")),
                events_detected=int(r.get("events_detected") or 0),
            )
            for r in rows
        ]

    def get_bank_sms_events(self, student_id: int, *, status=None):
        """The student's detected bank-SMS transaction events (structured fields
        only — the raw SMS body is never stored)."""
        sql = (
            "SELECT id, student_id, connection_id, status, direction, amount, "
            "       occurred_on, occurred_at, merchant, masked_account, bank_ref_id, "
            "       fingerprint, detect_reason, template_id, transaction_id "
            "FROM bank_sms_events WHERE student_id = %s"
        )
        params = [student_id]
        if status is not None:
            if isinstance(status, (list, tuple, set)):
                placeholders = ", ".join(["%s"] * len(status))
                sql += f" AND status IN ({placeholders})"
                params.extend(status)
            else:
                sql += " AND status = %s"
                params.append(status)
        sql += " ORDER BY id DESC"
        rows = self._query(sql, tuple(params)) or []
        return [
            BankSmsEvent(
                id=r["id"], student_id=r["student_id"], connection_id=r["connection_id"],
                status=r["status"], direction=r.get("direction"),
                amount=money(r["amount"]) if r.get("amount") is not None else None,
                occurred_on=_as_date(r["occurred_on"]) if r.get("occurred_on") else None,
                occurred_at=(r["occurred_at"].isoformat()
                             if r.get("occurred_at") is not None
                             and hasattr(r["occurred_at"], "isoformat")
                             else r.get("occurred_at")),
                merchant=r.get("merchant"), masked_account=r.get("masked_account"),
                bank_ref_id=r.get("bank_ref_id"), fingerprint=r.get("fingerprint") or "",
                detect_reason=r.get("detect_reason"), template_id=r.get("template_id"),
                transaction_id=r.get("transaction_id"),
            )
            for r in rows
        ]

    # ----------------------------------------------------------------- balance
    def compute_current_balance(
        self, student_id: int, as_of: Optional[date] = None
    ) -> Decimal:
        """opening_balance + credits - debits, for transactions dated on or
        before ``as_of`` (default: today).

        If the student has no account row, opening balance is treated as 0.
        """
        as_of = as_of or date.today()

        account = self.get_account(student_id)
        opening = account.opening_balance if account else ZERO

        rows = self._query(
            "SELECT direction, COALESCE(SUM(amount), 0) AS total "
            "FROM transactions "
            "WHERE student_id = %s AND payment_date <= %s "
            "GROUP BY direction",
            (student_id, as_of),
        ) or []

        credits = ZERO
        debits = ZERO
        for row in rows:
            total = money(row["total"])
            if (row["direction"] or DEBIT) == CREDIT:
                credits += total
            else:
                debits += total

        return money(opening + credits - debits)
