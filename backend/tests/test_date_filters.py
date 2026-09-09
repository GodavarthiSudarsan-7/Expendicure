from datetime import date

import pytest

from date_filters import month_bounds, parse_iso_date, format_year_month


def test_month_bounds_basic():
    assert month_bounds("2026-04") == (date(2026, 4, 1), date(2026, 5, 1))


def test_month_bounds_december_rolls_year():
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


def test_month_bounds_january():
    assert month_bounds("2026-01") == (date(2026, 1, 1), date(2026, 2, 1))


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026", "abc", "2026-4-1", "", "26-04"])
def test_month_bounds_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        month_bounds(bad)


def test_month_bounds_rejects_non_string():
    with pytest.raises(ValueError):
        month_bounds(202604)


def test_parse_iso_date_ok():
    assert parse_iso_date("2026-04-01") == date(2026, 4, 1)


def test_parse_iso_date_passthrough_date():
    d = date(2026, 4, 1)
    assert parse_iso_date(d) is d


@pytest.mark.parametrize("bad", ["01/04/2026", "2026-4-1", "not-a-date", "2026-13-01"])
def test_parse_iso_date_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_iso_date(bad)


def test_format_year_month():
    assert format_year_month(2026, 4) == "2026-04"
    assert format_year_month("2026", "12") == "2026-12"
