"""Hypotheek-rekenmodule — alleen toegankelijk voor admins."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import mortgage_calc
from app.auth import require_login
from app.database import get_db
from app.models import (
    Budget,
    Category,
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageScenarioBudget,
    MortgageVariant,
)
from app.template_config import templates

router = APIRouter(prefix="/hypotheek")


# Seed-defaults: ABN Annuïteiten Budget hypotheek met huisbankkorting (0,20%
# verwerkt), zoals gepubliceerd op abnamro.nl op 18 april 2026. NHG-kolom en
# variabele rente bewust weggelaten (passen niet in het model).
RATE_SEED_DEFAULTS = [
    (1, Decimal("0.65"), Decimal("0.0380")),
    (1, Decimal("0.85"), Decimal("0.0385")),
    (1, Decimal("0.90"), Decimal("0.0386")),
    (1, Decimal("1.00"), Decimal("0.0389")),
    (2, Decimal("0.65"), Decimal("0.0377")),
    (2, Decimal("0.85"), Decimal("0.0382")),
    (2, Decimal("0.90"), Decimal("0.0383")),
    (2, Decimal("1.00"), Decimal("0.0386")),
    (3, Decimal("0.65"), Decimal("0.0377")),
    (3, Decimal("0.85"), Decimal("0.0382")),
    (3, Decimal("0.90"), Decimal("0.0383")),
    (3, Decimal("1.00"), Decimal("0.0386")),
    (5, Decimal("0.65"), Decimal("0.0375")),
    (5, Decimal("0.85"), Decimal("0.0380")),
    (5, Decimal("0.90"), Decimal("0.0381")),
    (5, Decimal("1.00"), Decimal("0.0383")),
    (6, Decimal("0.65"), Decimal("0.0399")),
    (6, Decimal("0.85"), Decimal("0.0404")),
    (6, Decimal("0.90"), Decimal("0.0405")),
    (6, Decimal("1.00"), Decimal("0.0407")),
    (7, Decimal("0.65"), Decimal("0.0401")),
    (7, Decimal("0.85"), Decimal("0.0406")),
    (7, Decimal("0.90"), Decimal("0.0407")),
    (7, Decimal("1.00"), Decimal("0.0409")),
    (10, Decimal("0.65"), Decimal("0.0404")),
    (10, Decimal("0.85"), Decimal("0.0405")),
    (10, Decimal("0.90"), Decimal("0.0406")),
    (10, Decimal("1.00"), Decimal("0.0407")),
    (12, Decimal("0.65"), Decimal("0.0417")),
    (12, Decimal("0.85"), Decimal("0.0419")),
    (12, Decimal("0.90"), Decimal("0.0424")),
    (12, Decimal("1.00"), Decimal("0.0435")),
    (15, Decimal("0.65"), Decimal("0.0421")),
    (15, Decimal("0.85"), Decimal("0.0432")),
    (15, Decimal("0.90"), Decimal("0.0446")),
    (15, Decimal("1.00"), Decimal("0.0453")),
    (17, Decimal("0.65"), Decimal("0.0421")),
    (17, Decimal("0.85"), Decimal("0.0432")),
    (17, Decimal("0.90"), Decimal("0.0446")),
    (17, Decimal("1.00"), Decimal("0.0453")),
    (20, Decimal("0.65"), Decimal("0.0439")),
    (20, Decimal("0.85"), Decimal("0.0448")),
    (20, Decimal("0.90"), Decimal("0.0456")),
    (20, Decimal("1.00"), Decimal("0.0467")),
    (30, Decimal("0.65"), Decimal("0.0457")),
    (30, Decimal("0.85"), Decimal("0.0464")),
    (30, Decimal("0.90"), Decimal("0.0471")),
    (30, Decimal("1.00"), Decimal("0.0477")),
]


def _require_admin(request: Request, db: Session):
    """Admin-gated: non-admins krijgen 404 (bestaan van feature niet onthullen)."""
    user = require_login(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    return user


def _get_or_create_household(db: Session, user_id: int) -> HouseholdFinance:
    """Seed-defaults bij eerste bezoek (tax 0.3697, forfait 3600, 2.5%/1.5%)."""
    hf = db.query(HouseholdFinance).filter(HouseholdFinance.user_id == user_id).first()
    if hf is None:
        hf = HouseholdFinance(
            user_id=user_id,
            tax_rate=Decimal("0.3697"),
            notional_rent_value=Decimal("3600"),
            purchase_costs_pct=Decimal("0.025"),
            selling_costs_pct=Decimal("0.015"),
        )
        db.add(hf)
        db.commit()
        db.refresh(hf)
    return hf


def _parse_decimal(value: str, default: Decimal = Decimal("0")) -> Decimal:
    """Parse een formveld als Decimal. Accepteert lege string, komma's en punten."""
    if value is None:
        return default
    clean = value.strip().replace(",", ".")
    if not clean:
        return default
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return default


def _parse_percent(value: str, default: Decimal = Decimal("0")) -> Decimal:
    """Parse een percentage-veld: user voert 36,97 in → 0.3697 opslaan."""
    raw = _parse_decimal(value, default * Decimal("100"))
    return (raw / Decimal("100")).quantize(Decimal("0.0001"))


@router.get("")
def mortgage_index(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    scenarios = (
        db.query(MortgageScenario)
        .filter(MortgageScenario.user_id == user.id, MortgageScenario.is_archived == 0)
        .order_by(MortgageScenario.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "mortgage/index.html",
        {"request": request, "user": user, "scenarios": scenarios},
    )


@router.get("/huishouden")
def household_form(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    household = _get_or_create_household(db, user.id)
    saved = request.query_params.get("saved") == "1"
    return templates.TemplateResponse(
        "mortgage/household.html",
        {"request": request, "user": user, "household": household, "saved": saved},
    )


@router.post("/huishouden")
def household_save(
    request: Request,
    salary_primary: str = Form(""),
    salary_primary_name: str = Form(""),
    salary_secondary: str = Form(""),
    salary_secondary_name: str = Form(""),
    existing_mortgage_pim: str = Form(""),
    existing_mortgage_pim_rate: str = Form(""),
    existing_mortgage_pim_refund_rate: str = Form(""),
    existing_mortgage_interest_only: str = Form(""),
    existing_mortgage_interest_only_monthly: str = Form(""),
    current_home_debt: str = Form(""),
    tax_rate: str = Form(""),
    notional_rent_value: str = Form(""),
    purchase_costs_pct: str = Form(""),
    selling_costs_pct: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    hf = _get_or_create_household(db, user.id)

    hf.salary_primary = _parse_decimal(salary_primary)
    hf.salary_primary_name = salary_primary_name.strip() or None
    hf.salary_secondary = _parse_decimal(salary_secondary)
    hf.salary_secondary_name = salary_secondary_name.strip() or None

    hf.existing_mortgage_pim = _parse_decimal(existing_mortgage_pim)
    hf.existing_mortgage_pim_rate = _parse_percent(existing_mortgage_pim_rate)
    hf.existing_mortgage_pim_refund_rate = _parse_percent(existing_mortgage_pim_refund_rate)
    hf.existing_mortgage_interest_only = _parse_decimal(existing_mortgage_interest_only)
    hf.existing_mortgage_interest_only_monthly = _parse_decimal(existing_mortgage_interest_only_monthly)

    hf.current_home_debt = _parse_decimal(current_home_debt)
    hf.tax_rate = _parse_percent(tax_rate, Decimal("0.3697"))
    hf.notional_rent_value = _parse_decimal(notional_rent_value, Decimal("3600"))
    hf.purchase_costs_pct = _parse_percent(purchase_costs_pct, Decimal("0.025"))
    hf.selling_costs_pct = _parse_percent(selling_costs_pct, Decimal("0.015"))

    db.commit()
    return RedirectResponse("/hypotheek/huishouden?saved=1", status_code=302)


# ──────────────────────────────────────────────────────────────────────────────
# Rente-tabel (rentevast × LTV)
# ──────────────────────────────────────────────────────────────────────────────


def _rates_for_user(db: Session, user_id: int) -> list[MortgageRateTable]:
    return (
        db.query(MortgageRateTable)
        .filter(MortgageRateTable.user_id == user_id)
        .order_by(MortgageRateTable.fixed_years.asc(), MortgageRateTable.ltv_max_pct.asc())
        .all()
    )


@router.get("/rentes")
def rates_index(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    rates = _rates_for_user(db, user.id)
    flash = request.query_params.get("flash")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "mortgage/rates.html",
        {
            "request": request,
            "user": user,
            "rates": rates,
            "flash": flash,
            "error": error,
        },
    )


@router.post("/rentes")
def rates_create(
    request: Request,
    fixed_years: str = Form(...),
    ltv_max_pct: str = Form(...),
    interest_rate: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    try:
        years = int(fixed_years)
    except (TypeError, ValueError):
        return RedirectResponse("/hypotheek/rentes?error=invalid", status_code=302)
    if years <= 0:
        return RedirectResponse("/hypotheek/rentes?error=invalid", status_code=302)

    ltv = _parse_percent(ltv_max_pct)
    rate = _parse_percent(interest_rate)
    if ltv <= 0 or rate <= 0:
        return RedirectResponse("/hypotheek/rentes?error=invalid", status_code=302)

    exists = (
        db.query(MortgageRateTable)
        .filter(
            MortgageRateTable.user_id == user.id,
            MortgageRateTable.fixed_years == years,
            MortgageRateTable.ltv_max_pct == ltv,
        )
        .first()
    )
    if exists:
        return RedirectResponse("/hypotheek/rentes?error=duplicate", status_code=302)

    db.add(MortgageRateTable(
        user_id=user.id,
        fixed_years=years,
        ltv_max_pct=ltv,
        interest_rate=rate,
    ))
    db.commit()
    return RedirectResponse("/hypotheek/rentes?flash=added", status_code=302)


@router.post("/rentes/{rate_id}/update")
def rates_update(
    rate_id: int,
    request: Request,
    interest_rate: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    row = (
        db.query(MortgageRateTable)
        .filter(MortgageRateTable.id == rate_id, MortgageRateTable.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    new_rate = _parse_percent(interest_rate)
    if new_rate <= 0:
        return RedirectResponse("/hypotheek/rentes?error=invalid", status_code=302)
    row.interest_rate = new_rate
    db.commit()
    return RedirectResponse("/hypotheek/rentes?flash=updated", status_code=302)


@router.post("/rentes/{rate_id}/delete")
def rates_delete(rate_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    row = (
        db.query(MortgageRateTable)
        .filter(MortgageRateTable.id == rate_id, MortgageRateTable.user_id == user.id)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/hypotheek/rentes?flash=deleted", status_code=302)


@router.post("/rentes/seed")
def rates_seed(request: Request, db: Session = Depends(get_db)):
    """Vul de rente-tabel met zinvolle ABN-defaults — alleen als leeg."""
    user = _require_admin(request, db)
    existing = (
        db.query(MortgageRateTable).filter(MortgageRateTable.user_id == user.id).count()
    )
    if existing > 0:
        return RedirectResponse("/hypotheek/rentes?error=not_empty", status_code=302)

    for years, ltv, rate in RATE_SEED_DEFAULTS:
        db.add(MortgageRateTable(
            user_id=user.id, fixed_years=years, ltv_max_pct=ltv, interest_rate=rate,
        ))
    db.commit()
    return RedirectResponse("/hypotheek/rentes?flash=seeded", status_code=302)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario CRUD
# ──────────────────────────────────────────────────────────────────────────────


def _get_scenario(db: Session, user_id: int, scenario_id: int) -> MortgageScenario:
    row = (
        db.query(MortgageScenario)
        .filter(MortgageScenario.id == scenario_id, MortgageScenario.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Scenario niet gevonden")
    return row


def _apply_scenario_form(
    s: MortgageScenario,
    *,
    name: str,
    valuation: str,
    offer: str,
    renovation_cost: str,
    own_contribution: str,
    sale_old_home: str,
    energy_label: str,
    notes: str,
) -> None:
    s.name = name.strip() or s.name or "Naamloos scenario"
    s.valuation = _parse_decimal(valuation)
    s.offer = _parse_decimal(offer)
    s.renovation_cost = _parse_decimal(renovation_cost)
    s.own_contribution = _parse_decimal(own_contribution)
    s.sale_old_home = _parse_decimal(sale_old_home)
    s.energy_label = (energy_label or "A").strip()[:2].upper() or "A"
    s.notes = notes.strip() or None


@router.get("/scenarios")
def scenarios_list(
    request: Request,
    show_archived: int = 0,
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    q = db.query(MortgageScenario).filter(MortgageScenario.user_id == user.id)
    if not show_archived:
        q = q.filter(MortgageScenario.is_archived == 0)
    scenarios = q.order_by(MortgageScenario.created_at.desc()).all()
    archived_count = (
        db.query(MortgageScenario)
        .filter(MortgageScenario.user_id == user.id, MortgageScenario.is_archived == 1)
        .count()
    )
    return templates.TemplateResponse(
        "mortgage/scenario_list.html",
        {
            "request": request,
            "user": user,
            "scenarios": scenarios,
            "show_archived": bool(show_archived),
            "archived_count": archived_count,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/scenarios/nieuw")
def scenarios_new(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    return templates.TemplateResponse(
        "mortgage/scenario_form.html",
        {"request": request, "user": user, "scenario": None, "mode": "new"},
    )


def _auto_create_variants(db: Session, user_id: int, scenario: MortgageScenario) -> None:
    """Maak 1 variant per distinct rentevast-periode uit de rate-tabel van de user."""
    fixed_years_list = sorted({
        r.fixed_years for r in db.query(MortgageRateTable)
        .filter(MortgageRateTable.user_id == user_id).all()
    })
    for fy in fixed_years_list:
        db.add(MortgageVariant(scenario_id=scenario.id, fixed_years=fy))
    db.commit()


@router.post("/scenarios")
def scenarios_create(
    request: Request,
    name: str = Form(""),
    valuation: str = Form(""),
    offer: str = Form(""),
    renovation_cost: str = Form(""),
    own_contribution: str = Form(""),
    sale_old_home: str = Form(""),
    energy_label: str = Form("A"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    s = MortgageScenario(user_id=user.id)
    _apply_scenario_form(
        s,
        name=name,
        valuation=valuation,
        offer=offer,
        renovation_cost=renovation_cost,
        own_contribution=own_contribution,
        sale_old_home=sale_old_home,
        energy_label=energy_label,
        notes=notes,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    _auto_create_variants(db, user.id, s)
    return RedirectResponse(f"/hypotheek/scenarios/{s.id}?flash=created", status_code=302)


def _variant_stats(
    variant: MortgageVariant,
    ann_principal: Decimal,
    ltv_fraction: Decimal,
    rates,
    household: HouseholdFinance,
):
    """Bereken alle rijen voor deze variant voor de vergelijkingstabel + chart."""
    tax_rate = Decimal(str(household.tax_rate))
    notional = Decimal(str(household.notional_rent_value))
    existing_pim = Decimal(str(household.existing_mortgage_pim))
    existing_pim_rate = Decimal(str(household.existing_mortgage_pim_rate))
    existing_io_monthly = Decimal(str(household.existing_mortgage_interest_only_monthly))

    override = variant.interest_rate_override
    if override is not None:
        rate = Decimal(str(override))
        rate_source = "handmatig"
    else:
        rate = mortgage_calc.pick_rate(rates, variant.fixed_years, ltv_fraction)
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
        "net_monthly": Decimal("0.00"),
        "first_5y_total_cost": Decimal("0.00"),
        "net_monthly_by_year": [],
    }

    if rate is None:
        return stats

    # Nieuw annuïtair deel.
    stats["annuity_monthly"] = mortgage_calc.pmt(ann_principal, rate, 30)
    # Bestaande PIM loopt door: rente * principal / 12 (schatting).
    stats["pim_monthly"] = (existing_pim * existing_pim_rate / Decimal(12)).quantize(
        Decimal("0.01")
    )

    # Netto maandlast jaar 1 volgens calc-engine.
    stats["net_monthly"] = mortgage_calc.net_monthly(
        stats["annuity_monthly"], rate, ann_principal, tax_rate, notional,
    )
    stats["monthly_refund"] = (
        stats["annuity_monthly"] - stats["net_monthly"]
    ).quantize(Decimal("0.01"))

    if ann_principal > 0:
        schedule = list(
            mortgage_calc.amortization_schedule(ann_principal, rate, 30)
        )
        # Eerste 5 jaar totale kosten (som van netto-maandlasten).
        for year_offset in range(30):
            rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            if not rows:
                break
            year_interest = sum((r.interest for r in rows), Decimal(0))
            year_gross = sum((r.payment for r in rows), Decimal(0))
            deductible = max(year_interest - notional, Decimal(0))
            year_refund = deductible * tax_rate
            year_net = (year_gross - year_refund) / Decimal(12)
            stats["net_monthly_by_year"].append(year_net.quantize(Decimal("0.01")))
        # Eerste 5 jaar som (60 maanden, gemiddeld):
        first_60 = schedule[:60]
        gross_60 = sum((r.payment for r in first_60), Decimal(0))
        interest_60 = sum((r.interest for r in first_60), Decimal(0))
        refund_approx = Decimal(0)
        for year_offset in range(5):
            rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            year_int = sum((r.interest for r in rows), Decimal(0))
            refund_approx += max(year_int - notional, Decimal(0)) * tax_rate
        stats["first_5y_total_cost"] = (gross_60 - refund_approx).quantize(
            Decimal("0.01")
        )

    return stats


def _budget_rows_for_scenario(
    db: Session, user_id: int, scenario_id: int,
):
    """Aggregatie: recent 'current' budget per categorie + scenario-override.

    Returned: list van dicts met category, current_amount (uit Budget), scenario_amount
    (uit MortgageScenarioBudget override), effective_amount (override of current),
    en het totaal.
    """
    most_recent = (
        db.query(Budget.year, Budget.month)
        .filter(Budget.user_id == user_id)
        .order_by(Budget.year.desc(), Budget.month.desc())
        .first()
    )
    if not most_recent:
        return [], Decimal(0), None, None

    year, month = most_recent.year, most_recent.month
    budgets = (
        db.query(Budget)
        .filter(
            Budget.user_id == user_id,
            Budget.year == year,
            Budget.month == month,
        )
        .all()
    )
    overrides = {
        b.category_id: Decimal(str(b.amount))
        for b in db.query(MortgageScenarioBudget)
        .filter(MortgageScenarioBudget.scenario_id == scenario_id).all()
    }

    rows = []
    total = Decimal(0)
    for b in budgets:
        current = Decimal(str(b.amount))
        scen_amount = overrides.get(b.category_id)
        effective = scen_amount if scen_amount is not None else current
        rows.append({
            "category": b.category,
            "category_id": b.category_id,
            "current_amount": current,
            "scenario_amount": scen_amount,
            "effective_amount": effective,
        })
        total += effective
    rows.sort(key=lambda r: (r["category"].name.lower() if r["category"] else ""))
    return rows, total, year, month


@router.get("/scenarios/{scenario_id}")
def scenarios_detail(
    scenario_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    household = _get_or_create_household(db, user.id)
    rates = _rates_for_user(db, user.id)

    to_fin = mortgage_calc.to_finance(
        Decimal(str(scenario.offer)),
        Decimal(str(scenario.renovation_cost)),
        Decimal(str(scenario.own_contribution)),
        Decimal(str(household.purchase_costs_pct)),
    )
    ow = mortgage_calc.overwaarde(
        Decimal(str(scenario.sale_old_home)),
        Decimal(str(household.current_home_debt)),
        Decimal(str(household.selling_costs_pct)),
    )
    ann_principal = mortgage_calc.annuity_principal(
        to_fin,
        Decimal(str(household.existing_mortgage_pim)),
        Decimal(str(household.existing_mortgage_interest_only)),
    )
    ltv_fraction = mortgage_calc.ltv(
        to_fin, Decimal(str(scenario.valuation)),
    )

    # Bereken per variant de vergelijkingsdata.
    variants_sorted = sorted(scenario.variants, key=lambda v: v.fixed_years)
    variant_stats = [
        _variant_stats(v, ann_principal, ltv_fraction, rates, household)
        for v in variants_sorted
    ]

    # Default weergave: laagste-rentevast variant voor aflossingstabel (zoals
    # GJA-28). Als geen variants, fallback naar rate-tabel direct.
    default_stats = variant_stats[0] if variant_stats else None
    if default_stats and default_stats["rate"] is not None:
        fixed_years = default_stats["fixed_years"]
        rate = default_stats["rate"]
        rate_missing = False
        schedule = list(
            mortgage_calc.amortization_schedule(ann_principal, rate, 30)
        )
        monthly_payment = schedule[0].payment if schedule else Decimal("0")
        net_month = default_stats["net_monthly"]
        first_5y_interest = sum(
            (row.interest for row in schedule[:60]), Decimal(0),
        )
        first_5y_refund = default_stats["first_5y_total_cost"]  # niet direct refund, maar placeholder
        # eigenlijke refund som:
        first_5y_refund = Decimal(0)
        tax_rate_dec = Decimal(str(household.tax_rate))
        yearly_notional = Decimal(str(household.notional_rent_value))
        for year_offset in range(5):
            year_rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            year_interest = sum((row.interest for row in year_rows), Decimal(0))
            deductible = max(year_interest - yearly_notional, Decimal(0))
            first_5y_refund += deductible * tax_rate_dec
    else:
        # Fallback: geen variant of geen rate gevonden.
        fixed_years = default_stats["fixed_years"] if default_stats else min(
            (r.fixed_years for r in rates), default=10,
        )
        rate = None
        rate_missing = True
        schedule = []
        monthly_payment = Decimal("0")
        net_month = Decimal("0")
        first_5y_interest = Decimal("0")
        first_5y_refund = Decimal("0")

    # Budget-impact.
    budget_rows, budget_total, budget_year, budget_month = _budget_rows_for_scenario(
        db, user.id, scenario.id,
    )
    salary_sum = (
        Decimal(str(household.salary_primary)) + Decimal(str(household.salary_secondary))
    )
    variant_leftover = []
    variant_leftover_pairs = []  # tuples (stats, leftover) voor gemakkelijke iteratie
    for vs in variant_stats:
        if vs["rate_missing"]:
            variant_leftover.append(None)
            variant_leftover_pairs.append((vs, None))
        else:
            total_load = vs["net_monthly"] + vs["pim_monthly"] + vs["interest_only_monthly"]
            leftover = (salary_sum - budget_total - total_load).quantize(Decimal("0.01"))
            variant_leftover.append(leftover)
            variant_leftover_pairs.append((vs, leftover))

    available_fixed_years = sorted({r.fixed_years for r in rates}) or [5, 10, 15, 20, 30]
    missing_fixed_years = [
        fy for fy in available_fixed_years
        if fy not in {v.fixed_years for v in variants_sorted}
    ]

    # Chart.js data: max reeksen uitlijnen op 30 jaar.
    chart_labels = list(range(1, 31))
    chart_series = []
    for vs in variant_stats:
        if vs["rate_missing"]:
            continue
        series_data = [float(v) for v in vs["net_monthly_by_year"]]
        # zeropad tot 30 lengte als korter.
        while len(series_data) < 30:
            series_data.append(series_data[-1] if series_data else 0)
        chart_series.append({
            "label": f"{vs['fixed_years']}j rentevast",
            "data": series_data[:30],
        })

    return templates.TemplateResponse(
        "mortgage/scenario_detail.html",
        {
            "request": request,
            "user": user,
            "scenario": scenario,
            "household": household,
            "to_finance": to_fin,
            "overwaarde": ow,
            "annuity_principal": ann_principal,
            "ltv_fraction": ltv_fraction,
            "fixed_years": fixed_years,
            "rate": rate,
            "rate_missing": rate_missing,
            "monthly_payment": monthly_payment,
            "net_monthly": net_month,
            "schedule": schedule,
            "first_5y_interest": first_5y_interest,
            "first_5y_refund": first_5y_refund,
            "variant_stats": variant_stats,
            "missing_fixed_years": missing_fixed_years,
            "available_fixed_years": available_fixed_years,
            "budget_rows": budget_rows,
            "budget_total": budget_total,
            "budget_year": budget_year,
            "budget_month": budget_month,
            "salary_sum": salary_sum,
            "variant_leftover": variant_leftover,
            "variant_leftover_pairs": variant_leftover_pairs,
            "chart_labels": chart_labels,
            "chart_series": chart_series,
            "flash": request.query_params.get("flash"),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Variants CRUD
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/scenarios/{scenario_id}/variants")
def variants_add(
    scenario_id: int,
    request: Request,
    fixed_years: str = Form(...),
    interest_rate_override: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    try:
        years = int(fixed_years)
    except (TypeError, ValueError):
        return RedirectResponse(
            f"/hypotheek/scenarios/{scenario.id}?flash=variant_invalid",
            status_code=302,
        )
    if years <= 0:
        return RedirectResponse(
            f"/hypotheek/scenarios/{scenario.id}?flash=variant_invalid",
            status_code=302,
        )

    existing = db.query(MortgageVariant).filter(
        MortgageVariant.scenario_id == scenario.id,
        MortgageVariant.fixed_years == years,
    ).first()
    if existing:
        return RedirectResponse(
            f"/hypotheek/scenarios/{scenario.id}?flash=variant_duplicate",
            status_code=302,
        )

    override_value = None
    if interest_rate_override.strip():
        parsed = _parse_percent(interest_rate_override)
        if parsed > 0:
            override_value = parsed

    db.add(MortgageVariant(
        scenario_id=scenario.id,
        fixed_years=years,
        interest_rate_override=override_value,
    ))
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}?flash=variant_added", status_code=302,
    )


@router.post("/scenarios/{scenario_id}/variants/{variant_id}/delete")
def variants_delete(
    scenario_id: int, variant_id: int,
    request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    variant = db.query(MortgageVariant).filter(
        MortgageVariant.id == variant_id,
        MortgageVariant.scenario_id == scenario.id,
    ).first()
    if variant:
        db.delete(variant)
        db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}?flash=variant_deleted", status_code=302,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Scenario budget-overrides
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/scenarios/{scenario_id}/budgets")
def scenario_budget_upsert(
    scenario_id: int,
    request: Request,
    category_id: str = Form(...),
    amount: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    try:
        cat_id = int(category_id)
    except (TypeError, ValueError):
        return RedirectResponse(
            f"/hypotheek/scenarios/{scenario.id}?flash=budget_invalid",
            status_code=302,
        )
    # Alleen eigen categorieën mogen overschreven worden.
    cat = db.query(Category).filter(
        Category.id == cat_id, Category.user_id == user.id,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categorie niet gevonden")

    value = _parse_decimal(amount)
    existing = db.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == scenario.id,
        MortgageScenarioBudget.category_id == cat_id,
    ).first()
    if existing:
        existing.amount = value
    else:
        db.add(MortgageScenarioBudget(
            scenario_id=scenario.id, category_id=cat_id, amount=value,
        ))
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}?flash=budget_saved", status_code=302,
    )


@router.post("/scenarios/{scenario_id}/budgets/reset")
def scenario_budget_reset(
    scenario_id: int,
    request: Request,
    category_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Verwijder één override → categorie valt terug op user's standaard-budget."""
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    try:
        cat_id = int(category_id)
    except (TypeError, ValueError):
        return RedirectResponse(
            f"/hypotheek/scenarios/{scenario.id}?flash=budget_invalid",
            status_code=302,
        )
    existing = db.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == scenario.id,
        MortgageScenarioBudget.category_id == cat_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}?flash=budget_reset", status_code=302,
    )


@router.get("/scenarios/{scenario_id}/edit")
def scenarios_edit_form(
    scenario_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    return templates.TemplateResponse(
        "mortgage/scenario_form.html",
        {"request": request, "user": user, "scenario": scenario, "mode": "edit"},
    )


@router.post("/scenarios/{scenario_id}/edit")
def scenarios_edit(
    scenario_id: int,
    request: Request,
    name: str = Form(""),
    valuation: str = Form(""),
    offer: str = Form(""),
    renovation_cost: str = Form(""),
    own_contribution: str = Form(""),
    sale_old_home: str = Form(""),
    energy_label: str = Form("A"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    _apply_scenario_form(
        scenario,
        name=name,
        valuation=valuation,
        offer=offer,
        renovation_cost=renovation_cost,
        own_contribution=own_contribution,
        sale_old_home=sale_old_home,
        energy_label=energy_label,
        notes=notes,
    )
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}?flash=updated", status_code=302,
    )


@router.post("/scenarios/{scenario_id}/delete")
def scenarios_archive(
    scenario_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    scenario.is_archived = 1
    db.commit()
    return RedirectResponse("/hypotheek/scenarios?flash=archived", status_code=302)


@router.post("/scenarios/{scenario_id}/unarchive")
def scenarios_unarchive(
    scenario_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    scenario.is_archived = 0
    db.commit()
    return RedirectResponse(
        "/hypotheek/scenarios?show_archived=1&flash=unarchived", status_code=302,
    )
