"""Unit tests for the scenario comparison steps of the mortgage detail page (ACT-23)."""
from decimal import Decimal as D
from types import SimpleNamespace as NS

from app import mortgage_calc


def _household(**overrides):
    fields = dict(
        tax_rate=D("0.37"), hra_correction_factor=D("0.95"), notional_rent_value=D("2000"),
        inflation_pct=D("0.10"), contribution_growth_pct=D("0.05"),
        annual_child_benefit=D("1200"), annual_private_loan_refund=None, annual_extra_primary=D("0"),
        annual_extra_secondary=None, annual_vacation_budget=D("3000"), annual_house_budget=D("600"),
    )
    fields.update(overrides)
    return NS(**fields)


def _stats(fixed_years=10, rate_missing=False):
    return {
        "fixed_years": fixed_years, "rate_missing": rate_missing,
        "annuity_monthly": D("1500.00"), "pim_monthly": D("100.00"), "interest_only_monthly": D("50.00"),
        "net_monthly": D("1300.00"), "used_monthly_refund": D("200.00"), "annual_savings": D("600.00"),
        "mortgage_net_by_year": [D("1800.00"), D("1750.00")],
        "existing_monthly_by_year": [D("300.00"), D("250.00")],
        "used_refund_monthly_by_year": [D("200.00"), D("190.00")],
    }


def test_bridge_cost_summary_deducts_hra_refund():
    fin = NS(bridge_gross_interest_total=D("1000.00"))
    assert mortgage_calc.bridge_cost_summary(fin, _household()) == (D("1000.00"), D("351.50"), D("648.50"))
    assert mortgage_calc.bridge_cost_summary(fin, _household(tax_rate=None))[2] == D("1000.00")


def test_default_variant_summary_with_rate():
    summary = mortgage_calc.default_variant_summary(
        {"fixed_years": 5, "rate": D("0.04"), "net_monthly": D("1200.00")}, D("300000"), _household(), [],
    )
    schedule = summary["schedule"]
    assert summary["rate_missing"] is False
    assert summary["monthly_payment"] == mortgage_calc.pmt(D("300000"), D("0.04"), 30)
    assert summary["first_5y_interest"] == sum((r.interest for r in schedule[:60]), D(0))
    year1_interest = sum((r.interest for r in schedule[:12]), D(0))
    assert summary["first_5y_refund"] > (year1_interest - D("2000")) * D("0.37")
    assert summary["net_monthly"] == D("1200.00")


def test_default_variant_summary_fallbacks():
    missing = mortgage_calc.default_variant_summary(None, D("300000"), _household(), [NS(fixed_years=20), NS(fixed_years=5)])
    assert (missing["rate_missing"], missing["fixed_years"], missing["schedule"]) == (True, 5, [])
    assert mortgage_calc.default_variant_summary(None, D("1"), _household(), [])["fixed_years"] == 10
    no_rate = {"fixed_years": 20, "rate": None, "net_monthly": D("0")}
    assert mortgage_calc.default_variant_summary(no_rate, D("1"), _household(), [])["fixed_years"] == 20


def test_monthly_total_replaces_mortgage_budget_categories():
    rows = [NS(effective_amount=D("1800"), cost_scale_type="mortgage"), NS(effective_amount=D("900"), cost_scale_type=None)]
    assert mortgage_calc.mortgage_budget_sum(rows) == D("1800")
    # 1300 new + 400 existing + (2700 budget − 1800 mortgage budget)
    assert mortgage_calc.scenario_monthly_total(D("1300"), D("400"), D("2700"), rows) == D("2600.00")


def test_variant_leftovers_skip_missing_rates():
    leftovers, pairs = mortgage_calc.variant_leftovers(
        [_stats(), _stats(rate_missing=True)], salary_sum=D("5000"), budget_total=D("2000"),
    )
    # 5000 − 2000 − (1300 + 100 + 50)
    assert leftovers == [D("1550.00"), None]
    assert pairs[1][1] is None


def test_add_variant_comparison_compounds_inflation_and_growth():
    stats, missing = _stats(), _stats(rate_missing=True)
    mortgage_calc.add_variant_comparison(
        [stats, missing], existing_monthly_total=D("400"), household=_household(),
        other_budget_total=D("1000.00"), contributions_monthly_total=D("3000.00"),
        ann_principal=D("0"), rate=None, bridge_net_cost=D("648.50"),
    )
    assert stats["existing_monthly_total"] == D("550.00")
    assert stats["total_costs"] == D("3050.00")
    assert stats["total_income"] == D("3200.00")
    assert stats["resultaat"] == D("150.00")
    assert stats["savings_remainder_monthly"] == D("50.00")
    # Year 1: 3000 + 200 − (1500 + 300 + 1000); year 2: 3150 + 190 − (1500 + 250 + 1100)
    assert stats["surplus_by_year"] == [D("400.00"), D("490.00")]
    assert stats["savings_income_yr"] == D("6600.00")  # 400×12 + 1200 child benefit + 600 remaining refund
    assert stats["savings_expense_yr"] == D("3600.00")
    assert stats["net_annual_savings"] == D("2351.50")
    assert stats["avg_annual_amortization_5y"] == D("0.00")
    assert missing["total_costs"] == D("0.00")
    assert "surplus_by_year" not in missing


def test_variant_chart_series_pads_to_thirty_years_and_skips_missing():
    stats = _stats(fixed_years=10)
    stats["surplus_by_year"] = [D("400.00")]
    unknown = _stats(fixed_years=15)
    unknown["surplus_by_year"] = []
    series = mortgage_calc.variant_chart_series([stats, _stats(rate_missing=True), unknown])

    assert [s["label"] for s in series] == ["10j netto hypotheek-last", "10j overschot", "15j netto hypotheek-last", "15j overschot"]
    assert series[0]["data"][:3] == [1800.0, 1750.0, 1750.0] and len(series[0]["data"]) == 30
    assert series[1]["data"] == [400.0] * 30
    assert series[1]["backgroundColor"] == "rgba(255,159,64,0.15)"
    assert series[2]["borderColor"] == "rgba(128,128,128,1)"
    assert series[3]["data"] == [0] * 30
