"""ACT-49: Jinja-filters voor datums en bedragen."""
from datetime import date, datetime
from decimal import Decimal

from app.template_config import templates


def _render(expr, **ctx):
    return templates.env.from_string("{{ " + expr + " }}").render(**ctx)


def test_date_and_datetime_filters_handle_none():
    assert _render("d|date", d=date(2026, 3, 9)) == "09-03-2026"
    assert _render("d|datetime", d=datetime(2026, 3, 9, 14, 5)) == "09-03-2026 14:05"
    assert _render("d|date", d=None) == ""
    assert _render("d|datetime", d=None) == ""


def test_euro_sign_matches_euro_filter_with_symbol():
    assert _render("v|euro_sign", v=Decimal("1234.5")) == "€ 1.234,50"
    assert _render("v|euro_sign", v=Decimal("-3")) == "€ -3,00"
    assert _render("v|euro0_sign", v=Decimal("1234.6")) == "€ 1.235"
