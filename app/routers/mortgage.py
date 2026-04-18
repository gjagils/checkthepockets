"""Hypotheek-rekenmodule — alleen toegankelijk voor admins."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import HouseholdFinance, MortgageScenario
from app.template_config import templates

router = APIRouter(prefix="/hypotheek")


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
