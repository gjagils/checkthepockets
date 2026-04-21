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
