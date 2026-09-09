"""Unit tests for the Financial Digital Twin. Pure — a FakeRepo supplies data;
no DB, no Flask, no network."""

from datetime import date
from decimal import Decimal

import pytest

from finance.models import Transaction, RecurringTransaction, Account
from finance.money import money, ZERO
from finance.twin import build_twin_state, DEFAULT_COMMITTED_HORIZON_DAYS


# --------------------------------------------------------------------------- helpers

def txn(amount, direction, category, day, *, month=4, year=2026, tid=None):
    return Transaction(
        id=tid if tid is not None else int(f"{month}{day:02d}"),
        student_id=1,
        amount=Decimal(str(amount)),
        direction=direction,
        merchant_name="M",
        category_id=1,
        category_name=category,
        payment_date=date(year, month, day),
    )


def rec(amount, direction, next_date, *, active=True, rid=1, cadence="monthly"):
    return RecurringTransaction(
        id=rid, student_id=1, label="L", merchant_name="M",
        amount=Decimal(str(amount)), direction=direction, cadence=cadence,
        next_date=next_date, day_of_month=next_date.day, active=active,
    )


class FakeRepo:
    def __init__(self, *, account=None, transactions=None, recurring=None,
                 budgets=None, balance=None):
        self._account = account
        self._transactions = list(transactions or [])
        self._recurring = list(recurring or [])
        self._budgets = dict(budgets or {})
        self._balance = balance

    def get_account(self, student_id):
        return self._account

    def compute_current_balance(self, student_id, as_of=None):
        if self._balance is not None:
            return money(self._balance)
        opening = self._account.opening_balance if self._account else ZERO
        total = opening
        for t in self._transactions:
            if as_of is None or t.payment_date <= as_of:
                total += t.signed_amount
        return money(total)

    def get_transactions(self, student_id, start=None, end=None):
        out = []
        for t in self._transactions:
            if start is not None and t.payment_date < start:
                continue
            if end is not None and t.payment_date > end:
                continue
            out.append(t)
        return out

    def get_recurring(self, student_id, active_only=True):
        return [r for r in self._recurring if r.active or not active_only]

    def get_budgets(self, student_id, month):
        return dict(self._budgets)


AS_OF = date(2026, 4, 15)


def build(**kw):
    repo_kwargs = {k: kw.pop(k) for k in list(kw)
                   if k in ("account", "transactions", "recurring", "budgets", "balance")}
    return build_twin_state(FakeRepo(**repo_kwargs), 1, as_of=kw.pop("as_of", AS_OF), **kw)


# --------------------------------------------------------------------------- tests

def test_empty_state():
    s = build(default_safety_buffer=Decimal("2000"))
    assert s.opening_balance == Decimal("0.00")
    assert s.current_balance == Decimal("0.00")
    assert s.month_income == Decimal("0.00")
    assert s.month_spending == Decimal("0.00")
    assert s.month_net == Decimal("0.00")
    assert s.month_discretionary_spending == Decimal("0.00")
    assert s.spending_by_category == {}
    assert s.budgets == {}
    assert s.recurring == ()
    assert s.safety_buffer == Decimal("2000.00")
    assert s.committed_upcoming == Decimal("0.00")
    assert s.discretionary_buffer == Decimal("-2000.00")
    assert s.month == "2026-04"
    assert s.as_of == AS_OF


def test_opening_balance_no_transactions():
    acc = Account(1, Decimal("1500.00"), Decimal("0.00"), date(2026, 4, 1))
    s = build(account=acc)
    assert s.opening_balance == Decimal("1500.00")
    assert s.current_balance == Decimal("1500.00")


def test_income_increases_balance_and_month_income():
    s = build(transactions=[txn("5000", "credit", "Other", 1)])
    assert s.month_income == Decimal("5000.00")
    assert s.month_spending == Decimal("0.00")
    assert s.current_balance == Decimal("5000.00")


def test_expenses_tracked():
    s = build(transactions=[txn("120.50", "debit", "Food", 2),
                            txn("30", "debit", "Travel", 3)])
    assert s.month_spending == Decimal("150.50")
    assert s.current_balance == Decimal("-150.50")


def test_current_balance_opening_plus_credits_minus_debits():
    acc = Account(1, Decimal("1000.00"), Decimal("0.00"), date(2026, 4, 1))
    s = build(account=acc, transactions=[
        txn("5000", "credit", "Other", 1),
        txn("1200", "debit", "Rent", 1),
    ])
    assert s.current_balance == Decimal("4800.00")


def test_current_balance_respects_as_of():
    s = build(as_of=date(2026, 4, 10), transactions=[
        txn("100", "debit", "Food", 5),
        txn("999", "debit", "Food", 20),  # after as_of
    ])
    assert s.current_balance == Decimal("-100.00")
    assert s.month_spending == Decimal("100.00")  # day-20 txn excluded here too


def test_month_net():
    s = build(transactions=[
        txn("5000", "credit", "Other", 1),
        txn("1500", "debit", "Rent", 1),
    ])
    assert s.month_net == Decimal("3500.00")


def test_spending_by_category_groups_and_omits_zero_and_income():
    s = build(transactions=[
        txn("10", "debit", "Food", 1),
        txn("15", "debit", "Food", 2),
        txn("40", "debit", "Travel", 3),
        txn("500", "credit", "Other", 4),  # income, not in spending_by_category
    ])
    assert s.spending_by_category == {"Food": Decimal("25.00"), "Travel": Decimal("40.00")}


def test_spending_by_category_uncategorized_fallback():
    t = Transaction(id=1, student_id=1, amount=Decimal("12"), direction="debit",
                    merchant_name="M", category_id=None, category_name=None,
                    payment_date=date(2026, 4, 3))
    s = build(transactions=[t])
    assert s.spending_by_category == {"Uncategorized": Decimal("12.00")}


def test_budgets_for_the_month():
    s = build(budgets={"Food": Decimal("200.00"), "Rent": Decimal("400.00")})
    assert s.budgets == {"Food": Decimal("200.00"), "Rent": Decimal("400.00")}


def test_recurring_included_active_only():
    s = build(recurring=[
        rec("350", "debit", date(2026, 5, 1), rid=1, active=True),
        rec("99", "debit", date(2026, 5, 2), rid=2, active=False),
    ])
    assert [r.id for r in s.recurring] == [1]


def test_safety_buffer_from_account():
    acc = Account(1, Decimal("0.00"), Decimal("750.00"), date(2026, 4, 1))
    s = build(account=acc, default_safety_buffer=Decimal("2000"))
    assert s.safety_buffer == Decimal("750.00")


def test_safety_buffer_default_when_no_account():
    s = build(default_safety_buffer=Decimal("1234.50"))
    assert s.safety_buffer == Decimal("1234.50")


def test_committed_upcoming_sums_debit_recurring_in_horizon():
    s = build(as_of=date(2026, 4, 15), recurring=[
        rec("350", "debit", date(2026, 4, 20), rid=1),
        rec("50", "debit", date(2026, 5, 1), rid=2),
    ])
    # both within 30 days of 2026-04-15
    assert s.committed_upcoming == Decimal("400.00")
    assert s.committed_upcoming_horizon_days == DEFAULT_COMMITTED_HORIZON_DAYS


def test_committed_upcoming_excludes_credit_recurring():
    s = build(as_of=date(2026, 4, 15), recurring=[
        rec("5000", "credit", date(2026, 4, 20), rid=1),
        rec("350", "debit", date(2026, 4, 21), rid=2),
    ])
    assert s.committed_upcoming == Decimal("350.00")


def test_committed_upcoming_excludes_beyond_horizon():
    s = build(as_of=date(2026, 4, 15), committed_upcoming_horizon_days=10, recurring=[
        rec("350", "debit", date(2026, 4, 20), rid=1),  # in
        rec("99", "debit", date(2026, 4, 30), rid=2),   # 15 days out -> excluded
    ])
    assert s.committed_upcoming == Decimal("350.00")


def test_committed_upcoming_includes_due_today():
    s = build(as_of=date(2026, 4, 15), recurring=[rec("42", "debit", date(2026, 4, 15))])
    assert s.committed_upcoming == Decimal("42.00")


def test_committed_upcoming_excludes_past_due():
    s = build(as_of=date(2026, 4, 15), recurring=[rec("42", "debit", date(2026, 4, 14))])
    assert s.committed_upcoming == Decimal("0.00")


def test_discretionary_buffer_formula():
    acc = Account(1, Decimal("0.00"), Decimal("500.00"), date(2026, 4, 1))
    s = build(as_of=date(2026, 4, 15), account=acc, balance=Decimal("3000.00"),
              recurring=[rec("800", "debit", date(2026, 4, 20))])
    # 3000 - 800 - 500
    assert s.discretionary_buffer == Decimal("1700.00")


def test_discretionary_spending_excludes_essentials():
    s = build(transactions=[
        txn("100", "debit", "Food", 1),      # discretionary
        txn("400", "debit", "Rent", 1),      # essential
        txn("60", "debit", "Rations", 2),    # essential
        txn("75", "debit", "Health", 3),     # essential
        txn("25", "debit", "Entertainment", 4),  # discretionary
    ])
    assert s.month_spending == Decimal("660.00")
    assert s.month_discretionary_spending == Decimal("125.00")


def test_discretionary_spending_is_case_insensitive():
    s = build(transactions=[
        txn("400", "debit", "rent", 1),
        txn("50", "debit", "  HEALTH ", 2),
        txn("30", "debit", "Food", 3),
    ])
    assert s.month_discretionary_spending == Decimal("30.00")


def test_discretionary_categories_are_configurable():
    s = build(
        transactions=[txn("100", "debit", "Food", 1), txn("50", "debit", "Gym", 2)],
        non_discretionary_categories={"Food"},
    )
    # only "Gym" counts as discretionary now
    assert s.month_discretionary_spending == Decimal("50.00")


def test_month_window_is_first_of_month_through_as_of():
    s = build(as_of=date(2026, 4, 15), transactions=[
        txn("10", "debit", "Food", 1),          # first day of month -> in
        txn("15", "debit", "Food", 15),         # exactly as_of -> in
        txn("20", "debit", "Food", 16),         # day after as_of, same month -> OUT
        txn("30", "debit", "Food", 30),         # later in month -> OUT
        Transaction(id=99, student_id=1, amount=Decimal("999"), direction="debit",
                    merchant_name="M", category_id=1, category_name="Food",
                    payment_date=date(2026, 3, 31)),  # prev month -> out
    ])
    assert s.month_spending == Decimal("25.00")  # 10 + 15


def test_transaction_dated_exactly_as_of_is_included():
    s = build(as_of=date(2026, 4, 15), transactions=[
        txn("42", "debit", "Food", 15),
        txn("7", "credit", "Other", 15),
    ])
    assert s.month_spending == Decimal("42.00")
    assert s.month_income == Decimal("7.00")


def test_no_transaction_after_as_of_contributes_to_month_totals_or_balance():
    s = build(as_of=date(2026, 4, 10), transactions=[
        txn("100", "debit", "Food", 5),
        txn("50", "credit", "Other", 8),
        txn("200", "debit", "Food", 11),   # 1 day after as_of, same month
        txn("300", "credit", "Other", 25),  # later in month
        txn("400", "debit", "Rent", 5, month=5),  # next month
    ])
    assert s.month_spending == Decimal("100.00")
    assert s.month_income == Decimal("50.00")
    assert s.month_net == Decimal("-50.00")
    assert s.current_balance == Decimal("-50.00")   # 100 debit - 50 credit, <= as_of


def test_as_of_in_past_month_excludes_later_txns():
    s = build(as_of=date(2026, 3, 20), transactions=[
        txn("100", "debit", "Food", 10, month=3),
        txn("500", "debit", "Food", 5, month=4),  # April -> outside March + after as_of
    ])
    assert s.month == "2026-03"
    assert s.month_spending == Decimal("100.00")
    assert s.current_balance == Decimal("-100.00")


def test_december_month_to_date():
    s = build(as_of=date(2026, 12, 15), transactions=[
        Transaction(id=1, student_id=1, amount=Decimal("50"), direction="debit",
                    merchant_name="M", category_id=1, category_name="Food",
                    payment_date=date(2026, 12, 10)),   # <= as_of -> in
        Transaction(id=2, student_id=1, amount=Decimal("60"), direction="debit",
                    merchant_name="M", category_id=1, category_name="Food",
                    payment_date=date(2026, 12, 20)),   # after as_of -> out
        Transaction(id=3, student_id=1, amount=Decimal("70"), direction="debit",
                    merchant_name="M", category_id=1, category_name="Food",
                    payment_date=date(2027, 1, 1)),     # next month -> out
    ])
    assert s.month == "2026-12"
    assert s.month_spending == Decimal("50.00")


def test_decimal_precision_no_float_drift():
    s = build(transactions=[
        txn("0.10", "debit", "Food", 1),
        txn("0.20", "debit", "Food", 2),
        txn("10.005", "debit", "Food", 3),  # rounds half-up to 10.01 at boundary
    ])
    # 0.10 + 0.20 + 10.005 -> 10.305 -> money() -> 10.31 ; category sum quantized
    assert s.month_spending == Decimal("10.31")
    assert isinstance(s.month_spending, Decimal)
    assert s.spending_by_category["Food"].as_tuple().exponent == -2


def test_all_money_fields_are_decimal_quantized():
    acc = Account(1, Decimal("1000"), Decimal("200"), date(2026, 4, 1))
    s = build(account=acc, transactions=[txn("33.333", "debit", "Food", 1)],
              recurring=[rec("12.5", "debit", date(2026, 4, 20))],
              budgets={"Food": Decimal("100")})
    for value in [s.opening_balance, s.current_balance, s.month_income, s.month_spending,
                  s.month_net, s.month_discretionary_spending, s.safety_buffer,
                  s.committed_upcoming, s.discretionary_buffer,
                  *s.spending_by_category.values(), *s.budgets.values()]:
        assert isinstance(value, Decimal)
        assert value == value.quantize(Decimal("0.01"))
