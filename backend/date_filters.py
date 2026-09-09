"""Small, dependency-free date helpers.

These exist so month/period filtering can be expressed as ordinary indexed
range comparisons (``payment_date >= %s AND payment_date < %s``) instead of
``DATE_FORMAT(payment_date, '%Y-%m')``. The latter breaks under
mysql-connector's parameter substitution, because a bare ``%`` in the SQL
string is treated as a parameter marker.
"""

from datetime import date

__all__ = ["month_bounds", "parse_iso_date", "format_year_month"]


def month_bounds(month_str):
    """Return ``(first_day, first_day_of_next_month)`` for a ``"YYYY-MM"`` string.

    The upper bound is exclusive, so callers use ``>= start AND < end``.
    Raises ``ValueError`` for anything that is not a well-formed year-month.
    """
    if not isinstance(month_str, str):
        raise ValueError(f"month must be a 'YYYY-MM' string, got {month_str!r}")
    parts = month_str.split("-")
    if (len(parts) != 2
            or len(parts[0]) != 4 or not parts[0].isdigit()
            or len(parts[1]) != 2 or not parts[1].isdigit()):
        raise ValueError(f"Invalid month {month_str!r}, expected 'YYYY-MM'")
    year, month = int(parts[0]), int(parts[1])
    if not (1 <= month <= 12):
        raise ValueError(f"Invalid month value in {month_str!r}")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def parse_iso_date(value):
    """Parse a ``"YYYY-MM-DD"`` string into a ``date``. Raises ``ValueError``."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"date must be a 'YYYY-MM-DD' string, got {value!r}")
    return date.fromisoformat(value.strip())


def format_year_month(year, month):
    """``(2026, 4) -> "2026-04"``."""
    return f"{int(year):04d}-{int(month):02d}"
