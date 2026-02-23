import hashlib
import uuid
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Account, Transaction, Category, Tag, Rule
from app.auth import require_login
from app.parsers import abn_amro, bunq, ics
from app.parsers.base import ParseError, ParsedTransaction
from app.parsers.ics_pdf import parse_ics_pdf
from app.rules_engine import apply_rules_to_transaction

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
    category_id: int | None = Query(None),
    tag_id: int | None = Query(None),
    search: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    amount_min: str | None = Query(None),
    amount_max: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    query = (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.category))
        .filter(Account.user_id == user.id)
    )

    # Hide parent transactions that have been split (children replace them)
    split_parent_ids = (
        db.query(Transaction.parent_id)
        .filter(Transaction.parent_id.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    query = query.filter(Transaction.id.notin_(split_parent_ids))

    # Filters
    if account_id:
        query = query.filter(Transaction.account_id == account_id)

    if category_id:
        if category_id == -1:
            query = query.filter(Transaction.category_id.is_(None))
        else:
            # Include child categories
            cat = db.query(Category).filter(
                Category.id == category_id, Category.user_id == user.id
            ).first()
            if cat:
                child_ids = [c.id for c in cat.children]
                query = query.filter(
                    Transaction.category_id.in_([category_id] + child_ids)
                )

    if tag_id:
        query = query.filter(Transaction.tags.any(Tag.id == tag_id))

    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Transaction.description.ilike(search_term),
                Transaction.counterparty.ilike(search_term),
                Transaction.counterparty_iban.ilike(search_term),
            )
        )

    if date_from:
        try:
            query = query.filter(Transaction.date >= date_type.fromisoformat(date_from))
        except ValueError:
            pass

    if date_to:
        try:
            query = query.filter(Transaction.date <= date_type.fromisoformat(date_to))
        except ValueError:
            pass

    if amount_min:
        try:
            query = query.filter(Transaction.amount >= float(amount_min))
        except ValueError:
            pass

    if amount_max:
        try:
            query = query.filter(Transaction.amount <= float(amount_max))
        except ValueError:
            pass

    total = query.count()
    transactions = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
        .all()
    )

    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )
    tags = (
        db.query(Tag)
        .filter(Tag.user_id == user.id)
        .order_by(Tag.name)
        .all()
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    filter_params = {}
    if account_id:
        filter_params["account_id"] = account_id
    if category_id:
        filter_params["category_id"] = category_id
    if tag_id:
        filter_params["tag_id"] = tag_id
    if search:
        filter_params["search"] = search
    if date_from:
        filter_params["date_from"] = date_from
    if date_to:
        filter_params["date_to"] = date_to
    if amount_min:
        filter_params["amount_min"] = amount_min
    if amount_max:
        filter_params["amount_max"] = amount_max

    # Get categories grouped by account_id -> parent -> children
    all_cats = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )
    # {account_id: {"parents": [...], "children": {parent_id: [...]}}}
    cats_by_account = {}
    for c in all_cats:
        aid = c.account_id
        if aid not in cats_by_account:
            cats_by_account[aid] = {"parents": [], "children": {}}
        if c.parent_id is None:
            cats_by_account[aid]["parents"].append(c)
        else:
            cats_by_account[aid]["children"].setdefault(c.parent_id, []).append(c)

    return templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "categories": categories,
            "tags": tags,
            "current_account_id": account_id,
            "current_category_id": category_id,
            "current_tag_id": tag_id,
            "search": search or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "amount_min": amount_min or "",
            "amount_max": amount_max or "",
            "filter_params": filter_params,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "cats_by_account": cats_by_account,
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


@router.get("/transactions/{transaction_id}/edit")
def edit_transaction_page(
    transaction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    transaction = (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.tags))
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not transaction:
        return RedirectResponse("/", status_code=302)

    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )
    tags = (
        db.query(Tag)
        .filter(Tag.user_id == user.id)
        .order_by(Tag.name)
        .all()
    )

    return templates.TemplateResponse(
        "transactions/edit.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "categories": categories,
            "tags": tags,
        },
    )


@router.post("/transactions/{transaction_id}/edit")
async def edit_transaction(
    transaction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    transaction = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not transaction:
        return RedirectResponse("/", status_code=302)

    form = await request.form()
    transaction.description = (form.get("description") or "").strip() or None
    transaction.counterparty = (form.get("counterparty") or "").strip() or None
    cat_id = (form.get("category_id") or "").strip()
    transaction.category_id = int(cat_id) if cat_id else None

    # Handle tags
    tag_ids = form.getlist("tag_ids")
    selected_tags = []
    for tid in tag_ids:
        tag = db.query(Tag).filter(Tag.id == int(tid), Tag.user_id == user.id).first()
        if tag:
            selected_tags.append(tag)

    # Create new tag if provided
    new_tag_name = (form.get("new_tag") or "").strip()
    if new_tag_name:
        existing = db.query(Tag).filter(
            Tag.user_id == user.id, Tag.name == new_tag_name
        ).first()
        if existing:
            selected_tags.append(existing)
        else:
            tag_obj = Tag(user_id=user.id, name=new_tag_name)
            db.add(tag_obj)
            db.flush()
            selected_tags.append(tag_obj)

    transaction.tags = selected_tags
    db.commit()

    return RedirectResponse("/", status_code=302)


@router.get("/transactions/create")
def create_transaction_page(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    accounts = db.query(Account).filter(Account.user_id == user.id).order_by(Account.name).all()
    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )

    return templates.TemplateResponse(
        "transactions/create.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "categories": categories,
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/transactions/create")
def create_transaction(
    request: Request,
    account_id: int = Form(...),
    date: str = Form(...),
    amount: str = Form(...),
    description: str = Form(""),
    counterparty: str = Form(""),
    category_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Validate account belongs to user
    account = db.query(Account).filter(
        Account.id == account_id, Account.user_id == user.id
    ).first()
    if not account:
        return RedirectResponse("/", status_code=302)

    # Parse amount
    try:
        parsed_amount = Decimal(amount.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse("/transactions/create", status_code=302)

    # Parse date
    try:
        parsed_date = date_type.fromisoformat(date.strip())
    except ValueError:
        return RedirectResponse("/transactions/create", status_code=302)

    cat_id = int(category_id) if category_id.strip() else None

    # Generate unique hash for manual entries
    unique_key = f"MANUAL-{user.id}-{uuid.uuid4()}"
    import_hash = hashlib.sha256(unique_key.encode()).hexdigest()

    tx = Transaction(
        account_id=account.id,
        date=parsed_date,
        amount=parsed_amount,
        currency="EUR",
        description=description.strip() or None,
        counterparty=counterparty.strip() or None,
        category_id=cat_id,
        import_hash=import_hash,
    )
    db.add(tx)
    db.commit()

    return RedirectResponse("/", status_code=302)


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

    # Load active rules for auto-categorization
    active_rules = (
        db.query(Rule)
        .filter(Rule.user_id == user.id, Rule.is_active == 1)
        .all()
    )

    # Import transactions, skip duplicates
    imported = 0
    skipped = 0
    auto_categorized = 0
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
        db.flush()

        # Apply rules to new transaction
        if active_rules and apply_rules_to_transaction(active_rules, db_tx, db):
            auto_categorized += 1

        imported += 1

    db.commit()

    return templates.TemplateResponse(
        "transactions/import_result.html",
        {
            "request": request,
            "user": user,
            "imported": imported,
            "skipped": skipped,
            "auto_categorized": auto_categorized,
            "total": len(parsed),
            "account": account,
        },
    )


# ===== Split / Specificeer =====

@router.get("/transactions/{transaction_id}/split")
def split_transaction_page(
    transaction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Show the split transaction page where user uploads an ICS PDF."""
    user = require_login(request, db)
    transaction = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not transaction:
        return RedirectResponse("/", status_code=302)

    # Check if already split
    existing_children = (
        db.query(Transaction)
        .filter(Transaction.parent_id == transaction_id)
        .all()
    )

    return templates.TemplateResponse(
        "transactions/split.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "existing_children": existing_children,
        },
    )


@router.post("/transactions/{transaction_id}/split")
async def split_transaction(
    transaction_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Parse ICS PDF and create child transactions."""
    user = require_login(request, db)
    transaction = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not transaction:
        return RedirectResponse("/", status_code=302)

    content = await file.read()
    if not content:
        return templates.TemplateResponse(
            "transactions/split.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "existing_children": [],
                "error": "Leeg bestand",
            },
            status_code=400,
        )

    try:
        parsed_lines = parse_ics_pdf(content)
    except ParseError as e:
        return templates.TemplateResponse(
            "transactions/split.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "existing_children": [],
                "error": f"Fout bij verwerken PDF: {e}",
            },
            status_code=400,
        )

    # Load active rules for auto-categorization
    active_rules = (
        db.query(Rule)
        .filter(Rule.user_id == user.id, Rule.is_active == 1)
        .all()
    )

    # Delete existing children if re-splitting
    db.query(Transaction).filter(Transaction.parent_id == transaction_id).delete()
    db.flush()

    # Create child transactions
    try:
        created = 0
        auto_categorized = 0
        for idx, line in enumerate(parsed_lines):
            # Make amount negative for debits (expenses), positive for credits (refunds)
            amount = -line.amount_eur if line.is_debit else line.amount_eur

            child = Transaction(
                account_id=transaction.account_id,
                date=line.transaction_date,
                amount=amount,
                currency="EUR",
                description=line.description,
                counterparty=line.description.split()[0] if line.description else None,
                parent_id=transaction.id,
                import_hash=ParsedTransaction(
                    date=line.transaction_date,
                    amount=amount,
                    currency="EUR",
                    description=f"ICS-SPLIT-{transaction.id}-{idx}-{line.description}-{line.transaction_date}",
                ).import_hash,
            )
            db.add(child)
            db.flush()

            if active_rules and apply_rules_to_transaction(active_rules, child, db):
                auto_categorized += 1

            created += 1

        db.commit()
    except IntegrityError:
        db.rollback()
        existing_children = (
            db.query(Transaction)
            .filter(Transaction.parent_id == transaction_id)
            .all()
        )
        return templates.TemplateResponse(
            "transactions/split.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "existing_children": existing_children,
                "error": "Splitsen mislukt: een of meer transacties bestaan al. Maak eerst de vorige split ongedaan en probeer opnieuw.",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "transactions/split_result.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "created": created,
            "auto_categorized": auto_categorized,
        },
    )


@router.post("/transactions/{transaction_id}/unsplit")
def unsplit_transaction(
    transaction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Remove all child transactions and restore the parent."""
    user = require_login(request, db)
    transaction = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not transaction:
        return RedirectResponse("/", status_code=302)

    db.query(Transaction).filter(Transaction.parent_id == transaction_id).delete()
    db.commit()

    return RedirectResponse("/", status_code=302)
