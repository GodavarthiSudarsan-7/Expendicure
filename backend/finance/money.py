"""Decimal helpers. The finance layer never uses ``float`` for money.

Kept intentionally small for Phase 2 (convert, quantize, zero). It will grow as
later phases need it.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value):
    """Coerce ``value`` to ``Decimal`` without going through ``float``.

    Accepts ``Decimal``, ``int``, and numeric strings. Rejects ``None``,
    ``float`` (lossy), and anything unparseable, raising ``ValueError``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; never money
        raise ValueError("bool is not a monetary value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise ValueError("refusing to build money from float; pass a str or Decimal")
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal: {value!r}") from exc
    raise ValueError(f"cannot convert {type(value).__name__} to Decimal")


def money(value):
    """Return ``value`` as a ``Decimal`` quantized to 2 places, half-up."""
    result = to_decimal(value)
    if result.is_nan() or result.is_infinite():
        raise ValueError(f"not a finite monetary value: {value!r}")
    return result.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
