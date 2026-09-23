"""Regression values for existing loan parts and variant stats (ACT-23).

Expected values were produced by the route implementation before it moved to
app.mortgage_calc; today is fixed so rate changes land in a known year.
"""
import datetime as real_datetime
import types
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from app import mortgage_calc


class _FixedDate(real_datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 9, 23)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(mortgage_calc, "datetime", types.SimpleNamespace(date=_FixedDate))


def _interest_only():
    return NS(balance_eur=200000, mortgage_type="interest_only", rate_pct=D("2.5"), rate_pct_after=D("4.1"),
              rate_change_date=real_datetime.date(2027, 5, 1), months_remaining=None,
              hra_end_date=real_datetime.date(2031, 1, 1))


def _annuity():
    return NS(balance_eur=150000, mortgage_type="annuity", rate_pct=D("3.2"), rate_pct_after=None,
              rate_change_date=None, months_remaining=240, hra_end_date=None)


def _household():
    return NS(tax_rate=D("0.3697"), hra_correction_factor=D("0.95"), ewf_pct=D("0.0035"),
              existing_mortgage_pim=D("50000"), existing_mortgage_pim_rate=D("0.031"),
              existing_mortgage_interest_only_monthly=D("120"))


def _scenario(refund_usage=None):
    return NS(woz_value=None, valuation=D("650000"), monthly_refund_usage=refund_usage,
              existing_mortgages=[_interest_only(), _annuity()])


def test_rate_for_date_uses_rate_after_change():
    em = _interest_only()
    assert mortgage_calc.em_rate_for_date(em, real_datetime.date(2027, 4, 30)) == D("0.025")
    assert mortgage_calc.em_rate_for_date(em, real_datetime.date(2027, 6, 1)) == D("0.041")
    assert mortgage_calc.em_rate_for_date(NS(rate_pct=None, rate_change_date=None, rate_pct_after=None),
                                          real_datetime.date(2027, 1, 1)) is None


def test_existing_loan_yearly_amounts():
    interest_only, annuity = _interest_only(), _annuity()
    # Rate change in May 2027 (year offset 1): four months old rate, eight months new rate.
    assert mortgage_calc.existing_mortgage_yearly_interest(interest_only, 1) == D("7133.33")
    assert mortgage_calc.existing_mortgage_yearly_gross(interest_only, 1) == D("7133.33")
    assert mortgage_calc.existing_mortgage_yearly_gross(annuity, 0) == D("10163.88")
    assert mortgage_calc.existing_mortgage_yearly_interest(annuity, 0) == D("4720.62")
    assert mortgage_calc.existing_mortgage_yearly_interest(annuity, 10) == D("2671.00")
    no_balance = NS(balance_eur=0, mortgage_type="annuity", rate_pct=D("3"), rate_pct_after=None,
                    rate_change_date=None, months_remaining=100, hra_end_date=None)
    assert mortgage_calc.existing_mortgage_yearly_gross(no_balance, 0) == D("0")


def test_variant_stats_with_full_refund():
    variant = NS(fixed_years=10, interest_rate_override=D("0.0395"))
    stats = mortgage_calc.variant_stats(variant, D("400000"), D("0.8"), [], _household(), _scenario())

    assert (stats["rate"], stats["rate_source"]) == (D("0.0395"), "handmatig")
    assert stats["annuity_monthly"] == D("1898.15")
    assert stats["pim_monthly"] == D("129.17")
    assert stats["ewf_yr"] == D("2275.00")
    assert stats["annual_refund"] == D("6844.68")
    assert stats["monthly_refund"] == D("570.39")
    assert stats["net_monthly"] == D("1327.76")
    assert stats["first_5y_total_cost"] == D("70857.72")
    assert stats["mortgage_net_by_year"][:3] == [D("2485.19"), D("2614.07"), D("2685.78")]
    assert stats["mortgage_net_by_year"][5] == D("2971.13")
    assert stats["net_monthly_by_year"][4] == D("1185.14")
    assert len(stats["mortgage_net_by_year"]) == 30


def test_variant_stats_with_capped_refund_usage():
    variant = NS(fixed_years=10, interest_rate_override=D("0.0395"))
    stats = mortgage_calc.variant_stats(variant, D("400000"), D("0.8"), [], _household(), _scenario(D("150")))

    assert stats["used_monthly_refund"] == D("150.00")
    assert stats["annual_savings"] == D("5044.68")
    assert stats["net_monthly"] == D("1748.15")


def test_variant_stats_without_rate():
    variant = NS(fixed_years=5, interest_rate_override=None)
    stats = mortgage_calc.variant_stats(variant, D("400000"), D("0.8"), [], _household(), _scenario())

    assert stats["rate_missing"] is True
    assert stats["net_monthly"] == D("0.00")
    assert stats["mortgage_net_by_year"] == []
