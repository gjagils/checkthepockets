"""Leeftijd-helpers voor Person (LIN-34).

Gebruikt vanuit templates en toekomstige projecties. Gescheiden van het model
omdat een pure functie makkelijker te testen is dan een `@property` op een
SQLAlchemy-object (fixture-gedoe met sessies).
"""
from __future__ import annotations

import datetime


def age_years(birthdate: datetime.date | None, today: datetime.date | None = None) -> int | None:
    """Heel jaartal leeftijd op `today`. None als `birthdate` niet bekend is.

    Corrigeert voor of de verjaardag dit jaar al is geweest. Als vandaag exact
    de verjaardag is telt de persoon als die nieuwe leeftijd (N+1 bij eerste
    verjaardag).
    """
    if birthdate is None:
        return None
    if today is None:
        today = datetime.date.today()
    years = today.year - birthdate.year
    # Verjaardag nog niet bereikt dit jaar → 1 minder.
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return years


def format_age_nl(birthdate: datetime.date | None, today: datetime.date | None = None) -> str:
    """Nederlandse weergave: '8 jaar' (meervoud), '1 jaar' (enkelvoud), '' bij geen datum."""
    years = age_years(birthdate, today)
    if years is None:
        return ""
    return f"{years} jaar"


MONTH_NAMES_NL_FULL = [
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def months_until_18(
    birthdate: datetime.date | None, today: datetime.date | None = None,
) -> int | None:
    """Aantal hele maanden tot de maand waarin de persoon 18 wordt.

    Returnt `None` als `birthdate` None is of de persoon al 18+ is. Returnt 0 als
    de 18e verjaardag in de huidige kalendermaand valt — gebruikt door de
    kind-prognose om in dat geval gewoon de huidige waarde te tonen (geen
    extra groei-stappen).
    """
    if birthdate is None:
        return None
    if today is None:
        today = datetime.date.today()
    if age_years(birthdate, today) >= 18:
        return None
    months = (birthdate.year + 18 - today.year) * 12 + (birthdate.month - today.month)
    return max(0, months)


def eighteenth_month_label_nl(
    birthdate: datetime.date, today: datetime.date | None = None,
) -> str:
    """Weergave zoals 'mei 2036' voor kaart-tekst 'wordt 18 in …'."""
    if today is None:
        today = datetime.date.today()
    year = birthdate.year + 18
    return f"{MONTH_NAMES_NL_FULL[birthdate.month]} {year}"
