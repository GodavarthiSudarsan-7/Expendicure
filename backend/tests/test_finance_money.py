from decimal import Decimal

import pytest

from finance.money import money, to_decimal, ZERO


def test_zero_is_two_places():
    assert ZERO == Decimal("0.00")


def test_to_decimal_passthrough():
    d = Decimal("12.34")
    assert to_decimal(d) is d


def test_to_decimal_from_int_and_str():
    assert to_decimal(5) == Decimal("5")
    assert to_decimal("5.50") == Decimal("5.50")
    assert to_decimal("  7.1 ") == Decimal("7.1")


def test_to_decimal_rejects_float():
    with pytest.raises(ValueError):
        to_decimal(1.1)


def test_to_decimal_rejects_bool():
    with pytest.raises(ValueError):
        to_decimal(True)


def test_to_decimal_rejects_none_and_garbage():
    with pytest.raises(ValueError):
        to_decimal(None)
    with pytest.raises(ValueError):
        to_decimal("abc")


def test_money_quantizes_half_up():
    assert money("1.005") == Decimal("1.01")
    assert money("1.004") == Decimal("1.00")
    assert money(Decimal("2")) == Decimal("2.00")
    assert money("100") == Decimal("100.00")


def test_money_rejects_non_finite():
    with pytest.raises(ValueError):
        money("NaN")
    with pytest.raises(ValueError):
        money("Infinity")
