"""Regression tests for recurring schedule rules and savings calculations (ACT-22)."""
from datetime import date
from decimal import Decimal

import pytest

from app.models import RecurringTransaction
from app.recurring_schedule import (
    add_skipped_month, get_period_range, get_previous_period_range, is_active_in_month,
    is_in_active_period, parse_active_months, projected_hash, remove_skipped_month,
)
from app.savings_calc import determine_color_status, months_for_frequency, parse_custom_amounts

TODAY = date(2026, 6, 15)


def _item(**fields):
    return RecurringTransaction(name="Huur", amount_expected=Decimal("-900"), frequency="monthly", **fields)


@pytest.mark.parametrize("frequency, ref, expected", [
    ("weekly", date(2026, 9, 23), (date(2026, 9, 21), date(2026, 9, 27))),
    ("monthly", date(2024, 2, 10), (date(2024, 2, 1), date(2024, 2, 29))),
    ("quarterly", date(2026, 11, 5), (date(2026, 10, 1), date(2026, 12, 31))),
    ("yearly", date(2026, 3, 1), (date(2026, 1, 1), date(2026, 12, 31))),
    ("unknown", date(2026, 4, 30), (date(2026, 4, 1), date(2026, 4, 30))),
])
def test_period_ranges(frequency, ref, expected):
    assert get_period_range(frequency, ref) == expected


def test_previous_period_crosses_year_boundary():
    assert get_previous_period_range("monthly", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert get_previous_period_range("quarterly", date(2026, 2, 1)) == (date(2025, 10, 1), date(2025, 12, 31))


def test_active_months_parsing_and_period():
    assert parse_active_months(["12", "1", "1", "13", "x"]) == "1,12"
    assert parse_active_months([str(m) for m in range(1, 13)]) is None
    assert parse_active_months([]) is None

    winter = _item(active_months="1,2,12")
    assert not is_in_active_period(winter, TODAY)
    assert is_in_active_period(_item(active_months="bad,value"), TODAY)
    assert not is_in_active_period(_item(start_date=date(2026, 7, 1)), TODAY)
    assert not is_in_active_period(_item(end_date=date(2026, 6, 1)), TODAY)


def test_active_in_month_respects_dates_months_and_skips():
    item = _item(start_date=date(2026, 3, 20), end_date=date(2026, 10, 1), active_months="3,4,10,11")
    assert is_active_in_month(item, 2026, 3)  # start date falls inside the month
    assert not is_active_in_month(item, 2026, 2)
    assert is_active_in_month(item, 2026, 10)  # end date on the first of the month
    assert not is_active_in_month(item, 2026, 11)
    assert not is_active_in_month(item, 2026, 5)  # not an active month

    add_skipped_month(item, 2026, 4)
    add_skipped_month(item, 2026, 3)
    assert item.skipped_months == "2026-03,2026-04"
    assert not is_active_in_month(item, 2026, 4)
    remove_skipped_month(item, 2026, 3)
    remove_skipped_month(item, 2026, 4)
    assert item.skipped_months is None


def test_projected_hash_is_canonical():
    assert projected_hash(7, 2026, 3) == "projected-7-2026-03"


@pytest.mark.parametrize("frequency, target, months", [
    ("monthly", None, list(range(1, 13))),
    ("quarterly", None, [3, 6, 9, 12]),
    ("quarterly", 2, [2, 5, 8, 11]),
    ("biannual", 1, [1, 7]),
    ("yearly", None, [12]),
    ("yearly", 4, [4]),
    ("one-off", None, []),
    ("one-off", 9, [9]),
    ("custom", 3, []),
    ("unknown", None, list(range(1, 13))),
])
def test_months_for_frequency(frequency, target, months):
    assert months_for_frequency(frequency, target) == months


def test_parse_custom_amounts():
    values = ["10", "12,50", "", " ", "abc", "-5"] + [""] * 6
    parsed = parse_custom_amounts(*values)
    assert parsed[1] == Decimal("10")
    assert parsed[2] == Decimal("12.50")
    assert parsed[3] is None and parsed[4] is None and parsed[5] is None
    assert parsed[6] == Decimal("-5")
    assert set(parsed) == set(range(1, 13))


@pytest.mark.parametrize("actual, expected, is_income, month, fully, status", [
    (Decimal("100"), Decimal("100"), False, 7, False, "forecast"),   # future month
    (Decimal("100"), Decimal("50"), False, 6, False, "current"),     # current month
    (None, Decimal("50"), False, 5, False, "forecast"),              # no data yet
    (None, Decimal("50"), False, 5, True, "above"),                  # fully categorized: spent 0
    (None, Decimal("50"), True, 5, True, "below"),                   # fully categorized: received 0
    (Decimal("-50"), Decimal("50"), False, 5, False, "match"),
    (Decimal("-40"), Decimal("50"), False, 5, False, "above"),
    (Decimal("-60"), Decimal("50"), False, 5, False, "below"),
    (Decimal("60"), Decimal("50"), True, 5, False, "above"),
    (Decimal("40"), None, True, 5, False, "above"),
])
def test_color_status(actual, expected, is_income, month, fully, status):
    assert determine_color_status(actual, expected, is_income, month, 2026, TODAY, fully) == status
