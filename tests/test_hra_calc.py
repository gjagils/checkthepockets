"""Unit tests voor de hypotheekrenteaftrek-helpers in mortgage_calc.

Bevat een regressie-check op de werkelijke aangifte 2025: Pim €135.000 × 6%
+ ABN €145.000 × 1,76% = €10.652 rente, WOZ €597.000 → EWF €2.089,50,
tarief 37,56% × correctie 0,9482 → teruggaaf €3.049,48. Werkelijke aangifte
was €3.043; 0,2% afwijking is acceptabel voor de kalibratie.
"""
from decimal import Decimal

from app import mortgage_calc


def test_ewf_below_threshold_uses_low_pct():
    assert mortgage_calc.ewf_amount(
        Decimal("597000"), Decimal("0.0035"),
    ) == Decimal("2089.50")


def test_ewf_above_threshold_applies_high_pct():
    # WOZ € 1.500.000: eerste € 1.340.000 × 0,35% = € 4.690
    # daarboven € 160.000 × 2,35% = € 3.760
    # totaal € 8.450
    assert mortgage_calc.ewf_amount(
        Decimal("1500000"), Decimal("0.0035"),
    ) == Decimal("8450.00")


def test_ewf_zero_woz_returns_zero():
    assert mortgage_calc.ewf_amount(Decimal("0"), Decimal("0.0035")) == Decimal("0.00")


def test_hra_refund_zero_when_interest_below_forfait():
    # Rente € 2.000, EWF € 3.000 → saldo 0 → geen teruggaaf.
    assert mortgage_calc.hra_refund(
        Decimal("2000"), Decimal("3000"), Decimal("0.3756"), Decimal("1.0"),
    ) == Decimal("0.00")


def test_hra_refund_regression_on_2025_aangifte():
    """Aangifte 2025 GJ: werkelijke teruggaaf € 3.043 bij € 10.652 rente,
    WOZ € 597.000, tarief 37,56%, correctiefactor 0,9482.

    Modelmatig verwacht: € 3.049 (afwijking < 0,2%).
    """
    ewf = mortgage_calc.ewf_amount(Decimal("597000"), Decimal("0.0035"))
    refund = mortgage_calc.hra_refund(
        Decimal("10652"),
        ewf,
        Decimal("0.3756"),
        Decimal("0.9482"),
    )
    assert Decimal("3040") <= refund <= Decimal("3055"), (
        f"Regressie teruggaaf 2025: verwacht ~€3.043, kreeg €{refund}"
    )


def test_hra_refund_correction_factor_scales_linearly():
    base = mortgage_calc.hra_refund(
        Decimal("10000"), Decimal("2000"), Decimal("0.3756"), Decimal("1.0"),
    )
    corrected = mortgage_calc.hra_refund(
        Decimal("10000"), Decimal("2000"), Decimal("0.3756"), Decimal("0.5"),
    )
    # 50% correctie moet exact 50% van het bedrag opleveren.
    assert corrected == (base * Decimal("0.5")).quantize(Decimal("0.01"))
