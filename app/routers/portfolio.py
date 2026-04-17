import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PortfolioAsset, Person, PortfolioHolding, PortfolioPriceSnapshot
from app.auth import require_login
from app.portfolio_prices import fetch_price, fetch_historical_prices, PRESET_ASSETS
from app.template_config import templates

router = APIRouter(prefix="/portfolio")

MONTH_LABELS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]


ASSET_TYPE_LABELS = {
    "stock": "Beleggingen",
    "crypto": "Crypto",
    "metal": "Edelmetaal",
}


@router.get("")
def portfolio_overview(
    request: Request,
    type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    filter_type = type if type in ASSET_TYPE_LABELS else None

    asset_query = db.query(PortfolioAsset).filter(PortfolioAsset.user_id == user.id)
    if filter_type:
        asset_query = asset_query.filter(PortfolioAsset.asset_class == filter_type)
    assets = asset_query.order_by(PortfolioAsset.asset_class, PortfolioAsset.name).all()
    persons = (
        db.query(Person)
        .filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    holdings = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user.id)
        .all()
    )

    # Build holdings matrix: {(asset_id, person_id): quantity}
    # en een contributie-map {(asset_id, person_id): monthly_contribution_eur}
    holdings_map = {}
    contribution_map = {}
    for h in holdings:
        holdings_map[(h.asset_id, h.person_id)] = h.quantity
        contribution_map[(h.asset_id, h.person_id)] = h.monthly_contribution_eur or Decimal("0")

    # Calculate totals per person
    person_totals = {p.id: Decimal("0") for p in persons}
    asset_totals = {}
    asset_contributions = {}
    grand_total = Decimal("0")

    for asset in assets:
        asset_total = Decimal("0")
        asset_contribution = Decimal("0")
        for person in persons:
            qty = holdings_map.get((asset.id, person.id), Decimal("0"))
            value = qty * asset.current_price_eur
            person_totals[person.id] += value
            asset_total += value
            asset_contribution += contribution_map.get((asset.id, person.id), Decimal("0"))
        asset_totals[asset.id] = asset_total
        asset_contributions[asset.id] = asset_contribution
        grand_total += asset_total

    # Build chart data for portfolio value over time
    now = datetime.date.today()
    current_year = now.year
    current_month = now.month
    chart_data = {"labels": MONTH_LABELS, "past": [], "future": []}

    if assets and grand_total > 0:
        # Get total quantity per asset
        asset_quantities = {}
        for asset in assets:
            total_qty = Decimal("0")
            for person in persons:
                total_qty += holdings_map.get((asset.id, person.id), Decimal("0"))
            asset_quantities[asset.id] = total_qty

        # Fetch price snapshots for this year
        asset_ids = [a.id for a in assets]
        snapshots = (
            db.query(PortfolioPriceSnapshot)
            .filter(
                PortfolioPriceSnapshot.asset_id.in_(asset_ids),
                PortfolioPriceSnapshot.year == current_year,
            )
            .all()
        )
        # Build lookup: {(asset_id, month): price}
        snapshot_map = {}
        for s in snapshots:
            snapshot_map[(s.asset_id, s.month)] = s.price_eur

        for month in range(1, 13):
            if month <= current_month:
                # Past/current: use historical prices from snapshots
                month_total = Decimal("0")
                has_data = False
                for asset in assets:
                    price = snapshot_map.get((asset.id, month))
                    if price is not None:
                        has_data = True
                        month_total += asset_quantities[asset.id] * price
                    else:
                        # Fallback: use current price
                        month_total += asset_quantities[asset.id] * asset.current_price_eur

                chart_data["past"].append(float(round(month_total, 2)))
                # Current month also goes to future for seamless connection
                if month == current_month:
                    chart_data["future"].append(float(round(month_total, 2)))
                else:
                    chart_data["future"].append(None)
            else:
                # Future: project from current value using growth + monthly contribution.
                # Per asset simuleren we maand-voor-maand van current_month tot `month`:
                #   value = (value + contribution) * (1 + growth/100)
                # zodat stortingen gestapeld groeien en onttrekkingen (negatief) het
                # saldo verlagen.
                chart_data["past"].append(None)
                months_ahead = month - current_month
                month_total = Decimal("0")
                for asset in assets:
                    value = asset_totals.get(asset.id, Decimal("0"))
                    contribution = asset_contributions.get(asset.id, Decimal("0"))
                    growth_factor = Decimal("1") + (asset.monthly_growth_pct / Decimal("100"))
                    for _ in range(months_ahead):
                        value = (value + contribution) * growth_factor
                    month_total += value
                chart_data["future"].append(float(round(month_total, 2)))

    return templates.TemplateResponse(
        "portfolio/index.html",
        {
            "request": request,
            "user": user,
            "assets": assets,
            "persons": persons,
            "holdings_map": holdings_map,
            "contribution_map": contribution_map,
            "person_totals": person_totals,
            "asset_totals": asset_totals,
            "asset_contributions": asset_contributions,
            "grand_total": grand_total,
            "chart_data": chart_data,
            "current_year": current_year,
            "preset_assets": PRESET_ASSETS,
            "filter_type": filter_type,
            "filter_type_label": ASSET_TYPE_LABELS.get(filter_type) if filter_type else None,
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
        max_order = db.query(Person).filter(Person.user_id == user.id).count()
        person = Person(user_id=user.id, name=name, sort_order=max_order)
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
    person = db.query(Person).filter(
        Person.id == person_id,
        Person.user_id == user.id,
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
    person = db.query(Person).filter(
        Person.id == person_id, Person.user_id == user.id
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


@router.post("/holdings/save-contribution")
def save_contribution(
    request: Request,
    asset_id: int = Form(...),
    person_id: int = Form(...),
    contribution: str = Form("0"),
    db: Session = Depends(get_db),
):
    """Sla een maandelijkse storting (positief) of onttrekking (negatief) op
    voor een specifieke (asset, person)-combinatie. Gebruikt voor de
    projectie-grafiek zodat toekomstige maanden realistisch meegroeien."""
    user = require_login(request, db)

    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.id == asset_id, PortfolioAsset.user_id == user.id
    ).first()
    person = db.query(Person).filter(
        Person.id == person_id, Person.user_id == user.id
    ).first()
    if not asset or not person:
        return JSONResponse({"ok": False}, status_code=400)

    try:
        amount = Decimal(contribution.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        return JSONResponse({"ok": False}, status_code=400)

    holding = db.query(PortfolioHolding).filter(
        PortfolioHolding.user_id == user.id,
        PortfolioHolding.asset_id == asset_id,
        PortfolioHolding.person_id == person_id,
    ).first()

    if holding:
        holding.monthly_contribution_eur = amount
    else:
        holding = PortfolioHolding(
            user_id=user.id,
            asset_id=asset_id,
            person_id=person_id,
            quantity=Decimal("0"),
            monthly_contribution_eur=amount,
        )
        db.add(holding)

    db.commit()
    return JSONResponse({"ok": True, "contribution": float(amount)})


@router.post("/refresh-prices")
def refresh_prices(
    request: Request,
    db: Session = Depends(get_db),
):
    """Fetch live prices and historical prices for all assets."""
    user = require_login(request, db)

    assets = (
        db.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == user.id)
        .all()
    )

    updated = 0
    for asset in assets:
        # Fetch current price
        price = fetch_price(asset.symbol, asset.asset_class)
        if price is not None:
            asset.current_price_eur = price
            asset.price_updated_at = datetime.datetime.utcnow()
            updated += 1

        # Fetch and store historical prices
        history = fetch_historical_prices(asset.symbol, asset.asset_class, months=12)
        for (year, month), hist_price in history.items():
            existing = db.query(PortfolioPriceSnapshot).filter(
                PortfolioPriceSnapshot.asset_id == asset.id,
                PortfolioPriceSnapshot.year == year,
                PortfolioPriceSnapshot.month == month,
            ).first()
            if existing:
                existing.price_eur = hist_price
            else:
                snapshot = PortfolioPriceSnapshot(
                    asset_id=asset.id,
                    year=year,
                    month=month,
                    price_eur=hist_price,
                )
                db.add(snapshot)

    db.commit()
    return RedirectResponse("/portfolio", status_code=302)
