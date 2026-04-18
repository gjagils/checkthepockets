"""Hypotheek-rekenmodule — alleen toegankelijk voor admins."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import mortgage_calc
from app.auth import require_login
from app.database import get_db
from app.models import (
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageVariant,
)
from app.template_config import templates

router = APIRouter(prefix="/hypotheek")


# Seed-defaults uit Excel "annuiteit berekenen"-tab (ABN-kolommen E2:H4).
# Ontbrekende 15j-waarden geïnterpoleerd tussen 10j en 20j zodat de seed
# compleet is; admin kan na seed alles handmatig aanpassen.
RATE_SEED_DEFAULTS = [
    (5, Decimal("0.65"), Decimal("0.0339")),
    (5, Decimal("0.85"), Decimal("0.0344")),
    (5, Decimal("0.86"), Decimal("0.0348")),
    (10, Decimal("0.65"), Decimal("0.0373")),
    (10, Decimal("0.85"), Decimal("0.0375")),
    (10, Decimal("0.86"), Decimal("0.0377")),
    (15, Decimal("0.65"), Decimal("0.0395")),
    (15, Decimal("0.85"), Decimal("0.0400")),
    (15, Decimal("0.86"), Decimal("0.0410")),
    (20, Decimal("0.65"), Decimal("0.0416")),
    (20, Decimal("0.85"), Decimal("0.0425")),
    (20, Decimal("0.86"), Decimal("0.0444")),
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
    return RedirectResponse(f"/hypotheek/scenarios/{s.id}?flash=created", status_code=302)


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

    # Variant-keuze: laagste fixed_years uit scenario.variants (GJA-29), anders
    # de laagste rentevast die in de tabel staat.
    chosen_variant = None
    if scenario.variants:
        chosen_variant = min(scenario.variants, key=lambda v: v.fixed_years)
        fixed_years = chosen_variant.fixed_years
    else:
        fixed_years = min((r.fixed_years for r in rates), default=10)

    rate = None
    rate_override = chosen_variant.interest_rate_override if chosen_variant else None
    if rate_override is not None:
        rate = Decimal(str(rate_override))
    else:
        rate = mortgage_calc.pick_rate(rates, fixed_years, ltv_fraction)

    schedule = []
    monthly_payment = Decimal("0")
    net_month = Decimal("0")
    first_5y_interest = Decimal("0")
    first_5y_refund = Decimal("0")
    if rate is not None and ann_principal > 0:
        schedule = list(
            mortgage_calc.amortization_schedule(ann_principal, rate, years=30)
        )
        monthly_payment = schedule[0].payment if schedule else Decimal("0")
        net_month = mortgage_calc.net_monthly(
            monthly_payment,
            rate,
            ann_principal,
            Decimal(str(household.tax_rate)),
            Decimal(str(household.notional_rent_value)),
        )
        # Eerste 5 jaar rente-totaal; renteaftrek-som.
        months_5y = schedule[:60]
        first_5y_interest = sum((row.interest for row in months_5y), Decimal(0))
        yearly_notional = Decimal(str(household.notional_rent_value))
        tax_rate_dec = Decimal(str(household.tax_rate))
        for year_offset in range(5):
            year_rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            year_interest = sum((row.interest for row in year_rows), Decimal(0))
            deductible = max(year_interest - yearly_notional, Decimal(0))
            first_5y_refund += deductible * tax_rate_dec

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
            "rate_missing": rate is None,
            "monthly_payment": monthly_payment,
            "net_monthly": net_month,
            "schedule": schedule,
            "first_5y_interest": first_5y_interest,
            "first_5y_refund": first_5y_refund,
            "flash": request.query_params.get("flash"),
        },
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
