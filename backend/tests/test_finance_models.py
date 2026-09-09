import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from finance.models import Transaction, RecurringTransaction, Account


def _txn(direction, amount="10.00"):
    return Transaction(
        id=1,
        student_id=1,
        amount=Decimal(amount),
        direction=direction,
        merchant_name="Test",
        category_id=1,
        category_name="Food",
        payment_date=date(2026, 4, 1),
    )


def test_signed_amount_debit_is_negative():
    assert _txn("debit").signed_amount == Decimal("-10.00")


def test_signed_amount_credit_is_positive():
    assert _txn("credit").signed_amount == Decimal("10.00")


def test_recurring_signed_amount():
    rec = RecurringTransaction(
        id=1, student_id=1, label="Rent", merchant_name="Landlord",
        amount=Decimal("350.00"), direction="debit", cadence="monthly",
        next_date=date(2026, 5, 1), day_of_month=1,
    )
    assert rec.signed_amount == Decimal("-350.00")


def test_models_are_frozen():
    acc = Account(1, Decimal("0.00"), Decimal("0.00"), date(2026, 4, 1))
    with pytest.raises(dataclasses.FrozenInstanceError):
        acc.opening_balance = Decimal("5.00")
