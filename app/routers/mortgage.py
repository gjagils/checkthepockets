"""Hypotheek-rekenmodule — alleen toegankelijk voor admins."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import mortgage_calc
from app.auth import require_login
from app.database import get_db
from app.funda_parser import FundaParseError, fetch_funda, is_funda_url
from app.move_parser import MoveParseError, fetch_move, is_move_url
from app.models import (
    Budget,
    Category,
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageScenarioBudget,
    MortgageVariant,
    Person,
    ScenarioExistingMortgage,
    ScenarioPersonContribution,
)
from app.mortgage_rate_ocr import extract_rate_text
from app.mortgage_rate_parser import (
    ParsedRate,
    compare_with_existing,
    parse_bulk_rates,
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
    bulk_new = request.query_params.get("new")
    bulk_upd = request.query_params.get("upd")
    return templates.TemplateResponse(
        "mortgage/rates.html",
        {
            "request": request,
            "user": user,
            "rates": rates,
            "flash": flash,
            "error": error,
            "bulk_new_count": int(bulk_new) if bulk_new and bulk_new.isdigit() else 0,
            "bulk_updated_count": int(bulk_upd) if bulk_upd and bulk_upd.isdigit() else 0,
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


@router.post("/rentes/bulk/preview")
def rates_bulk_preview(
    request: Request,
    raw_text: str = Form(""),
    db: Session = Depends(get_db),
):
    """Parse paste-input en render een voorvertoning — importeert nog niets."""
    user = _require_admin(request, db)
    parse_result = parse_bulk_rates(raw_text)
    existing = _rates_for_user(db, user.id)
    new_rows, update_rows = compare_with_existing(parse_result.rows, existing)
    return templates.TemplateResponse(
        "mortgage/rates.html",
        {
            "request": request,
            "user": user,
            "rates": existing,
            "flash": None,
            "error": None,
            "bulk_raw_text": raw_text,
            "bulk_parsed": parse_result,
            "bulk_new_rows": new_rows,
            "bulk_update_rows": update_rows,
            "bulk_mode": "preview",
        },
    )


@router.post("/rentes/bulk/screenshot")
async def rates_bulk_screenshot(
    request: Request,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Accepteer een screenshot, haal er tab-tekst uit via Claude vision en
    render dezelfde preview als de paste-flow. De gebruiker kan de tekst
    zien/corrigeren in de textarea vóór definitieve import."""
    user = _require_admin(request, db)

    existing = _rates_for_user(db, user.id)

    image_bytes = await image.read()
    media_type = image.content_type or ""
    ocr = extract_rate_text(image_bytes, media_type)

    if not ocr.ok:
        return templates.TemplateResponse(
            "mortgage/rates.html",
            {
                "request": request,
                "user": user,
                "rates": existing,
                "flash": None,
                "error": None,
                "bulk_raw_text": "",
                "bulk_parsed": None,
                "bulk_new_rows": [],
                "bulk_update_rows": [],
                "bulk_mode": None,
                "bulk_error": ocr.error,
            },
            status_code=400,
        )

    parse_result = parse_bulk_rates(ocr.text)
    new_rows, update_rows = compare_with_existing(parse_result.rows, existing)
    return templates.TemplateResponse(
        "mortgage/rates.html",
        {
            "request": request,
            "user": user,
            "rates": existing,
            "flash": "screenshot_parsed",
            "error": None,
            "bulk_raw_text": ocr.text,
            "bulk_parsed": parse_result,
            "bulk_new_rows": new_rows,
            "bulk_update_rows": update_rows,
            "bulk_mode": "preview",
        },
    )


@router.post("/rentes/bulk/import")
def rates_bulk_import(
    request: Request,
    raw_text: str = Form(""),
    db: Session = Depends(get_db),
):
    """Schrijf de parsed rijen weg — upsert op (fixed_years, ltv_max_pct)."""
    user = _require_admin(request, db)
    parse_result = parse_bulk_rates(raw_text)
    if parse_result.has_errors or not parse_result.rows:
        existing = _rates_for_user(db, user.id)
        new_rows, update_rows = compare_with_existing(parse_result.rows, existing)
        return templates.TemplateResponse(
            "mortgage/rates.html",
            {
                "request": request,
                "user": user,
                "rates": existing,
                "flash": None,
                "error": None,
                "bulk_raw_text": raw_text,
                "bulk_parsed": parse_result,
                "bulk_new_rows": new_rows,
                "bulk_update_rows": update_rows,
                "bulk_mode": "preview",
                "bulk_error": (
                    "Import geannuleerd: los eerst de foutmeldingen op."
                    if parse_result.has_errors
                    else "Niets te importeren."
                ),
            },
            status_code=400,
        )

    existing = {
        (r.fixed_years, Decimal(str(r.ltv_max_pct))): r
        for r in _rates_for_user(db, user.id)
    }
    new_count = 0
    updated_count = 0
    for row in parse_result.rows:
        key = (row.fixed_years, row.ltv_max_pct)
        current = existing.get(key)
        if current:
            if Decimal(str(current.interest_rate)) != row.interest_rate:
                current.interest_rate = row.interest_rate
                updated_count += 1
        else:
            db.add(MortgageRateTable(
                user_id=user.id,
                fixed_years=row.fixed_years,
                ltv_max_pct=row.ltv_max_pct,
                interest_rate=row.interest_rate,
            ))
            new_count += 1
    db.commit()
    return RedirectResponse(
        f"/hypotheek/rentes?flash=bulk_imported&new={new_count}&upd={updated_count}",
        status_code=302,
    )


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
    funda_url: str = "",
    photo_url: str = "",
    purchase_fee_pct: str = "",
    sale_fee_pct: str = "",
    municipal_cost_factor: str = "",
    insurance_cost_factor: str = "",
    monthly_refund_usage: str = "",
) -> None:
    s.name = name.strip() or s.name or "Naamloos scenario"
    s.valuation = _parse_decimal(valuation)
    s.offer = _parse_decimal(offer)
    s.renovation_cost = _parse_decimal(renovation_cost)
    s.own_contribution = _parse_decimal(own_contribution)
    s.sale_old_home = _parse_decimal(sale_old_home)
    s.energy_label = (energy_label or "A").strip()[:2].upper() or "A"
    s.notes = notes.strip() or None
    s.funda_url = (funda_url or "").strip()[:500] or None
    s.photo_url = (photo_url or "").strip()[:500] or None
    # LIN-44: aan/verkoopkosten als percentage; leeg → default.
    if purchase_fee_pct.strip():
        s.purchase_fee_pct = _parse_decimal(purchase_fee_pct, default=Decimal("2.5"))
    elif s.purchase_fee_pct is None:
        s.purchase_fee_pct = Decimal("2.5")
    if sale_fee_pct.strip():
        s.sale_fee_pct = _parse_decimal(sale_fee_pct, default=Decimal("1.5"))
    elif s.sale_fee_pct is None:
        s.sale_fee_pct = Decimal("1.5")
    # LIN-45: factoren; leeg → default 1.5.
    if municipal_cost_factor.strip():
        s.municipal_cost_factor = _parse_decimal(
            municipal_cost_factor, default=Decimal("1.5")
        )
    elif s.municipal_cost_factor is None:
        s.municipal_cost_factor = Decimal("1.5")
    if insurance_cost_factor.strip():
        s.insurance_cost_factor = _parse_decimal(
            insurance_cost_factor, default=Decimal("1.5")
        )
    elif s.insurance_cost_factor is None:
        s.insurance_cost_factor = Decimal("1.5")
    # Teruggaaf-gebruik: leeg → NULL (volledige teruggaaf → maandlast, geen
    # spaarbedrag). Waarde ≥ 0 → dat deel naar maandlast, rest spaart.
    if monthly_refund_usage.strip():
        s.monthly_refund_usage = _parse_decimal(
            monthly_refund_usage, default=Decimal("0")
        )
    else:
        s.monthly_refund_usage = None


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


@router.post("/scenarios/funda-lookup")
def scenarios_funda_lookup(
    request: Request,
    url: str = Form(""),
    db: Session = Depends(get_db),
):
    """Parse een Funda- óf Move.nl-URL en geef de scenario-velden terug als JSON.

    De front-end gebruikt dit om het formulier vooraf in te vullen. Route wordt
    bepaald op basis van de host (funda.nl → Funda-parser, move.nl → Move-parser).
    Bij fouten retourneren we een 4xx met een NL-leesbare boodschap.
    """
    _require_admin(request, db)
    url = (url or "").strip()
    try:
        if is_move_url(url):
            parsed = fetch_move(url)
        elif is_funda_url(url):
            parsed = fetch_funda(url)
        else:
            return JSONResponse(
                {"error": "Alleen funda.nl- of move.nl-links worden ondersteund."},
                status_code=400,
            )
    except (FundaParseError, MoveParseError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(parsed)


DEFAULT_VARIANT_FIXED_YEARS = (5, 10, 20)


def _auto_create_variants(db: Session, user_id: int, scenario: MortgageScenario) -> None:
    """Maak standaard-varianten voor 5, 10 en 20 jaar rentevast (idempotent)."""
    existing = {v.fixed_years for v in scenario.variants}
    added = False
    for fy in DEFAULT_VARIANT_FIXED_YEARS:
        if fy in existing:
            continue
        db.add(MortgageVariant(scenario_id=scenario.id, fixed_years=fy))
        added = True
    if added:
        db.commit()
        db.refresh(scenario)


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
    funda_url: str = Form(""),
    photo_url: str = Form(""),
    purchase_fee_pct: str = Form(""),
    sale_fee_pct: str = Form(""),
    municipal_cost_factor: str = Form(""),
    insurance_cost_factor: str = Form(""),
    monthly_refund_usage: str = Form(""),
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
        funda_url=funda_url,
        photo_url=photo_url,
        purchase_fee_pct=purchase_fee_pct,
        sale_fee_pct=sale_fee_pct,
        municipal_cost_factor=municipal_cost_factor,
        insurance_cost_factor=insurance_cost_factor,
        monthly_refund_usage=monthly_refund_usage,
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
    scenario: MortgageScenario | None = None,
):
    """Bereken alle rijen voor deze variant voor de vergelijkingstabel + chart."""
    tax_rate = Decimal(str(household.tax_rate))
    notional = Decimal(str(household.notional_rent_value))
    existing_pim = Decimal(str(household.existing_mortgage_pim))
    existing_pim_rate = Decimal(str(household.existing_mortgage_pim_rate))
    existing_io_monthly = Decimal(str(household.existing_mortgage_interest_only_monthly))

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
        "annual_refund": Decimal("0.00"),
        "used_monthly_refund": Decimal("0.00"),
        "annual_savings": Decimal("0.00"),
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

    # Netto maandlast jaar 1 volgens calc-engine (volledige teruggaaf verrekend).
    base_net_monthly = mortgage_calc.net_monthly(
        stats["annuity_monthly"], rate, ann_principal, tax_rate, notional,
    )
    full_monthly_refund = (
        stats["annuity_monthly"] - base_net_monthly
    ).quantize(Decimal("0.01"))

    if refund_usage_setting is None:
        # Oude gedrag: alles naar maandlast.
        used_monthly = full_monthly_refund
    else:
        # User bepaalt bedrag; cap op wat er daadwerkelijk terug komt
        # (je kunt niet méér inzetten dan je krijgt).
        used_monthly = min(
            max(refund_usage_setting, Decimal("0")), full_monthly_refund,
        )

    stats["monthly_refund"] = full_monthly_refund
    stats["used_monthly_refund"] = used_monthly.quantize(Decimal("0.01"))
    stats["annual_refund"] = (full_monthly_refund * Decimal(12)).quantize(Decimal("0.01"))
    stats["annual_savings"] = (
        (full_monthly_refund - used_monthly) * Decimal(12)
    ).quantize(Decimal("0.01"))
    stats["net_monthly"] = (
        stats["annuity_monthly"] - used_monthly
    ).quantize(Decimal("0.01"))

    if ann_principal > 0:
        schedule = list(
            mortgage_calc.amortization_schedule(ann_principal, rate, 30)
        )
        # Netto-maandlast per jaar: teruggaaf-gebruik is een constant bedrag
        # (user-setting) of volledig (oude gedrag). Rest = spaarbedrag (niet in
        # deze reeks zichtbaar, alleen in stats["annual_savings"]).
        for year_offset in range(30):
            rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            if not rows:
                break
            year_interest = sum((r.interest for r in rows), Decimal(0))
            year_gross = sum((r.payment for r in rows), Decimal(0))
            deductible = max(year_interest - notional, Decimal(0))
            year_refund = deductible * tax_rate
            if refund_usage_setting is None:
                year_used = year_refund
            else:
                year_used = min(
                    max(refund_usage_setting, Decimal("0")) * Decimal(12),
                    year_refund,
                )
            year_net = (year_gross - year_used) / Decimal(12)
            stats["net_monthly_by_year"].append(year_net.quantize(Decimal("0.01")))
        # Eerste 5 jaar totale kosten (bruto minus gebruikte teruggaaf).
        first_60 = schedule[:60]
        gross_60 = sum((r.payment for r in first_60), Decimal(0))
        used_total = Decimal(0)
        for year_offset in range(5):
            rows = schedule[year_offset * 12:(year_offset + 1) * 12]
            year_int = sum((r.interest for r in rows), Decimal(0))
            year_refund = max(year_int - notional, Decimal(0)) * tax_rate
            if refund_usage_setting is None:
                used_total += year_refund
            else:
                used_total += min(
                    max(refund_usage_setting, Decimal("0")) * Decimal(12),
                    year_refund,
                )
        stats["first_5y_total_cost"] = (gross_60 - used_total).quantize(
            Decimal("0.01")
        )

    return stats


def _budget_rows_for_scenario(
    db: Session,
    user_id: int,
    scenario: MortgageScenario,
    *,
    existing_monthly_total: Decimal,
    new_annuity_monthly: Decimal,
):
    """Bouw scenario-budget-rijen via `mortgage_calc.build_scenario_budget_rows`.

    Returnt `(rows, total, year, month)` waarbij `rows` nu een lijst van
    `ScenarioBudgetRow`-dataclasses is — het template leest attributes via
    dot-notatie.
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
    # Alleen uitgave-categorieën meenemen in de scenario-budget-vergelijking.
    # Inkomen-categorieën (bv. "Gerd-Jan/Nelleke" salaris) horen niet in het
    # maandbudget-overzicht — dat wordt op de salary-kant al verrekend als
    # huishouden-inkomen in de leftover-berekening.
    budgets = (
        db.query(Budget)
        .join(Category, Category.id == Budget.category_id)
        .filter(
            Budget.user_id == user_id,
            Budget.year == year,
            Budget.month == month,
            Category.is_income == 0,
        )
        .all()
    )
    overrides = {
        b.category_id: b
        for b in db.query(MortgageScenarioBudget)
        .filter(MortgageScenarioBudget.scenario_id == scenario.id).all()
    }
    rows, total = mortgage_calc.build_scenario_budget_rows(
        scenario=scenario,
        budgets=budgets,
        overrides_by_cat=overrides,
        existing_monthly_total=existing_monthly_total,
        new_annuity_monthly=new_annuity_monthly,
    )
    return rows, total, year, month


@router.get("/scenarios/{scenario_id}")
def scenarios_detail(
    scenario_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    if not scenario.variants:
        _auto_create_variants(db, user.id, scenario)
    household = _get_or_create_household(db, user.id)
    rates = _rates_for_user(db, user.id)

    # LIN-44: één helper berekent alle afgeleide bedragen uit het scenario zelf
    # (incl. bestaande hypotheken en per-scenario aan/verkoopkosten).
    fin = mortgage_calc.compute_scenario_financials(scenario)
    to_fin = fin.te_financieren
    ow = fin.overwaarde
    ann_principal = fin.nieuwe_annuiteit
    ltv_fraction = fin.ltv_fraction

    # Bereken per variant de vergelijkingsdata.
    variants_sorted = sorted(scenario.variants, key=lambda v: v.fixed_years)
    variant_stats = [
        _variant_stats(v, ann_principal, ltv_fraction, rates, household, scenario)
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

    # Budget-impact. LIN-45: factor-engine + hypotheek-som gebruikt de monthly-
    # last van de default variant (laagste rentevast). Fallback op 0 bij geen rate.
    new_annuity_monthly = monthly_payment if not rate_missing else Decimal("0")
    budget_rows, budget_total, budget_year, budget_month = _budget_rows_for_scenario(
        db, user.id, scenario,
        existing_monthly_total=fin.existing_monthly_total,
        new_annuity_monthly=new_annuity_monthly,
    )

    # LIN-45: person contributions + coverage.
    persons = (
        db.query(Person)
        .filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    contributions_by_person_id = {
        c.person_id: c for c in db.query(ScenarioPersonContribution)
        .filter(ScenarioPersonContribution.scenario_id == scenario.id)
        .all()
    }
    contribution_rows = []
    total_contrib = Decimal("0")
    for p in persons:
        c = contributions_by_person_id.get(p.id)
        amount = Decimal(str(c.monthly_contribution_eur)) if c else Decimal("0")
        contribution_rows.append({
            "person": p,
            "amount": amount,
        })
        total_contrib += amount
    # Totaal maandlast = nieuwe net-monthly + bestaande hypotheken + rest-budget
    scenario_monthly_total = (
        net_month + fin.existing_monthly_total + (budget_total - (
            # Mortgage-categorieën staan al in budget_total; voorkom dubbeltelling
            sum(
                (r.effective_amount for r in budget_rows
                 if r.cost_scale_type == "mortgage"),
                Decimal("0"),
            )
        ))
    ).quantize(Decimal("0.01"))
    coverage = mortgage_calc.compute_scenario_coverage(
        scenario_monthly_total, [r["amount"] for r in contribution_rows],
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
            "fin": fin,  # LIN-44: alle afgeleide waardes gebundeld
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
            "contribution_rows": contribution_rows,
            "coverage": coverage,
            "scenario_monthly_total": scenario_monthly_total,
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
        existing.source = "manual"
    else:
        db.add(MortgageScenarioBudget(
            scenario_id=scenario.id, category_id=cat_id, amount=value,
            source="manual",
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
    funda_url: str = Form(""),
    photo_url: str = Form(""),
    purchase_fee_pct: str = Form(""),
    sale_fee_pct: str = Form(""),
    municipal_cost_factor: str = Form(""),
    insurance_cost_factor: str = Form(""),
    monthly_refund_usage: str = Form(""),
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
        funda_url=funda_url,
        photo_url=photo_url,
        purchase_fee_pct=purchase_fee_pct,
        sale_fee_pct=sale_fee_pct,
        municipal_cost_factor=municipal_cost_factor,
        insurance_cost_factor=insurance_cost_factor,
        monthly_refund_usage=monthly_refund_usage,
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


# ──────────────────────────────────────────────────────────────────────────────
# Bestaande hypotheken per scenario (LIN-44)
# ──────────────────────────────────────────────────────────────────────────────

_EXISTING_TYPES = ("annuity", "interest_only")


def _clean_existing_type(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in _EXISTING_TYPES else "annuity"


def _existing_mortgage_for(
    db: Session, user_id: int, scenario_id: int, em_id: int,
) -> ScenarioExistingMortgage:
    em = (
        db.query(ScenarioExistingMortgage)
        .join(MortgageScenario, ScenarioExistingMortgage.scenario_id == MortgageScenario.id)
        .filter(
            ScenarioExistingMortgage.id == em_id,
            ScenarioExistingMortgage.scenario_id == scenario_id,
            MortgageScenario.user_id == user_id,
        )
        .first()
    )
    if not em:
        raise HTTPException(status_code=404, detail="Bestaande hypotheek niet gevonden")
    return em


@router.post("/scenarios/{scenario_id}/existing-mortgages")
def existing_mortgage_create(
    scenario_id: int,
    request: Request,
    name: str = Form(""),
    balance_eur: str = Form("0"),
    mortgage_type: str = Form("annuity"),
    rate_pct: str = Form(""),
    months_remaining: str = Form(""),
    monthly_payment_eur: str = Form(""),
    counts_in_ltv: str = Form("1"),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    last = (
        db.query(ScenarioExistingMortgage)
        .filter(ScenarioExistingMortgage.scenario_id == scenario.id)
        .order_by(ScenarioExistingMortgage.sort_order.desc())
        .first()
    )
    next_order = ((last.sort_order if last else -1) + 1)

    em = ScenarioExistingMortgage(
        scenario_id=scenario.id,
        name=(name.strip() or "Bestaande hypotheek")[:100],
        balance_eur=_parse_decimal(balance_eur),
        mortgage_type=_clean_existing_type(mortgage_type),
        rate_pct=(_parse_decimal(rate_pct) if rate_pct.strip() else None),
        months_remaining=(int(months_remaining) if months_remaining.strip().isdigit() else None),
        monthly_payment_eur=(
            _parse_decimal(monthly_payment_eur) if monthly_payment_eur.strip() else None
        ),
        counts_in_ltv=1 if counts_in_ltv.strip() in ("1", "on", "true", "yes") else 0,
        sort_order=next_order,
    )
    db.add(em)
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}#existing-mortgages",
        status_code=302,
    )


@router.post("/scenarios/{scenario_id}/existing-mortgages/{em_id}/edit")
def existing_mortgage_edit(
    scenario_id: int,
    em_id: int,
    request: Request,
    name: str = Form(""),
    balance_eur: str = Form("0"),
    mortgage_type: str = Form("annuity"),
    rate_pct: str = Form(""),
    months_remaining: str = Form(""),
    monthly_payment_eur: str = Form(""),
    counts_in_ltv: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    em = _existing_mortgage_for(db, user.id, scenario_id, em_id)

    em.name = (name.strip() or em.name)[:100]
    em.balance_eur = _parse_decimal(balance_eur)
    em.mortgage_type = _clean_existing_type(mortgage_type)
    em.rate_pct = (_parse_decimal(rate_pct) if rate_pct.strip() else None)
    em.months_remaining = (int(months_remaining) if months_remaining.strip().isdigit() else None)
    em.monthly_payment_eur = (
        _parse_decimal(monthly_payment_eur) if monthly_payment_eur.strip() else None
    )
    # Checkbox: als-ie niet in de form zit (unchecked) krijgen we "". 0 = uit,
    # anders meetellen. Default blijft "1" zodat bestaande bank-hypotheken
    # door normaal submitten niet uitgeschakeld worden als de checkbox op
    # "1" staat.
    em.counts_in_ltv = 1 if counts_in_ltv.strip() in ("1", "on", "true", "yes") else 0
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario_id}#existing-mortgages",
        status_code=302,
    )


@router.post("/scenarios/{scenario_id}/existing-mortgages/{em_id}/delete")
def existing_mortgage_delete(
    scenario_id: int,
    em_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    em = _existing_mortgage_for(db, user.id, scenario_id, em_id)
    db.delete(em)
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario_id}#existing-mortgages",
        status_code=302,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Person contributions (LIN-45)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/scenarios/{scenario_id}/contributions")
def scenario_contribution_upsert(
    scenario_id: int,
    request: Request,
    person_id: str = Form(...),
    amount: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = _require_admin(request, db)
    scenario = _get_scenario(db, user.id, scenario_id)
    try:
        pid = int(person_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Ongeldige person_id")

    person = db.query(Person).filter(
        Person.id == pid, Person.user_id == user.id,
    ).first()
    if not person:
        raise HTTPException(status_code=404, detail="Persoon niet gevonden")

    value = _parse_decimal(amount)
    existing = db.query(ScenarioPersonContribution).filter(
        ScenarioPersonContribution.scenario_id == scenario.id,
        ScenarioPersonContribution.person_id == pid,
    ).first()
    if existing:
        existing.monthly_contribution_eur = value
    else:
        db.add(ScenarioPersonContribution(
            scenario_id=scenario.id,
            person_id=pid,
            monthly_contribution_eur=value,
        ))
    db.commit()
    return RedirectResponse(
        f"/hypotheek/scenarios/{scenario.id}#contributions", status_code=302,
    )
