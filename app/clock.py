"""Eén plek voor "nu" en "vandaag".

De container draait in UTC, de gebruiker en de scheduler in Europe/Amsterdam. Tussen 00:00 en 02:00
Nederlandse tijd valt `date.today()` in UTC nog op de vorige dag (en soms de vorige maand), waardoor
maandgrenzen, "is dit al voorbij" en projecties een dag/maand te vroeg rekenen. Gebruik daarom:

* `today_nl()`  voor alles wat "vandaag" voor de gebruiker betekent;
* `now_utc()`   voor tijdstempels in de database (naïef UTC, zoals de kolommen al zijn).

Aanroepen als `clock.today_nl()` (niet `from app.clock import today_nl`), zodat tests de klok kunnen
vervangen.
"""
import datetime
from zoneinfo import ZoneInfo

NL_TZ = ZoneInfo("Europe/Amsterdam")


def now_utc() -> datetime.datetime:
    """Naïeve UTC-tijd; vervangt het verouderde `datetime.utcnow()`."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def today_nl() -> datetime.date:
    """De datum van vandaag in Nederland."""
    return datetime.datetime.now(NL_TZ).date()
