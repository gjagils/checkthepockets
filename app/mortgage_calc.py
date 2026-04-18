"""Hypotheek-rekenkern: placeholders voor PMT, te-financieren bedrag en overwaarde.

Concrete implementatie volgt in GJA-28 (calc engine).
"""
from decimal import Decimal


def pmt(principal: Decimal, annual_rate: Decimal, years: int) -> Decimal:
    """Annuïtaire maandlast voor een hypotheekdeel.

    TODO: GJA-28 — implementeer de annuïtaire formule
    ``P = L * (c * (1+c)^n) / ((1+c)^n - 1)`` met c = annual_rate/12,
    n = years*12, en retourneer een Decimal afgerond op centen.
    """
    raise NotImplementedError("pmt() wordt ingevuld in GJA-28")


def to_finance(
    offer: Decimal,
    renovation_cost: Decimal,
    own_contribution: Decimal,
    sale_old_home: Decimal,
    current_home_debt: Decimal,
    purchase_costs_pct: Decimal,
) -> Decimal:
    """Te-financieren bedrag voor een scenario.

    TODO: GJA-28 — bereken: (bod + verbouwing + aankoopkosten) − (eigen inbreng
    + verkoop oude woning − restschuld oude woning). Retourneer een Decimal.
    """
    raise NotImplementedError("to_finance() wordt ingevuld in GJA-28")


def overwaarde(sale_old_home: Decimal, current_home_debt: Decimal, selling_costs_pct: Decimal) -> Decimal:
    """Netto overwaarde van de huidige woning.

    TODO: GJA-28 — bereken: verkoopprijs − verkoopkosten − restschuld.
    """
    raise NotImplementedError("overwaarde() wordt ingevuld in GJA-28")
