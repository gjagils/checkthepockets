"""Hypotheek-rekenmodule — alleen toegankelijk voor admins."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import HouseholdFinance, MortgageRateTable, MortgageScenario
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
