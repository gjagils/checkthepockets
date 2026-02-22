from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Account, Transaction, Category
from app.auth import require_login
from app.parsers import abn_amro, bunq, ics
from app.parsers.base import ParseError

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PARSERS = {
    "abn_amro": ("ABN AMRO", abn_amro.parse),
    "bunq": ("Bunq", bunq.parse),
    "ics": ("ICS", ics.parse),
}

PER_PAGE = 50


@router.get("/")
def transaction_list(
    request: Request,
    page: int = Query(1, ge=1),
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    query = (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.category))
        .filter(Account.user_id == user.id)
    )

    if account_id:
        query = query.filter(Transaction.account_id == account_id)

    total = query.count()
    transactions = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
        .all()
    )

    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    # Get categories grouped by parent for the dropdown
    all_cats = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )
    parents = [c for c in all_cats if c.parent_id is None]
    children_map = {}
    for c in all_cats:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

    return templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "current_account_id": account_id,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "parents": parents,
            "children_map": children_map,
        },
    )


@router.post("/transactions/{transaction_id}/category")
def set_category(
    request: Request,
    transaction_id: int,
    category_id: int = Form(0),
    redirect_to: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return RedirectResponse(redirect_to, status_code=302)

    tx.category_id = category_id if category_id else None
    db.commit()

    return RedirectResponse(redirect_to, status_code=302)


@router.get("/import")
def import_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse(
        "transactions/import.html",
        {
            "request": request,
            "user": user,
            "banks": {k: v[0] for k, v in PARSERS.items()},
        },
    )


@router.post("/import")
async def import_csv(
    request: Request,
    bank: str = Form(...),
    account_name: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    if bank not in PARSERS:
        return templates.TemplateResponse(
            "transactions/import.html",
            {
                "request": request,
                "user": user,
                "banks": {k: v[0] for k, v in PARSERS.items()},
                "error": "Onbekende bank geselecteerd",
            },
            status_code=400,
        )

    content = await file.read()
    if not content:
        return templates.TemplateResponse(
            "transactions/import.html",
            {
                "request": request,
                "user": user,
                "banks": {k: v[0] for k, v in PARSERS.items()},
                "error": "Leeg bestand",
            },
            status_code=400,
        )

    bank_label, parser = PARSERS[bank]

    try:
        detected_iban, parsed = parser(content)
    except ParseError as e:
        return templates.TemplateResponse(
            "transactions/import.html",
            {
                "request": request,
                "user": user,
                "banks": {k: v[0] for k, v in PARSERS.items()},
                "error": f"Fout bij verwerken: {e}",
            },
            status_code=400,
        )

    if not parsed:
        return templates.TemplateResponse(
            "transactions/import.html",
            {
                "request": request,
                "user": user,
                "banks": {k: v[0] for k, v in PARSERS.items()},
                "error": "Geen transacties gevonden in het bestand",
            },
            status_code=400,
        )

    # Find or create account
    iban = detected_iban
    name = account_name.strip() or f"{bank_label} - {iban or 'creditcard'}"

    account = (
        db.query(Account)
        .filter(
            Account.user_id == user.id,
            Account.bank == bank,
            Account.iban == iban,
        )
        .first()
    )

    if not account:
        account = Account(
            user_id=user.id,
            name=name,
            iban=iban,
            bank=bank,
        )
        db.add(account)
        db.flush()

    # Import transactions, skip duplicates
    imported = 0
    skipped = 0
    for tx in parsed:
        exists = (
            db.query(Transaction)
            .filter(Transaction.import_hash == tx.import_hash)
            .first()
        )
        if exists:
            skipped += 1
            continue

        db_tx = Transaction(
            account_id=account.id,
            date=tx.date,
            amount=tx.amount,
            currency=tx.currency,
            description=tx.description,
            counterparty=tx.counterparty,
            counterparty_iban=tx.counterparty_iban,
            balance_after=tx.balance_after,
            import_hash=tx.import_hash,
        )
        db.add(db_tx)
        imported += 1

    db.commit()

    return templates.TemplateResponse(
        "transactions/import_result.html",
        {
            "request": request,
            "user": user,
            "imported": imported,
            "skipped": skipped,
            "total": len(parsed),
            "account": account,
        },
    )
