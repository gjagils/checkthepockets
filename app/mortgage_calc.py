"""Hypotheek-rekenkern: PMT, aflossingstabel, te-financieren, overwaarde, netto-maandlast.

Alle bedragen zijn Decimal (centen). Rentes zijn fracties (0.0375 = 3,75%).
"""
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from app.models import HouseholdFinance, MortgageScenario, MortgageVariant, ScenarioExistingMortgage

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


def effective_rate_pct_today(em) -> Decimal | None:
    """Kies de rente (als percentage, dus 4.45 niet 0.0445) die vandaag geldt
    voor een bestaand leningdeel. Respecteert een eventuele rentesprong via
    ``rate_change_date`` + ``rate_pct_after``.
    """
    import datetime as _dt
    rate_after = getattr(em, "rate_pct_after", None)
    change_date = getattr(em, "rate_change_date", None)
    if rate_after is not None and change_date is not None:
        if _dt.date.today() >= change_date:
            return Decimal(str(rate_after))
    return em.rate_pct if em.rate_pct is not None else None


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
    # Overbruggingshypotheek (alle NULL/0 als geen timing is gezet of verkoop
    # vóór overdracht plaatsvindt — we ondersteunen die omgekeerde situatie nog
    # niet, dan is er geen overbrugging nodig).
    bridge_days: int = 0
    bridge_amount: Decimal = Decimal("0.00")
    bridge_monthly_interest: Decimal = Decimal("0.00")
    bridge_gross_interest_total: Decimal = Decimal("0.00")


def bridge_days_between(
    transfer_date_new, sale_date_old,
) -> int:
    """Aantal dagen tussen overdracht nieuw en verkoop oud.

    Beide datums moeten gezet zijn én sale_date_old moet op of na
    transfer_date_new liggen; anders retourneert 0 (geen overbrugging nodig).
    Banken factureren overbrugging op dagbasis, dus we tellen werkelijke
    kalenderdagen tussen passeer- en verkoopdatum.
    """
    if not transfer_date_new or not sale_date_old:
        return 0
    if sale_date_old < transfer_date_new:
        return 0
    return (sale_date_old - transfer_date_new).days


def bridge_loan_metrics(
    bridge_amount: Decimal,
    bridge_rate_pct: Decimal,  # als fractie, bv. 0.0420
    bridge_days: int,
) -> tuple[Decimal, Decimal]:
    """Maand-referentielast + totale bruto rente-kost over de werkelijke periode.

    Aflossingsvrij. Totale rente = amount × rate / 365 × dagen (banken
    factureren op dagbasis). De maand-referentielast (amount × rate / 12) wordt
    los teruggegeven omdat de UI 'm gebruikt voor de "dubbele maandlast"-KPI.
    """
    amount = Decimal(str(bridge_amount or 0))
    rate = Decimal(str(bridge_rate_pct or 0))
    days = int(bridge_days or 0)
    if amount <= 0 or rate <= 0 or days <= 0:
        return Decimal("0.00"), Decimal("0.00")
    monthly_interest = _round_cent(amount * rate / Decimal(12))
    total_gross = _round_cent(amount * rate / Decimal(365) * Decimal(days))
    return monthly_interest, total_gross


def compute_scenario_financials(scenario, household=None) -> ScenarioFinancials:
    """Bereken alle afgeleide waardes voor een scenario conform LIN-44.

    De scenario-objecten zijn SQLAlchemy-modellen; we lezen alleen simpele
    velden zodat deze functie ook buiten een sessie getest kan worden met
    eenvoudige stubs.

    `household` wordt alleen gebruikt voor `bridge_rate_pct` bij de
    overbruggingshypotheek-berekening. Zonder household (of zonder
    overbruggings-datums op het scenario) blijven alle bridge_*-velden op 0.
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
    existing_total_ltv = Decimal("0")  # som van alleen de hypotheken die
                                        # de bank ziet als onderpand-schuld
    existing_monthly_total = Decimal("0")
    for m in getattr(scenario, "existing_mortgages", []) or []:
        bal = Decimal(str(m.balance_eur or 0))
        existing_total += bal
        # `counts_in_ltv` bestaat pas sinds migratie 051; val terug op True
        # voor oudere stubs/tests die het veld niet zetten.
        in_ltv = bool(getattr(m, "counts_in_ltv", 1))
        if in_ltv:
            existing_total_ltv += bal
        monthly = existing_mortgage_monthly(
            balance=bal,
            mortgage_type=m.mortgage_type or "annuity",
            rate_pct=effective_rate_pct_today(m),
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
            "counts_in_ltv": in_ltv,
        })

    overwaarde_amount = max(Decimal(0), sale_old - existing_total - sale_fee)
    te_financieren = _round_cent(offer + renovation + purchase_fee)
    nieuwe_annuiteit = max(
        Decimal(0),
        te_financieren - own_contrib - overwaarde_amount - existing_total,
    )
    # LTV gebruikt alleen de hypotheken waarvan de bank mee-rekent (zie
    # counts_in_ltv). Privé-leningen zoals een familie-hypotheek tellen dus
    # niet mee voor de loan-to-value die de bank gebruikt.
    total_debt_for_ltv = existing_total_ltv + nieuwe_annuiteit
    ltv_fraction = (
        (total_debt_for_ltv / valuation).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if valuation > 0 else Decimal(0)
    )

    bridge_days = bridge_days_between(
        getattr(scenario, "transfer_date_new", None),
        getattr(scenario, "sale_date_old", None),
    )
    override = getattr(scenario, "bridge_amount_override", None)
    bridge_amount = (
        Decimal(str(override))
        if override is not None and Decimal(str(override)) > 0
        else _round_cent(overwaarde_amount)
    )
    bridge_rate = Decimal(str(getattr(household, "bridge_rate_pct", 0) or 0))
    if bridge_days > 0 and bridge_amount > 0 and bridge_rate > 0:
        bridge_monthly, bridge_total_interest = bridge_loan_metrics(
            bridge_amount, bridge_rate, bridge_days,
        )
    else:
        bridge_amount = Decimal("0.00")
        bridge_monthly = Decimal("0.00")
        bridge_total_interest = Decimal("0.00")

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
        bridge_days=bridge_days,
        bridge_amount=_round_cent(bridge_amount),
        bridge_monthly_interest=_round_cent(bridge_monthly),
        bridge_gross_interest_total=_round_cent(bridge_total_interest),
    )


@dataclass
class ScenarioBudgetRow:
    """Één rij voor de scenario-budget-tabel (LIN-45).

    `scenario_amount` is None wanneer er geen override is (bv. categorie zonder
    `cost_scale_type` en zonder expliciete manual override). Templates tonen
    dan het current-bedrag als placeholder.
    """
    category_id: int
    category_name: str
    current_amount: Decimal
    scenario_amount: Decimal | None
    effective_amount: Decimal
    source: str  # "auto" | "manual" | "none"
    cost_scale_type: str | None


def build_scenario_budget_rows(
    *,
    scenario,
    budgets,             # list[Budget] voor de laatste maand
    overrides_by_cat,    # dict[cat_id -> MortgageScenarioBudget]
    existing_monthly_total: Decimal,
    new_annuity_monthly: Decimal,
) -> tuple[list[ScenarioBudgetRow], Decimal]:
    """Pas factors en hypotheek-som toe op de scenario-budget-rijen.

    Regels:
    - `source == "manual"` op een override → user-waarde wint, geen auto-factor.
    - Category `cost_scale_type == "mortgage"` → effectief bedrag wordt vervangen
      door `existing_monthly_total + new_annuity_monthly` (tenzij manueel gezet).
    - Category `cost_scale_type == "municipal"` → effectief bedrag =
      `current * scenario.municipal_cost_factor` (tenzij manueel).
    - Category `cost_scale_type == "insurance"` → idem met `insurance_cost_factor`.
    - Geen scale-type + geen override → effectief = current (onveranderd).
    """
    municipal_factor = Decimal(str(getattr(scenario, "municipal_cost_factor", "1.50") or "1.50"))
    insurance_factor = Decimal(str(getattr(scenario, "insurance_cost_factor", "1.50") or "1.50"))
    mortgage_total = _round_cent(
        Decimal(str(existing_monthly_total or 0)) + Decimal(str(new_annuity_monthly or 0))
    )

    rows: list[ScenarioBudgetRow] = []
    total = Decimal("0")
    for b in budgets:
        current = Decimal(str(b.amount or 0))
        override = overrides_by_cat.get(b.category_id)
        cat = b.category
        scale_type = getattr(cat, "cost_scale_type", None) if cat else None

        # Handmatig override wint altijd.
        if override is not None and (override.source == "manual"):
            scen_amount: Decimal | None = Decimal(str(override.amount or 0))
            source = "manual"
        elif scale_type == "mortgage":
            scen_amount = mortgage_total
            source = "auto"
        elif scale_type == "municipal":
            scen_amount = _round_cent(current * municipal_factor)
            source = "auto"
        elif scale_type == "insurance":
            scen_amount = _round_cent(current * insurance_factor)
            source = "auto"
        elif override is not None:
            scen_amount = Decimal(str(override.amount or 0))
            source = override.source or "auto"
        else:
            scen_amount = None
            source = "none"

        effective = scen_amount if scen_amount is not None else current
        total += effective

        rows.append(ScenarioBudgetRow(
            category_id=b.category_id,
            category_name=(cat.name if cat else f"#{b.category_id}"),
            current_amount=_round_cent(current),
            scenario_amount=(_round_cent(scen_amount) if scen_amount is not None else None),
            effective_amount=_round_cent(effective),
            source=source,
            cost_scale_type=scale_type,
        ))

    rows.sort(key=lambda r: r.category_name.lower())
    return rows, _round_cent(total)


@dataclass
class ScenarioCoverage:
    """Samenvatting voor de dekkings-kaart (LIN-45)."""
    monthly_total: Decimal
    contributions_total: Decimal
    difference: Decimal
    covered: bool


def compute_scenario_coverage(
    monthly_total: Decimal, contributions: list[Decimal],
) -> ScenarioCoverage:
    total = _round_cent(sum((Decimal(str(c or 0)) for c in contributions), Decimal("0")))
    diff = _round_cent(total - Decimal(str(monthly_total or 0)))
    return ScenarioCoverage(
        monthly_total=_round_cent(Decimal(str(monthly_total or 0))),
        contributions_total=total,
        difference=diff,
        covered=(total >= Decimal(str(monthly_total or 0))),
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


# ── Eigenwoningforfait (2026) ───────────────────────────────────────────

# Drempel waarboven het hoge forfait-tarief geldt. Vanaf 2026 is dit € 1,34 mln
# volgens Belastingdienst-tarieven. Hardcoded omdat de drempel jaarlijks
# wijzigt en losstaat van user-configuratie.
EWF_HIGH_THRESHOLD = Decimal("1340000")
EWF_HIGH_PCT = Decimal("0.0235")


def ewf_amount(
    woz_value: Decimal,
    ewf_pct_low: Decimal = Decimal("0.0035"),
) -> Decimal:
    """Bereken het eigenwoningforfait op basis van de WOZ-waarde.

    * 0,35% (default) tot en met de drempel (€ 1.340.000 in 2026).
    * 2,35% over het deel boven de drempel.
    """
    woz = Decimal(str(woz_value or 0))
    if woz <= 0:
        return Decimal("0.00")
    low = min(woz, EWF_HIGH_THRESHOLD) * Decimal(str(ewf_pct_low))
    high = max(woz - EWF_HIGH_THRESHOLD, Decimal("0")) * EWF_HIGH_PCT
    return _round_cent(low + high)


def hra_refund(
    deductible_interest_yr: Decimal,
    ewf_yr: Decimal,
    tax_rate: Decimal,
    correction_factor: Decimal = Decimal("1.0000"),
) -> Decimal:
    """Werkelijke teruggaaf per jaar.

    Formule: ``max(0, rente_aftrekbaar − EWF) × tarief × correctiefactor``.

    De `correction_factor` corrigeert voor afwijkingen tussen de modelmatige
    teruggaaf en de werkelijke aangifte (o.a. heffingskortingen, afrondingen,
    tariefsaanpassingen). Default 1,0 = geen correctie; kalibreer met
    `werkelijke_teruggaaf / (aftrekbare_rente − EWF) / tarief`.
    """
    saldo = max(Decimal(str(deductible_interest_yr or 0)) - Decimal(str(ewf_yr or 0)), Decimal("0"))
    factor = Decimal(str(correction_factor or "1.0"))
    return _round_cent(saldo * Decimal(str(tax_rate)) * factor)


# ── Bestaande leningdelen en varianten ────────────────────────────────────────


def em_rate_for_date(
    em: "ScenarioExistingMortgage", dt: datetime.date,
) -> Decimal | None:
    """Kies de geldende rente op ``dt`` — post-change of originele rate.

    Returnt None als er helemaal geen rente is gezet op het leningdeel.
    """
    if (
        em.rate_change_date is not None
        and em.rate_pct_after is not None
        and dt >= em.rate_change_date
    ):
        return Decimal(str(em.rate_pct_after)) / Decimal(100)
    if em.rate_pct is None:
        return None
    return Decimal(str(em.rate_pct)) / Decimal(100)


def existing_mortgage_yearly_gross(
    em: "ScenarioExistingMortgage", year_offset: int,
) -> Decimal:
    """Totale bruto betaling (rente + aflossing) in het doeljaar.

    Voor aflossingsvrij: gelijk aan rente (geen aflossing). Voor annuïtair:
    de volledige jaartermijn. Respecteert rate_change_date zoals interest-only
    al doet; voor annuïtair bij een rentesprong mid-year valt 'ie momenteel
    terug op de gemiddelde rente (acceptabele vereenvoudiging, omdat Pim/ABN
    in praktijk aflossingsvrij zijn).
    """
    bal = Decimal(str(em.balance_eur or 0))
    if bal <= 0:
        return Decimal("0")

    today = datetime.date.today()
    year_start = datetime.date(today.year + year_offset, 1, 1)
    year_end = datetime.date(today.year + year_offset, 12, 31)
    mtype = em.mortgage_type or "annuity"

    if mtype == "interest_only":
        if (
            em.rate_change_date is not None
            and em.rate_pct_after is not None
            and year_start <= em.rate_change_date <= year_end
        ):
            pre_rate = em_rate_for_date(em, year_start)
            post_rate = em_rate_for_date(em, em.rate_change_date)
            if pre_rate is None or post_rate is None:
                return Decimal("0")
            months_pre = (em.rate_change_date.month - 1)
            months_post = 12 - months_pre
            return (
                bal * pre_rate * Decimal(months_pre) / Decimal(12)
                + bal * post_rate * Decimal(months_post) / Decimal(12)
            ).quantize(Decimal("0.01"))
        rate = em_rate_for_date(em, year_start)
        if rate is None:
            return Decimal("0")
        return (bal * rate).quantize(Decimal("0.01"))

    # Annuïtair: PMT per maand × 12. Gebruik een schedule met de rente die
    # 1 januari geldt.
    rate = em_rate_for_date(em, year_start)
    if rate is None:
        return Decimal("0")
    months = int(em.months_remaining) if em.months_remaining else 360
    years = max(months // 12, 1)
    pmt_monthly = _calc_annuity_monthly_from_months(
        bal, rate, min(months, years * 12),
    )
    return (pmt_monthly * Decimal(12)).quantize(Decimal("0.01"))


def existing_mortgage_yearly_interest(
    em: "ScenarioExistingMortgage", year_offset: int,
) -> Decimal:
    """Rente die dit leningdeel in ``year_offset`` (0 = huidig jaar) maakt.

    * Aflossingsvrij: ``balance × rate_pct/100`` — constant over de looptijd,
      met een stap als ``rate_change_date`` binnen het jaar valt (dan wordt
      pro-rata verdeeld over pre/post change-datum).
    * Annuïtair: gebruikt een amortization-schedule met de rate die begin van
      het jaar geldt. Rente-sprong mid-year wordt (bewust) genegeerd voor
      annuïtair — in praktijk herbereken je dan de hele resterende schedule.

    Returnt 0 als rate of balance ontbreekt.
    """
    bal = Decimal(str(em.balance_eur or 0))
    if bal <= 0:
        return Decimal("0")

    today = datetime.date.today()
    year_start = datetime.date(today.year + year_offset, 1, 1)
    year_end = datetime.date(today.year + year_offset, 12, 31)

    mtype = em.mortgage_type or "annuity"

    if mtype == "interest_only":
        # Pro-rata per maand rond de rate_change_date.
        if (
            em.rate_change_date is not None
            and em.rate_pct_after is not None
            and year_start <= em.rate_change_date <= year_end
        ):
            pre_rate = em_rate_for_date(em, year_start)
            post_rate = em_rate_for_date(em, em.rate_change_date)
            if pre_rate is None or post_rate is None:
                return Decimal("0")
            months_pre = (em.rate_change_date.month - 1)
            months_post = 12 - months_pre
            return (
                bal * pre_rate * Decimal(months_pre) / Decimal(12)
                + bal * post_rate * Decimal(months_post) / Decimal(12)
            ).quantize(Decimal("0.01"))
        rate = em_rate_for_date(em, year_start)
        if rate is None:
            return Decimal("0")
        return (bal * rate).quantize(Decimal("0.01"))

    # Annuïtair: rate die op 1 januari van het doeljaar geldt.
    rate = em_rate_for_date(em, year_start)
    if rate is None:
        return Decimal("0")
    months = int(em.months_remaining) if em.months_remaining else 360
    years = max(months // 12, 1)
    schedule = list(amortization_schedule(bal, rate, years))
    rows = schedule[year_offset * 12:(year_offset + 1) * 12]
    return sum((r.interest for r in rows), Decimal("0"))


def variant_stats(
    variant: "MortgageVariant",
    ann_principal: Decimal,
    ltv_fraction: Decimal,
    rates,
    household: "HouseholdFinance",
    scenario: "MortgageScenario | None" = None,
):
    """Bereken alle rijen voor deze variant voor de vergelijkingstabel + chart.

    HRA wordt per jaar uitgerekend met:

    * Werkelijke rente uit de aflossingstabel (annuïteit) + rente uit bestaande
      leningdelen die nog HRA-geldig zijn (``hra_end_date``).
    * EWF als percentage × WOZ-waarde (scenario.woz_value of fallback
      scenario.valuation).
    * ``household.hra_correction_factor`` als kalibratie op je echte aangifte.

    Het veld ``annual_refund`` = gemiddelde teruggaaf over de rentevast-periode
    (5/10/20 jaar), omdat de jaar-1-waarde een boven-schatting is.
    """
    tax_rate = Decimal(str(household.tax_rate))
    correction = Decimal(
        str(getattr(household, "hra_correction_factor", "1.0") or "1.0")
    )
    ewf_pct = Decimal(
        str(getattr(household, "ewf_pct", "0.0035") or "0.0035")
    )
    existing_pim = Decimal(str(household.existing_mortgage_pim))
    existing_pim_rate = Decimal(str(household.existing_mortgage_pim_rate))
    existing_io_monthly = Decimal(str(household.existing_mortgage_interest_only_monthly))

    # WOZ: scenario override, fallback = taxatie, fallback = 0.
    woz = Decimal("0")
    if scenario is not None:
        woz = Decimal(str(
            scenario.woz_value
            if scenario.woz_value is not None
            else scenario.valuation or 0
        ))
    ewf_yr = ewf_amount(woz, ewf_pct)

    # Teruggaaf-gebruik per scenario: NULL = volledige teruggaaf → maandlast
    # (oude gedrag); anders dit bedrag per maand naar maandlast, rest spaart.
    refund_usage_setting: Decimal | None = None
    if scenario is not None and scenario.monthly_refund_usage is not None:
        refund_usage_setting = Decimal(str(scenario.monthly_refund_usage))

    override = variant.interest_rate_override
    if override is not None:
        rate = Decimal(str(override))
        rate_source = "handmatig"
    else:
        rate = pick_rate(rates, variant.fixed_years, ltv_fraction)
        rate_source = "uit rente-tabel"

    stats = {
        "variant": variant,
        "fixed_years": variant.fixed_years,
        "rate": rate,
        "rate_source": rate_source,
        "rate_missing": rate is None,
        "annuity_monthly": Decimal("0.00"),
        "pim_monthly": Decimal("0.00"),
        "interest_only_monthly": existing_io_monthly,
        "monthly_refund": Decimal("0.00"),
        "annual_refund": Decimal("0.00"),
        "used_monthly_refund": Decimal("0.00"),
        "annual_savings": Decimal("0.00"),
        "net_monthly": Decimal("0.00"),
        "first_5y_total_cost": Decimal("0.00"),
        "net_monthly_by_year": [],
        # Nieuw: per jaar bestaande-maandlast en gebruikte teruggaaf, zodat
        # het scenario-chart de totale netto hypotheek-last (inclusief ABN-
        # rentesprong + PIM-HRA-einde) kan tonen, én een overschot-lijn.
        "existing_monthly_by_year": [],
        "used_refund_monthly_by_year": [],
        "mortgage_net_by_year": [],
        "ewf_yr": ewf_yr,
    }

    if rate is None:
        return stats

    stats["annuity_monthly"] = pmt(ann_principal, rate, 30)
    stats["pim_monthly"] = (existing_pim * existing_pim_rate / Decimal(12)).quantize(
        Decimal("0.01")
    )

    schedule = (
        list(amortization_schedule(ann_principal, rate, 30))
        if ann_principal > 0 else []
    )

    today = datetime.date.today()
    fixed_years = variant.fixed_years or 5
    refunds_over_fixed: list[Decimal] = []

    for year_offset in range(30):
        yr_start = datetime.date(today.year + year_offset, 1, 1)

        # Nieuwe annuïteit — rente altijd aftrekbaar (30-jr loopt sowieso).
        rows = schedule[year_offset * 12:(year_offset + 1) * 12]
        annuity_int = sum((r.interest for r in rows), Decimal(0)) if rows else Decimal(0)
        annuity_gross = sum((r.payment for r in rows), Decimal(0)) if rows else Decimal(0)

        # Bestaande leningdelen: rente aftrekbaar tot hra_end_date, plus de
        # totale bruto maandlast voor het chart.
        existing_int_deductible = Decimal(0)
        existing_gross_yr = Decimal(0)
        if scenario is not None:
            for em in scenario.existing_mortgages:
                yr_int = existing_mortgage_yearly_interest(em, year_offset)
                yr_gross = existing_mortgage_yearly_gross(em, year_offset)
                existing_gross_yr += yr_gross
                if em.hra_end_date is None or em.hra_end_date > yr_start:
                    existing_int_deductible += yr_int

        total_deductible = annuity_int + existing_int_deductible
        year_refund = hra_refund(
            total_deductible, ewf_yr, tax_rate, correction,
        )

        if year_offset < fixed_years:
            refunds_over_fixed.append(year_refund)

        # Netto maandlast nieuwe annuïteit = bruto − inzet teruggaaf per maand.
        if refund_usage_setting is None:
            year_used = year_refund
        else:
            year_used = min(
                max(refund_usage_setting, Decimal("0")) * Decimal(12), year_refund,
            )
        if rows:
            year_net = (annuity_gross - year_used) / Decimal(12)
            stats["net_monthly_by_year"].append(year_net.quantize(Decimal("0.01")))

        # Per-jaar reeksen voor het chart.
        stats["existing_monthly_by_year"].append(
            (existing_gross_yr / Decimal(12)).quantize(Decimal("0.01"))
        )
        stats["used_refund_monthly_by_year"].append(
            (year_used / Decimal(12)).quantize(Decimal("0.01"))
        )
        mortgage_net_monthly = (
            (annuity_gross + existing_gross_yr - year_used) / Decimal(12)
        )
        stats["mortgage_net_by_year"].append(
            mortgage_net_monthly.quantize(Decimal("0.01"))
        )

    # Vergelijkingstabel-cellen: gemiddelde over rentevast-periode (realistisch,
    # houdt rekening met dalende rente én aflopende HRA van bestaande leningen).
    if refunds_over_fixed:
        avg_annual_refund = (
            sum(refunds_over_fixed, Decimal(0)) / Decimal(len(refunds_over_fixed))
        ).quantize(Decimal("0.01"))
    else:
        avg_annual_refund = Decimal("0.00")

    full_monthly_refund = (avg_annual_refund / Decimal(12)).quantize(Decimal("0.01"))

    if refund_usage_setting is None:
        used_monthly = full_monthly_refund
    else:
        used_monthly = min(
            max(refund_usage_setting, Decimal("0")), full_monthly_refund,
        )

    stats["monthly_refund"] = full_monthly_refund
    stats["used_monthly_refund"] = used_monthly.quantize(Decimal("0.01"))
    stats["annual_refund"] = avg_annual_refund
    stats["annual_savings"] = (
        (full_monthly_refund - used_monthly) * Decimal(12)
    ).quantize(Decimal("0.01"))
    stats["net_monthly"] = (
        stats["annuity_monthly"] - used_monthly
    ).quantize(Decimal("0.01"))

    # Eerste 5 jaar totale kosten uit de net_monthly_by_year reeks.
    if len(stats["net_monthly_by_year"]) >= 5:
        stats["first_5y_total_cost"] = (
            sum(stats["net_monthly_by_year"][:5], Decimal(0)) * Decimal(12)
        ).quantize(Decimal("0.01"))

    return stats


# ── Scenariovergelijking (detailpagina) ───────────────────────────────────────


def bridge_cost_summary(fin: ScenarioFinancials, household) -> tuple[Decimal, Decimal, Decimal]:
    """Eenmalige netto overbruggingskost: ``(bruto rente, HRA-teruggaaf, netto)``.

    Overbruggingsrente is HRA-aftrekbaar (fiscaal box 1, max 2 jaar). Simpele
    benadering: tarief × bruto rente × correctiefactor. EWF trekken we hier
    niet opnieuw af — dat is al verrekend bij de reguliere HRA van de nieuwe
    annuïteit. De netto kost gaat in jaar 1 van het spaarsaldo af.
    """
    tax_rate = Decimal(str(household.tax_rate or 0))
    hra_correction = Decimal(str(
        getattr(household, "hra_correction_factor", "1.0") or "1.0"
    ))
    gross_interest = fin.bridge_gross_interest_total
    hra_refund_amount = (gross_interest * tax_rate * hra_correction).quantize(Decimal("0.01"))
    net_cost = (gross_interest - hra_refund_amount).quantize(Decimal("0.01"))
    return gross_interest, hra_refund_amount, net_cost


def default_variant_summary(default_stats: dict | None, ann_principal: Decimal, household, rates) -> dict:
    """Aflossingstabel en kerncijfers voor de standaardweergave.

    Standaard is de variant met de kortste rentevaste periode. Zonder variant
    of rente valt de weergave terug op lege waarden en de kortste periode uit
    de rentetabel (of 10 jaar).
    """
    if default_stats and default_stats["rate"] is not None:
        rate = default_stats["rate"]
        schedule = list(amortization_schedule(ann_principal, rate, 30))
        # Eerste 5 jaar: teruggaaf op rente boven het eigenwoningforfait.
        first_5y_refund = Decimal(0)
        tax_rate_dec = Decimal(str(household.tax_rate))
        yearly_notional = Decimal(str(household.notional_rent_value))
        for year_offset in range(5):
            year_rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            year_interest = sum((row.interest for row in year_rows), Decimal(0))
            deductible = max(year_interest - yearly_notional, Decimal(0))
            first_5y_refund += deductible * tax_rate_dec
        return {
            "fixed_years": default_stats["fixed_years"],
            "rate": rate,
            "rate_missing": False,
            "schedule": schedule,
            "monthly_payment": schedule[0].payment if schedule else Decimal("0"),
            "net_monthly": default_stats["net_monthly"],
            "first_5y_interest": sum((row.interest for row in schedule[:60]), Decimal(0)),
            "first_5y_refund": first_5y_refund,
        }
    return {
        "fixed_years": default_stats["fixed_years"] if default_stats else min(
            (r.fixed_years for r in rates), default=10,
        ),
        "rate": None,
        "rate_missing": True,
        "schedule": [],
        "monthly_payment": Decimal("0"),
        "net_monthly": Decimal("0"),
        "first_5y_interest": Decimal("0"),
        "first_5y_refund": Decimal("0"),
    }


def mortgage_budget_sum(budget_rows) -> Decimal:
    """Budget in hypotheek-categorieën; die worden vervangen door de echte lasten."""
    return sum(
        (r.effective_amount for r in budget_rows if r.cost_scale_type == "mortgage"),
        Decimal("0"),
    )


def scenario_monthly_total(
    net_monthly_amount: Decimal, existing_monthly_total: Decimal, budget_total: Decimal, budget_rows,
) -> Decimal:
    """Totaal maandlast = nieuwe netto maandlast + bestaande hypotheken + rest-budget."""
    return (
        net_monthly_amount + existing_monthly_total
        + (budget_total - mortgage_budget_sum(budget_rows))
    ).quantize(Decimal("0.01"))


def variant_leftovers(variant_stats_list: list[dict], salary_sum: Decimal, budget_total: Decimal):
    """Wat er per variant overblijft van het salaris: ``(lijst, (stats, rest)-paren)``."""
    leftovers = []
    pairs = []
    for vs in variant_stats_list:
        if vs["rate_missing"]:
            leftovers.append(None)
            pairs.append((vs, None))
        else:
            total_load = vs["net_monthly"] + vs["pim_monthly"] + vs["interest_only_monthly"]
            leftover = (salary_sum - budget_total - total_load).quantize(Decimal("0.01"))
            leftovers.append(leftover)
            pairs.append((vs, leftover))
    return leftovers, pairs


def add_variant_comparison(
    variant_stats_list: list[dict],
    *,
    existing_monthly_total: Decimal,
    household,
    other_budget_total: Decimal,
    contributions_monthly_total: Decimal,
    ann_principal: Decimal,
    rate: Decimal | None,
    bridge_net_cost: Decimal,
) -> None:
    """Vul per variant kosten, inkomsten, resultaat, overschot en spaarsaldo aan.

    Hypotheek-categorieën in het budget zijn al uit ``other_budget_total``
    gehaald; de echte nieuwe annuïteit en bestaande lasten komen ervoor in de
    plaats. Inflatie (alleen op het overige budget) en groei van de bijdragen
    worden per jaar samengesteld toegepast. ``rate`` is de rente van de
    standaardvariant en bepaalt de gemiddelde aflossing over 5 jaar.
    """
    for vs in variant_stats_list:
        if vs["rate_missing"]:
            vs["existing_monthly_total"] = Decimal("0.00")
            vs["other_budget_total"] = other_budget_total
            vs["total_costs"] = Decimal("0.00")
            vs["contributions_total"] = contributions_monthly_total
            vs["total_income"] = Decimal("0.00")
            vs["resultaat"] = Decimal("0.00")
            vs["savings_remainder_monthly"] = Decimal("0.00")
            continue
        existing_monthly = (
            Decimal(str(existing_monthly_total))
            + vs["pim_monthly"]
            + vs["interest_only_monthly"]
        ).quantize(Decimal("0.01"))
        total_costs = (
            vs["annuity_monthly"] + existing_monthly + other_budget_total
        ).quantize(Decimal("0.01"))
        total_income = (
            contributions_monthly_total + vs["used_monthly_refund"]
        ).quantize(Decimal("0.01"))
        vs["existing_monthly_total"] = existing_monthly
        vs["other_budget_total"] = other_budget_total
        vs["total_costs"] = total_costs
        vs["contributions_total"] = contributions_monthly_total
        vs["total_income"] = total_income
        vs["resultaat"] = (total_income - total_costs).quantize(Decimal("0.01"))
        vs["savings_remainder_monthly"] = (
            vs["annual_savings"] / Decimal(12)
        ).quantize(Decimal("0.01"))

        # Per-jaar surplus op de gezamenlijke rekening: inkomsten_yr − kosten_yr,
        # met kosten_yr = nieuwe annuïteit + werkelijke bestaande maandlast dat
        # jaar + rest-budget en inkomsten_yr = bijdragen + gebruikte teruggaaf.
        inflation = Decimal(str(
            getattr(household, "inflation_pct", "0.025") or "0.025"
        ))
        contrib_growth = Decimal(str(
            getattr(household, "contribution_growth_pct", "0.030") or "0.030"
        ))
        one = Decimal("1")
        surplus_by_year: list[Decimal] = []
        for i in range(len(vs["mortgage_net_by_year"])):
            yr_existing = vs["existing_monthly_by_year"][i]
            yr_used = vs["used_refund_monthly_by_year"][i]
            infl_factor = (one + inflation) ** i
            contrib_factor = (one + contrib_growth) ** i
            yr_other_budget = (other_budget_total * infl_factor).quantize(Decimal("0.01"))
            yr_contrib = (contributions_monthly_total * contrib_factor).quantize(Decimal("0.01"))
            yr_costs = vs["annuity_monthly"] + yr_existing + yr_other_budget
            yr_income = yr_contrib + yr_used
            surplus_by_year.append((yr_income - yr_costs).quantize(Decimal("0.01")))
        vs["surplus_by_year"] = surplus_by_year

        # Jaarlijks spaarsaldo op basis van het eerste jaar (zonder inflatie).
        monthly_surplus_yr1 = (
            surplus_by_year[0] if surplus_by_year else Decimal("0")
        )
        savings_income_yr = (
            monthly_surplus_yr1 * Decimal(12)
            + Decimal(str(household.annual_child_benefit or 0))
            + Decimal(str(household.annual_private_loan_refund or 0))
            + Decimal(str(household.annual_extra_primary or 0))
            + Decimal(str(household.annual_extra_secondary or 0))
            + vs["annual_savings"]  # rest teruggaaf (onbenut deel HRA)
        ).quantize(Decimal("0.01"))
        savings_expense_yr = (
            Decimal(str(household.annual_vacation_budget or 0))
            + Decimal(str(household.annual_house_budget or 0))
        ).quantize(Decimal("0.01"))
        vs["savings_monthly_surplus"] = (
            monthly_surplus_yr1 * Decimal(12)
        ).quantize(Decimal("0.01"))
        vs["savings_income_yr"] = savings_income_yr
        vs["savings_expense_yr"] = savings_expense_yr
        # Eenmalige overbruggingskost komt in jaar 1 van het spaarsaldo af,
        # voor elke variant gelijk (overbrugging is scenario-niveau).
        vs["bridge_net_cost"] = bridge_net_cost
        vs["net_annual_savings"] = (
            savings_income_yr - savings_expense_yr - bridge_net_cost
        ).quantize(Decimal("0.01"))

        # Gemiddelde aflossing op de nieuwe annuïteit over de eerste 5 jaar.
        if ann_principal > 0 and rate is not None:
            sched = list(amortization_schedule(ann_principal, rate, 30))[:60]
            total_principal_5y = sum((r.principal for r in sched), Decimal("0"))
            vs["avg_annual_amortization_5y"] = (
                total_principal_5y / Decimal(5)
            ).quantize(Decimal("0.01"))
        else:
            vs["avg_annual_amortization_5y"] = Decimal("0.00")


_VARIANT_COLORS = {
    5: "rgba(54,162,235,1)",    # blauw
    10: "rgba(255,159,64,1)",   # oranje
    20: "rgba(75,192,75,1)",    # groen
}
_DEFAULT_VARIANT_COLOR = "rgba(128,128,128,1)"


def variant_chart_series(variant_stats_list: list[dict]) -> list[dict]:
    """Chart.js-reeksen per variant: netto hypotheeklast (doorgetrokken) en
    overschot op de gezamenlijke rekening (gestippeld met vlak), 30 jaar lang."""

    def _pad(series: list[Decimal]) -> list[float]:
        out = [float(v) for v in series]
        while len(out) < 30:
            out.append(out[-1] if out else 0)
        return out[:30]

    def _soften(rgba: str, alpha: float) -> str:
        # "rgba(54,162,235,1)" → "rgba(54,162,235,0.15)"
        return rgba.rsplit(",", 1)[0] + f",{alpha})"

    chart_series: list[dict] = []
    for vs in variant_stats_list:
        if vs["rate_missing"]:
            continue
        color = _VARIANT_COLORS.get(vs["fixed_years"], _DEFAULT_VARIANT_COLOR)
        label_prefix = f"{vs['fixed_years']}j"
        chart_series.append({
            "label": f"{label_prefix} netto hypotheek-last",
            "data": _pad(vs["mortgage_net_by_year"]),
            "borderColor": color,
            "backgroundColor": "transparent",
            "borderWidth": 2,
            "fill": False,
            "tension": 0.1,
        })
        chart_series.append({
            "label": f"{label_prefix} overschot",
            "data": _pad(vs.get("surplus_by_year", [])),
            "borderColor": color,
            "backgroundColor": _soften(color, 0.15),
            "borderWidth": 1.5,
            "borderDash": [6, 3],
            "fill": "origin",
            "tension": 0.1,
        })
    return chart_series
