"""Tests voor leeftijd-helpers (LIN-34)."""
from __future__ import annotations

import datetime

from app.person_utils import age_years, format_age_nl


def test_age_years_none_without_birthdate():
    assert age_years(None) is None


def test_age_years_before_birthday_this_year():
    # Kind geboren 15 juni 2020, vandaag 10 juni 2026 → nog geen 6 geweest.
    bd = datetime.date(2020, 6, 15)
    today = datetime.date(2026, 6, 10)
    assert age_years(bd, today) == 5


def test_age_years_after_birthday_this_year():
    bd = datetime.date(2020, 6, 15)
    today = datetime.date(2026, 8, 1)
    assert age_years(bd, today) == 6


def test_age_years_birthday_today_is_new_age():
    # Acceptatiecriterium: verjaardag vandaag → exact N jaar.
    bd = datetime.date(2018, 4, 21)
    today = datetime.date(2026, 4, 21)
    assert age_years(bd, today) == 8


def test_age_years_day_before_birthday():
    bd = datetime.date(2018, 4, 21)
    today = datetime.date(2026, 4, 20)
    assert age_years(bd, today) == 7


def test_age_years_leap_day_born_non_leap_year():
    # Geboren op 29 feb. Op 28 feb 2026 (geen schrikkeljaar) is verjaardag nog
    # niet bereikt volgens (maand, dag)-vergelijking.
    bd = datetime.date(2020, 2, 29)
    today = datetime.date(2026, 2, 28)
    assert age_years(bd, today) == 5
    assert age_years(bd, datetime.date(2026, 3, 1)) == 6


def test_format_age_nl_empty_when_no_birthdate():
    assert format_age_nl(None) == ""


def test_format_age_nl_formats_years():
    bd = datetime.date(2018, 4, 21)
    today = datetime.date(2026, 4, 21)
    assert format_age_nl(bd, today) == "8 jaar"


def test_format_age_nl_one_year():
    bd = datetime.date(2025, 4, 21)
    today = datetime.date(2026, 4, 21)
    assert format_age_nl(bd, today) == "1 jaar"
