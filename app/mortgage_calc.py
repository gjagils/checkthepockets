"""Hypotheek-rekenkern: PMT, aflossingstabel, te-financieren, overwaarde, netto-maandlast.

Alle bedragen zijn Decimal (centen). Rentes zijn fracties (0.0375 = 3,75%).
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterator

_CENT = Decimal("0.01")


def _round_cent(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def pmt(principal: Decimal, annual_rate: Decimal, years: int) -> Decimal:
    """Annuïtaire maandlast. P = L * c / (1 − (1+c)^-n), c = rate/12, n = years*12.

    Bij rate = 0 valt de formule terug op gelijke aflossing (principal/n).
    Retourneert Decimal afgerond op centen.
    """
    if principal <= 0 or years <= 0:
        return Decimal("0.00")
    n = years * 12
    if annual_rate == 0:
        return _round_cent(principal / Decimal(n))
    c = annual_rate / Decimal(12)
    one_plus_c_n = (Decimal(1) + c) ** n
    monthly = principal * c * one_plus_c_n / (one_plus_c_n - Decimal(1))
    return _round_cent(monthly)


@dataclass
class AmortizationRow:
    month: int           # 1..n
    year: int            # 1..years
    payment: Decimal     # maandtermijn
    interest: Decimal    # rente-deel
    principal: Decimal   # aflossings-deel
    balance: Decimal     # restschuld einde maand


def amortization_schedule(
    principal: Decimal, annual_rate: Decimal, years: int,
) -> Iterator[AmortizationRow]:
    """Yield maandrijen. Laatste termijn corrigeert cent-afrondingen."""
    if principal <= 0 or years <= 0:
        return
    n = years * 12
    monthly_rate = annual_rate / Decimal(12)
    monthly_payment = pmt(principal, annual_rate, years)
    balance = principal
    for m in range(1, n + 1):
        interest = _round_cent(balance * monthly_rate)
        if m == n:
            # laatste termijn: schrap afrondings-drift
            principal_part = balance
            payment = _round_cent(principal_part + interest)
        else:
            principal_part = _round_cent(monthly_payment - interest)
            payment = monthly_payment
        balance = _round_cent(balance - principal_part)
        yield AmortizationRow(
            month=m,
            year=((m - 1) // 12) + 1,
            payment=payment,
            interest=interest,
            principal=principal_part,
            balance=max(balance, Decimal("0.00")),
        )


def to_finance(
    offer: Decimal,
    renovation_cost: Decimal,
    own_contribution: Decimal,
    purchase_costs_pct: Decimal,
) -> Decimal:
    """Te financieren bedrag: bod + verbouwing + aankoopkosten − eigen inbreng.

    Aankoopkosten worden berekend als percentage van het bod (overdracht,
    notaris, taxatie samen geschat in `purchase_costs_pct`).
    """
    purchase_costs = offer * purchase_costs_pct
    return _round_cent(offer + renovation_cost + purchase_costs - own_contribution)


def overwaarde(
    sale_old_home: Decimal, current_home_debt: Decimal, selling_costs_pct: Decimal,
) -> Decimal:
    """Netto overwaarde: verkoopprijs × (1 − verkoopkosten-pct) − restschuld."""
    return _round_cent(
        sale_old_home * (Decimal(1) - selling_costs_pct) - current_home_debt
    )


def annuity_principal(
    to_finance_amount: Decimal,
    existing_mortgage_pim: Decimal,
    existing_mortgage_interest_only: Decimal,
) -> Decimal:
    """Deel van to_finance dat annuïtair afgelost wordt (rest is aflossingsvrij
    of via bestaande hypotheek gedekt)."""
    amount = to_finance_amount - existing_mortgage_pim - existing_mortgage_interest_only
    return _round_cent(max(amount, Decimal(0)))


def ltv(to_finance_amount: Decimal, valuation: Decimal) -> Decimal:
    """Loan-to-value als fractie (0.85 = 85%)."""
    if valuation <= 0:
        return Decimal("0")
    return (to_finance_amount / valuation).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def pick_rate(
    rates,  # list[MortgageRateTable]
    fixed_years: int,
    ltv_fraction: Decimal,
) -> Decimal | None:
    """Kies de juiste rente-regel op basis van rentevast + LTV-bucket.

    Rij wordt gekozen als fixed_years matcht en ltv_max_pct >= ltv_fraction.
    Binnen kandidaten wint de laagste ltv_max_pct (smallste bucket).
    Retourneert None als er geen passende rij is.
    """
    candidates = [
        r for r in rates
        if r.fixed_years == fixed_years and Decimal(str(r.ltv_max_pct)) >= ltv_fraction
    ]
    if not candidates:
        return None
    winner = min(candidates, key=lambda r: Decimal(str(r.ltv_max_pct)))
    return Decimal(str(winner.interest_rate))


def net_monthly(
    monthly_payment: Decimal,
    annual_rate: Decimal,
    principal: Decimal,
    tax_rate: Decimal,
    notional_rent_value: Decimal,
) -> Decimal:
    """Netto maandlast na hypotheekrenteaftrek (eerste-jaar-benadering).

    Formule: bruto − (jaarrente − eigenwoningforfait) × tax_rate / 12.
    Dit benadert de eerste-jaar-gemiddelde nettolast zoals Excel D6/H28. De
    aftrekbasis valt met de tijd, dus dit is een boven-schatting van het
    voordeel op lange termijn.
    """
    if monthly_payment <= 0:
        return Decimal("0.00")
    annual_interest = principal * annual_rate
    deductible = max(annual_interest - notional_rent_value, Decimal(0))
    annual_refund = deductible * tax_rate
    monthly_refund = annual_refund / Decimal(12)
    return _round_cent(monthly_payment - monthly_refund)
