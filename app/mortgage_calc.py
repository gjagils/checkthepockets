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


def _calc_annuity_monthly_from_months(
    principal: Decimal, annual_rate: Decimal, months: int,
) -> Decimal:
    """Annuïtaire maandlast voor een willekeurig aantal maanden.

    Varianten: `pmt(...)` neemt jaren; deze accepteert maanden zodat we het
    resterende looptijd-veld van een bestaande hypotheek direct kunnen gebruiken.
    """
    if principal <= 0 or months <= 0:
        return Decimal("0.00")
    if annual_rate == 0:
        return _round_cent(principal / Decimal(months))
    c = annual_rate / Decimal(12)
    one_plus_c_n = (Decimal(1) + c) ** months
    monthly = principal * c * one_plus_c_n / (one_plus_c_n - Decimal(1))
    return _round_cent(monthly)


def existing_mortgage_monthly(
    balance: Decimal,
    mortgage_type: str,
    rate_pct: Decimal | None,
    months_remaining: int | None,
    override: Decimal | None = None,
) -> Decimal:
    """Maandlast van een bestaande hypotheek (annuity of interest_only).

    Als `override` is ingevuld wordt die direct gerespecteerd — nuttig voor
    afwijkende aflosvormen die we nog niet modelleren.
    """
    if override is not None and override > 0:
        return _round_cent(override)
    if balance is None or balance <= 0 or rate_pct is None:
        return Decimal("0.00")
    annual = Decimal(str(rate_pct)) / Decimal(100)
    if mortgage_type == "interest_only":
        return _round_cent(Decimal(str(balance)) * annual / Decimal(12))
    # Annuity: gebruik months_remaining; valt terug op 30 jaar als niet gezet.
    months = int(months_remaining) if months_remaining and months_remaining > 0 else 360
    return _calc_annuity_monthly_from_months(Decimal(str(balance)), annual, months)


@dataclass
class ScenarioFinancials:
    """Alle afgeleide bedragen voor de derived-waardes-kaart."""
    purchase_fee: Decimal
    sale_fee: Decimal
    existing_total: Decimal
    overwaarde: Decimal
    te_financieren: Decimal
    nieuwe_annuiteit: Decimal
    ltv_fraction: Decimal  # als fractie (0.85 = 85%)
    existing_monthly_total: Decimal
    existing_lines: list[dict]  # [{"id", "name", "type", "balance", "monthly"}, ...]


def compute_scenario_financials(scenario) -> ScenarioFinancials:
    """Bereken alle afgeleide waardes voor een scenario conform LIN-44.

    De scenario-objecten zijn SQLAlchemy-modellen; we lezen alleen simpele
    velden zodat deze functie ook buiten een sessie getest kan worden met
    eenvoudige stubs.
    """
    offer = Decimal(str(scenario.offer or 0))
    renovation = Decimal(str(scenario.renovation_cost or 0))
    own_contrib = Decimal(str(scenario.own_contribution or 0))
    sale_old = Decimal(str(scenario.sale_old_home or 0))
    valuation = Decimal(str(scenario.valuation or 0))
    purchase_pct = Decimal(str(scenario.purchase_fee_pct or 0))
    sale_pct = Decimal(str(scenario.sale_fee_pct or 0))

    purchase_fee = _round_cent(offer * purchase_pct / Decimal(100))
    sale_fee = _round_cent(sale_old * sale_pct / Decimal(100))

    existing_lines: list[dict] = []
    existing_total = Decimal("0")
    existing_monthly_total = Decimal("0")
    for m in getattr(scenario, "existing_mortgages", []) or []:
        bal = Decimal(str(m.balance_eur or 0))
        existing_total += bal
        monthly = existing_mortgage_monthly(
            balance=bal,
            mortgage_type=m.mortgage_type or "annuity",
            rate_pct=m.rate_pct,
            months_remaining=m.months_remaining,
            override=(Decimal(str(m.monthly_payment_eur))
                     if m.monthly_payment_eur is not None and m.monthly_payment_eur > 0
                     else None),
        )
        existing_monthly_total += monthly
        existing_lines.append({
            "id": m.id,
            "name": m.name,
            "type": m.mortgage_type or "annuity",
            "balance": bal,
            "rate_pct": m.rate_pct,
            "months_remaining": m.months_remaining,
            "monthly": monthly,
        })

    overwaarde_amount = max(Decimal(0), sale_old - existing_total - sale_fee)
    te_financieren = _round_cent(offer + renovation + purchase_fee)
    nieuwe_annuiteit = max(
        Decimal(0),
        te_financieren - own_contrib - overwaarde_amount - existing_total,
    )
    total_debt = existing_total + nieuwe_annuiteit
    ltv_fraction = (
        (total_debt / valuation).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if valuation > 0 else Decimal(0)
    )

    return ScenarioFinancials(
        purchase_fee=purchase_fee,
        sale_fee=_round_cent(sale_fee),
        existing_total=_round_cent(existing_total),
        overwaarde=_round_cent(overwaarde_amount),
        te_financieren=_round_cent(te_financieren),
        nieuwe_annuiteit=_round_cent(nieuwe_annuiteit),
        ltv_fraction=ltv_fraction,
        existing_monthly_total=_round_cent(existing_monthly_total),
        existing_lines=existing_lines,
    )


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
