import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PortfolioAsset, PortfolioPerson, PortfolioHolding
from app.auth import require_login
from app.portfolio_prices import fetch_price, PRESET_ASSETS

router = APIRouter(prefix="/portfolio")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def portfolio_overview(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    assets = (
        db.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == user.id)
        .order_by(PortfolioAsset.asset_class, PortfolioAsset.name)
        .all()
    )
    persons = (
        db.query(PortfolioPerson)
        .filter(PortfolioPerson.user_id == user.id)
        .order_by(PortfolioPerson.name)
        .all()
    )
    holdings = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user.id)
        .all()
    )

    # Build holdings matrix: {(asset_id, person_id): quantity}
    holdings_map = {}
    for h in holdings:
        holdings_map[(h.asset_id, h.person_id)] = h.quantity

    # Calculate totals per person
    person_totals = {p.id: Decimal("0") for p in persons}
    asset_totals = {}
    grand_total = Decimal("0")

    for asset in assets:
        asset_total = Decimal("0")
        for person in persons:
            qty = holdings_map.get((asset.id, person.id), Decimal("0"))
            value = qty * asset.current_price_eur
            person_totals[person.id] += value
            asset_total += value
        asset_totals[asset.id] = asset_total
        grand_total += asset_total

    # Build projection data (months ahead)
    projection_months = 12
    projections = []
    for m in range(1, projection_months + 1):
        month_total = Decimal("0")
        for asset in assets:
            growth = (1 + asset.monthly_growth_pct / 100) ** m
            asset_value = asset_totals.get(asset.id, Decimal("0"))
            month_total += asset_value * growth
        projections.append({
            "month": m,
            "total": month_total,
            "growth": month_total - grand_total,
        })

    return templates.TemplateResponse(
        "portfolio/index.html",
        {
            "request": request,
            "user": user,
            "assets": assets,
            "persons": persons,
            "holdings_map": holdings_map,
            "person_totals": person_totals,
            "asset_totals": asset_totals,
            "grand_total": grand_total,
            "projections": projections,
            "preset_assets": PRESET_ASSETS,
        },
    )


@router.post("/persons")
def add_person(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    name = name.strip()
    if name:
        person = PortfolioPerson(user_id=user.id, name=name)
        db.add(person)
        db.commit()
    return RedirectResponse("/portfolio", status_code=302)


@router.post("/persons/{person_id}/delete")
def delete_person(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    person = db.query(PortfolioPerson).filter(
        PortfolioPerson.id == person_id,
        PortfolioPerson.user_id == user.id,
    ).first()
    if person:
        db.delete(person)
        db.commit()
    return RedirectResponse("/portfolio", status_code=302)


@router.post("/assets")
def add_asset(
    request: Request,
    name: str = Form(...),
    symbol: str = Form(...),
    asset_class: str = Form(...),
    unit: str = Form(""),
    monthly_growth_pct: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    try:
        growth = Decimal(monthly_growth_pct.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        growth = Decimal("0")

    asset = PortfolioAsset(
        user_id=user.id,
        name=name.strip(),
        symbol=symbol.strip(),
        asset_class=asset_class,
        unit=unit.strip() or "stuk",
        monthly_growth_pct=growth,
    )
    db.add(asset)
    db.commit()

    return RedirectResponse("/portfolio", status_code=302)


@router.post("/assets/{asset_id}/edit")
def edit_asset(
    asset_id: int,
    request: Request,
    name: str = Form(...),
    unit: str = Form(""),
    monthly_growth_pct: str = Form("0"),
    manual_price: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.id == asset_id,
        PortfolioAsset.user_id == user.id,
    ).first()
    if not asset:
        return RedirectResponse("/portfolio", status_code=302)

    asset.name = name.strip()
    if unit.strip():
        asset.unit = unit.strip()

    try:
        asset.monthly_growth_pct = Decimal(monthly_growth_pct.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        pass

    # Manual price override
    manual = manual_price.strip().replace(",", ".")
    if manual:
        try:
            asset.current_price_eur = Decimal(manual)
            asset.price_updated_at = datetime.datetime.utcnow()
        except (InvalidOperation, ValueError):
            pass

    db.commit()
    return RedirectResponse("/portfolio", status_code=302)


@router.post("/assets/{asset_id}/delete")
def delete_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.id == asset_id,
        PortfolioAsset.user_id == user.id,
    ).first()
    if asset:
        db.delete(asset)
        db.commit()
    return RedirectResponse("/portfolio", status_code=302)


@router.post("/holdings/save")
def save_holding(
    request: Request,
    asset_id: int = Form(...),
    person_id: int = Form(...),
    quantity: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Verify ownership
    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.id == asset_id, PortfolioAsset.user_id == user.id
    ).first()
    person = db.query(PortfolioPerson).filter(
        PortfolioPerson.id == person_id, PortfolioPerson.user_id == user.id
    ).first()
    if not asset or not person:
        return JSONResponse({"ok": False}, status_code=400)

    try:
        qty = Decimal(quantity.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        return JSONResponse({"ok": False}, status_code=400)

    holding = db.query(PortfolioHolding).filter(
        PortfolioHolding.user_id == user.id,
        PortfolioHolding.asset_id == asset_id,
        PortfolioHolding.person_id == person_id,
    ).first()

    if holding:
        holding.quantity = qty
    else:
        holding = PortfolioHolding(
            user_id=user.id,
            asset_id=asset_id,
            person_id=person_id,
            quantity=qty,
        )
        db.add(holding)

    db.commit()
    value = float(qty * asset.current_price_eur)
    return JSONResponse({"ok": True, "quantity": float(qty), "value": value})


@router.post("/refresh-prices")
def refresh_prices(
    request: Request,
    db: Session = Depends(get_db),
):
    """Fetch live prices for all assets."""
    user = require_login(request, db)

    assets = (
        db.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == user.id)
        .all()
    )

    updated = 0
    for asset in assets:
        price = fetch_price(asset.symbol, asset.asset_class)
        if price is not None:
            asset.current_price_eur = price
            asset.price_updated_at = datetime.datetime.utcnow()
            updated += 1

    db.commit()
    return RedirectResponse("/portfolio", status_code=302)
