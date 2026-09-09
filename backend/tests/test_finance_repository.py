"""FinanceRepository with an in-memory fake ``query`` — no DB."""

from datetime import date
from decimal import Decimal

import pytest

from finance.repository import FinanceRepository
from finance.models import CREDIT, DEBIT


class FakeQuery:
    """Answers the specific SELECTs the repository issues, from fixture data."""

    def __init__(self, account=None, transactions=None, recurring=None,
                 rules=None, categories=None, budgets=None):
        self.account = account
        self.transactions = transactions or []
        self.recurring = recurring or []
        self.rules = rules or []
        self.categories = categories or []
        self.budgets = budgets or []

    def __call__(self, sql, params=(), one=False):
        s = " ".join(sql.split()).lower()
        if s.startswith("select student_id, opening_balance"):
            return dict(self.account) if self.account else None
        if s.startswith("select c.name as category_name, b.monthly_limit"):
            return list(self.budgets)
        if s.startswith("select t.id, t.student_id, t.amount"):
            rows = self.transactions
            # emulate the date filters
            if "t.payment_date >= %s" in s:
                start = params[1]
                rows = [r for r in rows if r["payment_date"] >= start]
            if "t.payment_date <= %s" in s:
                end = params[-1]
                rows = [r for r in rows if r["payment_date"] <= end]
            return rows
        if s.startswith("select id, student_id, label"):
            rows = self.recurring
            if "active = true" in s:
                rows = [r for r in rows if r.get("active", True)]
            return rows
        if s.startswith("select id, student_id, match_type"):
            return self.rules
        if s.startswith("select id, name, is_default, student_id from categories"):
            return self.categories
        if s.startswith("select direction, coalesce(sum(amount), 0) as total"):
            as_of = params[1]
            agg = {}
            for r in self.transactions:
                if r["payment_date"] <= as_of:
                    agg.setdefault(r["direction"], Decimal("0"))
                    agg[r["direction"]] += Decimal(str(r["amount"]))
            return [{"direction": k, "total": v} for k, v in agg.items()]
        raise AssertionError(f"unexpected query: {s}")


def test_get_account_none_when_absent():
    repo = FinanceRepository(FakeQuery(account=None))
    assert repo.get_account(1) is None


def test_get_account_returns_decimals():
    repo = FinanceRepository(FakeQuery(account={
        "student_id": 1, "opening_balance": "1000", "safety_buffer": "200",
        "as_of_date": date(2026, 4, 1),
    }))
    acc = repo.get_account(1)
    assert acc.opening_balance == Decimal("1000.00")
    assert acc.safety_buffer == Decimal("200.00")
    assert acc.as_of_date == date(2026, 4, 1)


def test_get_transactions_maps_rows():
    repo = FinanceRepository(FakeQuery(transactions=[
        {"id": 1, "student_id": 1, "amount": "15.50", "direction": DEBIT,
         "merchant_name": "Cafe", "category_id": 1, "category_name": "Food",
         "payment_date": date(2026, 4, 1), "payment_method": "Cash", "notes": None},
    ]))
    txns = repo.get_transactions(1)
    assert len(txns) == 1
    assert txns[0].amount == Decimal("15.50")
    assert txns[0].signed_amount == Decimal("-15.50")


def test_get_transactions_date_filter():
    rows = [
        {"id": 1, "student_id": 1, "amount": "10", "direction": DEBIT,
         "merchant_name": "A", "category_id": 1, "category_name": "Food",
         "payment_date": date(2026, 3, 1), "payment_method": None, "notes": None},
        {"id": 2, "student_id": 1, "amount": "20", "direction": DEBIT,
         "merchant_name": "B", "category_id": 1, "category_name": "Food",
         "payment_date": date(2026, 4, 15), "payment_method": None, "notes": None},
    ]
    repo = FinanceRepository(FakeQuery(transactions=rows))
    got = repo.get_transactions(1, start=date(2026, 4, 1), end=date(2026, 4, 30))
    assert [t.id for t in got] == [2]


def test_compute_current_balance_credits_minus_debits():
    rows = [
        {"id": 1, "student_id": 1, "amount": "5000", "direction": CREDIT,
         "merchant_name": "Allowance", "category_id": 1, "category_name": "Other",
         "payment_date": date(2026, 4, 1), "payment_method": None, "notes": None},
        {"id": 2, "student_id": 1, "amount": "350", "direction": DEBIT,
         "merchant_name": "Rent", "category_id": 2, "category_name": "Rent",
         "payment_date": date(2026, 4, 2), "payment_method": None, "notes": None},
        {"id": 3, "student_id": 1, "amount": "50", "direction": DEBIT,
         "merchant_name": "Food", "category_id": 1, "category_name": "Food",
         "payment_date": date(2026, 5, 1), "payment_method": None, "notes": None},
    ]
    repo = FinanceRepository(FakeQuery(
        account={"student_id": 1, "opening_balance": "1000", "safety_buffer": "0",
                 "as_of_date": date(2026, 3, 31)},
        transactions=rows,
    ))
    # as_of before the May debit: 1000 + 5000 - 350 = 5650
    assert repo.compute_current_balance(1, as_of=date(2026, 4, 30)) == Decimal("5650.00")
    # as_of after the May debit: - 50 more = 5600
    assert repo.compute_current_balance(1, as_of=date(2026, 5, 31)) == Decimal("5600.00")


def test_compute_current_balance_no_account_is_zero_opening():
    rows = [
        {"id": 1, "student_id": 1, "amount": "100", "direction": CREDIT,
         "merchant_name": "x", "category_id": 1, "category_name": "Other",
         "payment_date": date(2026, 4, 1), "payment_method": None, "notes": None},
    ]
    repo = FinanceRepository(FakeQuery(account=None, transactions=rows))
    assert repo.compute_current_balance(1, as_of=date(2026, 4, 30)) == Decimal("100.00")


def test_get_recurring_active_only():
    repo = FinanceRepository(FakeQuery(recurring=[
        {"id": 1, "student_id": 1, "label": "Rent", "merchant_name": "LL",
         "amount": "350", "direction": DEBIT, "cadence": "monthly",
         "day_of_month": 1, "weekday": None, "next_date": date(2026, 5, 1),
         "source": "user", "confidence": None, "active": True},
    ]))
    recs = repo.get_recurring(1)
    assert len(recs) == 1
    assert recs[0].amount == Decimal("350.00")
    assert recs[0].signed_amount == Decimal("-350.00")


def test_get_categorization_rules_maps():
    repo = FinanceRepository(FakeQuery(rules=[
        {"id": 1, "student_id": None, "match_type": "contains",
         "pattern": "netflix", "category_id": 6, "priority": 50},
    ]))
    rules = repo.get_categorization_rules(1)
    assert rules[0].student_id is None
    assert rules[0].pattern == "netflix"


def test_get_budgets_returns_decimal_map():
    repo = FinanceRepository(FakeQuery(budgets=[
        {"category_name": "Food", "monthly_limit": "200"},
        {"category_name": "Rent", "monthly_limit": Decimal("400.00")},
    ]))
    budgets = repo.get_budgets(1, "2026-04")
    assert budgets == {"Food": Decimal("200.00"), "Rent": Decimal("400.00")}
    assert all(isinstance(v, Decimal) for v in budgets.values())


def test_get_budgets_empty():
    repo = FinanceRepository(FakeQuery(budgets=[]))
    assert repo.get_budgets(1, "2026-04") == {}
