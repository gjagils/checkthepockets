"""Unit tests voor app/mortgage_calc.py (GJA-28)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.mortgage_calc import (
    amortization_schedule,
    annuity_principal,
    ltv,
    net_monthly,
    overwaarde,
    pick_rate,
    pmt,
    to_finance,
)


def test_pmt_standard_case():
    # €300.000 @ 3,75% over 30 jaar → Excel PMT = ~1389,35.
    monthly = pmt(Decimal("300000"), Decimal("0.0375"), 30)
    assert abs(monthly - Decimal("1389.35")) <= Decimal("1")


def test_pmt_zero_rate_falls_back_to_equal_principal():
    monthly = pmt(Decimal("12000"), Decimal("0"), 1)
    assert monthly == Decimal("1000.00")


def test_pmt_zero_principal_returns_zero():
    assert pmt(Decimal("0"), Decimal("0.05"), 30) == Decimal("0.00")


def test_amortization_schedule_ends_at_zero_balance():
    rows = list(amortization_schedule(Decimal("300000"), Decimal("0.0375"), 30))
    assert len(rows) == 360
    assert rows[-1].balance == Decimal("0.00")


def test_amortization_schedule_interest_plus_principal_equals_payment():
    rows = list(amortization_schedule(Decimal("100000"), Decimal("0.04"), 10))
    for row in rows[:-1]:  # laatste rij corrigeert afronding
        assert row.interest + row.principal == row.payment


def test_amortization_total_interest_positive():
    rows = list(amortization_schedule(Decimal("100000"), Decimal("0.04"), 10))
    total_principal = sum((r.principal for r in rows), Decimal(0))
    assert total_principal == Decimal("100000.00")
    total_interest = sum((r.interest for r in rows), Decimal(0))
    assert total_interest > 0


def test_to_finance_formula():
    # bod 400k + verbouw 20k + 2.5% kosten op bod − eigen inbreng 30k = 400+20+10−30 = 400.
    result = to_finance(
        offer=Decimal("400000"),
        renovation_cost=Decimal("20000"),
        own_contribution=Decimal("30000"),
        purchase_costs_pct=Decimal("0.025"),
    )
    assert result == Decimal("400000.00")


def test_overwaarde_formula():
    # verkoop 350k × (1 − 0.015) − restschuld 280k = 344750 − 280000 = 64750.
    result = overwaarde(
        sale_old_home=Decimal("350000"),
        current_home_debt=Decimal("280000"),
        selling_costs_pct=Decimal("0.015"),
    )
    assert result == Decimal("64750.00")


def test_annuity_principal_subtracts_existing():
    assert annuity_principal(
        Decimal("400000"), Decimal("150000"), Decimal("50000"),
    ) == Decimal("200000.00")


def test_annuity_principal_cannot_go_negative():
    assert annuity_principal(
        Decimal("100000"), Decimal("200000"), Decimal("50000"),
    ) == Decimal("0.00")


def test_ltv_fraction():
    assert ltv(Decimal("425000"), Decimal("500000")) == Decimal("0.8500")


def test_ltv_zero_valuation_returns_zero():
    assert ltv(Decimal("400000"), Decimal("0")) == Decimal("0")


def test_pick_rate_chooses_smallest_matching_bucket():
    rates = [
        SimpleNamespace(fixed_years=10, ltv_max_pct=Decimal("0.65"), interest_rate=Decimal("0.0373")),
        SimpleNamespace(fixed_years=10, ltv_max_pct=Decimal("0.85"), interest_rate=Decimal("0.0375")),
        SimpleNamespace(fixed_years=10, ltv_max_pct=Decimal("0.86"), interest_rate=Decimal("0.0377")),
        SimpleNamespace(fixed_years=20, ltv_max_pct=Decimal("0.85"), interest_rate=Decimal("0.0425")),
    ]
    # LTV 0.60 → 65%-bucket.
    assert pick_rate(rates, 10, Decimal("0.6000")) == Decimal("0.0373")
    # LTV 0.80 → 85%-bucket (65% is te klein).
    assert pick_rate(rates, 10, Decimal("0.8000")) == Decimal("0.0375")
    # LTV 0.855 → 86%-bucket.
    assert pick_rate(rates, 10, Decimal("0.8550")) == Decimal("0.0377")


def test_pick_rate_returns_none_when_no_match():
    rates = [
        SimpleNamespace(fixed_years=10, ltv_max_pct=Decimal("0.85"), interest_rate=Decimal("0.0375")),
    ]
    assert pick_rate(rates, 10, Decimal("0.95")) is None  # boven bucket
    assert pick_rate(rates, 5, Decimal("0.80")) is None   # verkeerd aantal jaren


def test_net_monthly_reduces_gross_by_tax_refund():
    # principal 200k @ 3,75% → jaarrente 7500. Minus forfait 3600 = 3900 aftrek.
    # Refund jaar = 3900 × 0.3697 = 1441.83. Per maand ≈ 120,15.
    # Gross ~930 (200k/30y @ 3,75%) → net ≈ 810.
    gross = pmt(Decimal("200000"), Decimal("0.0375"), 30)
    result = net_monthly(
        gross, Decimal("0.0375"), Decimal("200000"),
        tax_rate=Decimal("0.3697"), notional_rent_value=Decimal("3600"),
    )
    assert result < gross
    assert abs(result - Decimal("805")) <= Decimal("10")


def test_net_monthly_no_refund_when_below_notional():
    # Klein hypotheek: jaarrente onder forfait → geen aftrek, netto == bruto.
    gross = pmt(Decimal("50000"), Decimal("0.02"), 30)
    result = net_monthly(
        gross, Decimal("0.02"), Decimal("50000"),
        tax_rate=Decimal("0.3697"), notional_rent_value=Decimal("3600"),
    )
    assert result == gross
