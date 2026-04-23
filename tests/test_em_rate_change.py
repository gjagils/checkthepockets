"""Tests voor rentesprong op een bestaand leningdeel.

Voorbeeld: ABN aflossingsvrij 1,76% t/m 31-12-2030, dan 4,45% vanaf
01-01-2031 op dezelfde hoofdsom.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.mortgage_calc import effective_rate_pct_today


def _em(**kw):
    """Helper: bouw een object dat genoeg van ScenarioExistingMortgage-
    attributen heeft voor de helpers."""
    defaults = dict(
        rate_pct=Decimal("1.760"),
        rate_pct_after=None,
        rate_change_date=None,
        balance_eur=Decimal("145000"),
        mortgage_type="interest_only",
        months_remaining=None,
        hra_end_date=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_effective_rate_without_change_returns_rate_pct():
    em = _em(rate_pct=Decimal("1.760"))
    assert effective_rate_pct_today(em) == Decimal("1.760")


def test_effective_rate_with_future_change_ignores_rate2():
    future = date(date.today().year + 10, 1, 1)
    em = _em(
        rate_pct=Decimal("1.760"),
        rate_pct_after=Decimal("4.450"),
        rate_change_date=future,
    )
    assert effective_rate_pct_today(em) == Decimal("1.760")


def test_effective_rate_with_past_change_uses_rate2():
    past = date(date.today().year - 1, 1, 1)
    em = _em(
        rate_pct=Decimal("1.760"),
        rate_pct_after=Decimal("4.450"),
        rate_change_date=past,
    )
    assert effective_rate_pct_today(em) == Decimal("4.450")


def test_effective_rate_falls_back_to_none_if_no_rate():
    em = _em(rate_pct=None)
    assert effective_rate_pct_today(em) is None
