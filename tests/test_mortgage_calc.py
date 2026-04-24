"""Unit tests voor app/mortgage_calc.py (GJA-28)."""
import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.mortgage_calc import (
    amortization_schedule,
    annuity_principal,
    bridge_loan_metrics,
    bridge_months_between,
    compute_scenario_financials,
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


# ── Overbruggingshypotheek ──────────────────────────────────────────────────


def test_bridge_months_between_same_day_counts_as_one_month():
    # 1 juli → 1 augustus = één hele maand overbrugging.
    result = bridge_months_between(
        datetime.date(2026, 7, 1), datetime.date(2026, 8, 1),
    )
    assert result == 1


def test_bridge_months_between_typical_four_month_gap():
    # Overdracht 1 juli, verkoop 1 november = 4 maanden.
    result = bridge_months_between(
        datetime.date(2026, 7, 1), datetime.date(2026, 11, 1),
    )
    assert result == 4


def test_bridge_months_between_partial_month_rounds_down():
    # 1 juli → 20 juli = geen volle maand → 0.
    result = bridge_months_between(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 20),
    )
    assert result == 0


def test_bridge_months_between_none_returns_zero():
    assert bridge_months_between(None, datetime.date(2026, 8, 1)) == 0
    assert bridge_months_between(datetime.date(2026, 7, 1), None) == 0
    assert bridge_months_between(None, None) == 0


def test_bridge_months_between_reverse_order_returns_zero():
    # Verkoop vóór overdracht: geen overbrugging nodig — 0 teruggeven zodat
    # het restje van de pipeline dat signaal correct interpreteert.
    result = bridge_months_between(
        datetime.date(2026, 11, 1), datetime.date(2026, 7, 1),
    )
    assert result == 0


def test_bridge_loan_metrics_standard_case():
    # €370.000 @ 4,20% over 4 maanden:
    # maandlast = 370000 × 0.042 / 12 = 1295,00
    # totaal = 1295 × 4 = 5180,00
    monthly, total = bridge_loan_metrics(Decimal("370000"), Decimal("0.0420"), 4)
    assert monthly == Decimal("1295.00")
    assert total == Decimal("5180.00")


def test_bridge_loan_metrics_zero_months_returns_zero():
    monthly, total = bridge_loan_metrics(Decimal("370000"), Decimal("0.0420"), 0)
    assert monthly == Decimal("0.00")
    assert total == Decimal("0.00")


def test_bridge_loan_metrics_zero_amount_returns_zero():
    monthly, total = bridge_loan_metrics(Decimal("0"), Decimal("0.0420"), 4)
    assert monthly == Decimal("0.00")
    assert total == Decimal("0.00")


def _scenario_stub(**kwargs):
    """SimpleNamespace met alle velden die compute_scenario_financials nodig heeft."""
    defaults = dict(
        offer=Decimal("500000"),
        renovation_cost=Decimal("0"),
        own_contribution=Decimal("50000"),
        sale_old_home=Decimal("450000"),
        valuation=Decimal("500000"),
        purchase_fee_pct=Decimal("2.5"),
        sale_fee_pct=Decimal("1.5"),
        existing_mortgages=[],
        transfer_date_new=None,
        sale_date_old=None,
        bridge_amount_override=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_compute_scenario_financials_without_bridge_dates_has_zero_bridge():
    fin = compute_scenario_financials(_scenario_stub())
    assert fin.bridge_months == 0
    assert fin.bridge_amount == Decimal("0.00")
    assert fin.bridge_monthly_interest == Decimal("0.00")
    assert fin.bridge_gross_interest_total == Decimal("0.00")


def test_compute_scenario_financials_with_bridge_computes_metrics():
    scenario = _scenario_stub(
        transfer_date_new=datetime.date(2026, 7, 1),
        sale_date_old=datetime.date(2026, 11, 1),
    )
    household = SimpleNamespace(bridge_rate_pct=Decimal("0.0420"))
    fin = compute_scenario_financials(scenario, household)
    assert fin.bridge_months == 4
    # Bedrag = overwaarde = 450000 × (1 − 0.015) − 0 (geen bestaande) = 443250,
    # dan wel het netto overwaarde-getal uit de formule. Belangrijker: > 0 en
    # de metrics zijn consistent.
    assert fin.bridge_amount > Decimal("0.00")
    assert fin.bridge_monthly_interest > Decimal("0.00")
    expected_total = fin.bridge_monthly_interest * 4
    assert fin.bridge_gross_interest_total == expected_total


def test_compute_scenario_financials_respects_bridge_override():
    scenario = _scenario_stub(
        transfer_date_new=datetime.date(2026, 7, 1),
        sale_date_old=datetime.date(2026, 11, 1),
        bridge_amount_override=Decimal("200000"),
    )
    household = SimpleNamespace(bridge_rate_pct=Decimal("0.0420"))
    fin = compute_scenario_financials(scenario, household)
    assert fin.bridge_amount == Decimal("200000.00")
    # 200000 × 0.042 / 12 = 700,00
    assert fin.bridge_monthly_interest == Decimal("700.00")
