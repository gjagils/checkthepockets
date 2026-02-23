import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import NetWorthAccount, NetWorthSnapshot
from app.auth import require_login

router = APIRouter(prefix="/networth")
templates = Jinja2Templates(directory="app/templates")

ACCOUNT_TYPES = {
    "asset": "Bezitting",
    "liability": "Schuld",
}

CATEGORIES = {
    "savings": "Spaargeld",
    "investment": "Beleggingen",
    "property": "Vastgoed",
    "vehicle": "Voertuig",
    "pension": "Pensioen",
    "mortgage": "Hypotheek",
    "loan": "Lening",
    "credit": "Krediet",
    "other": "Overig",
}

MONTH_NAMES_NL = {
    1: "Jan", 2: "Feb", 3: "Mrt", 4: "Apr",
    5: "Mei", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Okt", 11: "Nov", 12: "Dec",
}


@router.get("")
def networth_overview(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()

    accounts = (
        db.query(NetWorthAccount)
        .filter(NetWorthAccount.user_id == user.id)
        .order_by(NetWorthAccount.account_type, NetWorthAccount.name)
        .all()
    )

    # Split into assets and liabilities
    assets = [a for a in accounts if a.account_type == "asset" and a.is_active]
    liabilities = [a for a in accounts if a.account_type == "liability" and a.is_active]
    inactive = [a for a in accounts if not a.is_active]

    total_assets = sum(a.balance or Decimal("0") for a in assets)
    total_liabilities = sum(a.balance or Decimal("0") for a in liabilities)
    net_worth = total_assets - total_liabilities

    # Group by category
    asset_groups = {}
    for a in assets:
        cat_label = CATEGORIES.get(a.category, a.category)
        asset_groups.setdefault(cat_label, []).append(a)

    liability_groups = {}
    for a in liabilities:
        cat_label = CATEGORIES.get(a.category, a.category)
        liability_groups.setdefault(cat_label, []).append(a)

    # Historical net worth (aggregate snapshots by month)
    history = _get_networth_history(db, user.id)

    return templates.TemplateResponse(
        "networth/index.html",
        {
            "request": request,
            "user": user,
            "asset_groups": asset_groups,
            "liability_groups": liability_groups,
            "inactive": inactive,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "net_worth": net_worth,
            "history": history,
            "account_types": ACCOUNT_TYPES,
            "categories": CATEGORIES,
            "month_names": MONTH_NAMES_NL,
            "today": today,
        },
    )


def _get_networth_history(db: Session, user_id: int) -> list[dict]:
    """Get monthly net worth history from snapshots."""
    rows = (
        db.query(
            NetWorthSnapshot.year,
            NetWorthSnapshot.month,
            NetWorthAccount.account_type,
            func.sum(NetWorthSnapshot.balance).label("total"),
        )
        .join(NetWorthAccount)
        .filter(NetWorthSnapshot.user_id == user_id)
        .group_by(
            NetWorthSnapshot.year,
            NetWorthSnapshot.month,
            NetWorthAccount.account_type,
        )
        .order_by(NetWorthSnapshot.year, NetWorthSnapshot.month)
        .all()
    )

    # Combine into monthly entries
    monthly = {}
    for row in rows:
        key = (row.year, row.month)
        if key not in monthly:
            monthly[key] = {"year": row.year, "month": row.month, "assets": Decimal("0"), "liabilities": Decimal("0")}
        if row.account_type == "asset":
            monthly[key]["assets"] = row.total or Decimal("0")
        else:
            monthly[key]["liabilities"] = row.total or Decimal("0")

    history = []
    for key in sorted(monthly.keys()):
        entry = monthly[key]
        entry["net_worth"] = entry["assets"] - entry["liabilities"]
        history.append(entry)

    return history


@router.post("/accounts")
def create_account(
    request: Request,
    name: str = Form(...),
    account_type: str = Form(...),
    category: str = Form(...),
    balance: str = Form("0"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    if not name or account_type not in ACCOUNT_TYPES:
        return RedirectResponse("/networth", status_code=302)

    try:
        parsed_balance = Decimal(balance.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        parsed_balance = Decimal("0")

    account = NetWorthAccount(
        user_id=user.id,
        name=name,
        account_type=account_type,
        category=category if category in CATEGORIES else "other",
        balance=parsed_balance,
        notes=notes.strip() or None,
    )
    db.add(account)
    db.commit()

    return RedirectResponse("/networth", status_code=302)


@router.post("/accounts/{account_id}/edit")
def edit_account(
    account_id: int,
    request: Request,
    name: str = Form(...),
    balance: str = Form("0"),
    category: str = Form("other"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    account = db.query(NetWorthAccount).filter(
        NetWorthAccount.id == account_id, NetWorthAccount.user_id == user.id
    ).first()
    if not account:
        return RedirectResponse("/networth", status_code=302)

    name = name.strip()
    if name:
        account.name = name

    try:
        account.balance = Decimal(balance.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        pass

    if category in CATEGORIES:
        account.category = category
    account.notes = notes.strip() or None
    account.updated_at = datetime.datetime.utcnow()
    db.commit()

    return RedirectResponse("/networth", status_code=302)


@router.post("/accounts/{account_id}/toggle")
def toggle_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    account = db.query(NetWorthAccount).filter(
        NetWorthAccount.id == account_id, NetWorthAccount.user_id == user.id
    ).first()
    if account:
        account.is_active = 0 if account.is_active else 1
        db.commit()
    return RedirectResponse("/networth", status_code=302)


@router.post("/accounts/{account_id}/delete")
def delete_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    account = db.query(NetWorthAccount).filter(
        NetWorthAccount.id == account_id, NetWorthAccount.user_id == user.id
    ).first()
    if account:
        db.delete(account)
        db.commit()
    return RedirectResponse("/networth", status_code=302)


@router.post("/accounts/{account_id}/balance")
def update_balance_ajax(
    account_id: int,
    request: Request,
    balance: str = Form("0"),
    db: Session = Depends(get_db),
):
    """AJAX endpoint to update a single account balance."""
    user = require_login(request, db)
    account = db.query(NetWorthAccount).filter(
        NetWorthAccount.id == account_id, NetWorthAccount.user_id == user.id
    ).first()
    if not account:
        return JSONResponse({"ok": False}, status_code=404)

    try:
        account.balance = Decimal(balance.strip().replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        return JSONResponse({"ok": False}, status_code=400)

    account.updated_at = datetime.datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "balance": float(account.balance)})


@router.post("/snapshot")
def take_snapshot(
    request: Request,
    db: Session = Depends(get_db),
):
    """Save current balances as a monthly snapshot."""
    user = require_login(request, db)
    today = datetime.date.today()
    year, month = today.year, today.month

    accounts = (
        db.query(NetWorthAccount)
        .filter(NetWorthAccount.user_id == user.id, NetWorthAccount.is_active == 1)
        .all()
    )

    for account in accounts:
        existing = (
            db.query(NetWorthSnapshot)
            .filter(
                NetWorthSnapshot.account_id == account.id,
                NetWorthSnapshot.year == year,
                NetWorthSnapshot.month == month,
            )
            .first()
        )
        if existing:
            existing.balance = account.balance or Decimal("0")
        else:
            db.add(NetWorthSnapshot(
                user_id=user.id,
                account_id=account.id,
                year=year,
                month=month,
                balance=account.balance or Decimal("0"),
            ))

    db.commit()
    return RedirectResponse("/networth", status_code=302)
