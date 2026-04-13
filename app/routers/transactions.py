import base64
import csv
import hashlib
import io
import json
import uuid
import calendar as _calendar
from datetime import date as date_type, timedelta, datetime as _datetime
from decimal import Decimal, InvalidOperation
from typing import List
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, tuple_
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Account, Transaction, Category, Tag, Rule, RecurringTransaction
from app.auth import require_login
from app.parsers import abn_amro, bunq, ics, ing, rabobank
from app.parsers.base import ParseError, ParsedTransaction
from app.parsers.ics_pdf import parse_ics_pdf
from app.rules_engine import apply_rules_to_transaction
from app.template_config import templates

router = APIRouter()

PARSERS = {
    "abn_amro": ("ABN AMRO", abn_amro.parse),
    "bunq": ("Bunq", bunq.parse),
    "ics": ("ICS", ics.parse),
    "ing": ("ING", ing.parse),
    "rabobank": ("Rabobank", rabobank.parse),
}

# Fields available for custom CSV column mapping
CUSTOM_CSV_FIELDS = [
    ("date",              "Datum *"),
    ("amount",            "Bedrag *"),
    ("description",       "Omschrijving"),
    ("counterparty",      "Tegenpartij"),
    ("counterparty_iban", "IBAN tegenpartij"),
    ("balance_after",     "Saldo na"),
    ("category",          "Categorie (naam)"),
]


def _get_csv_headers_and_preview(content: bytes) -> tuple[list[str], list[list[str]]]:
    """Return (headers, first_5_data_rows) from raw CSV bytes."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], []
    preview = []
    for i, row in enumerate(reader):
        if i >= 5:
            break
        preview.append(row)
    return headers, preview


def _parse_custom_csv(content: bytes, col_mapping: dict) -> list[ParsedTransaction]:
    """Parse a generic CSV using a user-defined column mapping."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    date_col   = col_mapping.get("date", "")
    amount_col = col_mapping.get("amount", "")
    desc_col   = col_mapping.get("description", "")
    cp_col     = col_mapping.get("counterparty", "")
    iban_col   = col_mapping.get("counterparty_iban", "")
    bal_col    = col_mapping.get("balance_after", "")
    cat_col    = col_mapping.get("category", "")

    DATE_FMTS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y%m%d"]

    parsed = []
    for row in reader:
        # --- date ---
        date_str = row.get(date_col, "").strip() if date_col else ""
        parsed_date = None
        for fmt in DATE_FMTS:
            try:
                parsed_date = _datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                pass
        if not parsed_date:
            continue

        # --- amount ---
        raw_amt = row.get(amount_col, "").strip().replace("\xa0", "").replace(" ", "") if amount_col else ""
        # Handle European format  1.234,56  or  1,234.56
        if "," in raw_amt and "." in raw_amt:
            if raw_amt.rindex(",") > raw_amt.rindex("."):  # 1.234,56
                raw_amt = raw_amt.replace(".", "").replace(",", ".")
            else:
                raw_amt = raw_amt.replace(",", "")
        elif "," in raw_amt:
            raw_amt = raw_amt.replace(",", ".")
        try:
            amount = Decimal(raw_amt)
        except InvalidOperation:
            continue

        description   = row.get(desc_col, "").strip() if desc_col else ""
        counterparty  = row.get(cp_col, "").strip()   if cp_col   else ""
        iban          = row.get(iban_col, "").strip()  if iban_col else ""
        category_name = row.get(cat_col, "").strip()   if cat_col  else ""

        balance = None
        if bal_col:
            bal_raw = row.get(bal_col, "").strip().replace(",", ".").replace(" ", "")
            try:
                balance = Decimal(bal_raw)
            except InvalidOperation:
                pass

        ptx = ParsedTransaction(
            date=parsed_date,
            amount=amount,
            currency="EUR",
            description=description or None,
            counterparty=counterparty or None,
            counterparty_iban=iban or None,
            balance_after=balance,
        )
        ptx._category_name = category_name  # type: ignore[attr-defined]
        parsed.append(ptx)
    return parsed


def _build_preview(parsed: list[ParsedTransaction], existing_hashes: set) -> tuple[list[dict], str]:
    """Return (preview_rows for template, base64 tx_data for hidden form field)."""
    preview_rows = []
    tx_data_list = []
    for p in parsed:
        is_dup = p.import_hash in existing_hashes
        preview_rows.append({
            "date": p.date.isoformat(),
            "amount": str(p.amount),
            "description": p.description or "",
            "counterparty": p.counterparty or "",
            "is_duplicate": is_dup,
        })
        tx_data_list.append({
            "date": p.date.isoformat(),
            "amount": str(p.amount),
            "currency": p.currency,
            "description": p.description,
            "counterparty": p.counterparty,
            "counterparty_iban": p.counterparty_iban,
            "balance_after": str(p.balance_after) if p.balance_after is not None else None,
            "import_hash": p.import_hash,
            "category_name": getattr(p, "_category_name", "") or "",
        })
    tx_data = base64.b64encode(json.dumps(tx_data_list).encode()).decode()
    return preview_rows, tx_data

PER_PAGE = 50


def _build_tx_query(db, user, account_id, category_id, tag_id, search,
                    date_from, date_to, amount_min, amount_max):
    """Shared filter logic used by list view, export, and duplicates."""
    query = (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.category), joinedload(Transaction.tags))
        .filter(Account.user_id == user.id)
    )

    split_parent_ids = (
        db.query(Transaction.parent_id)
        .filter(Transaction.parent_id.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    query = query.filter(Transaction.id.notin_(split_parent_ids))
    query = query.filter(Transaction.is_excluded == 0)
    query = query.filter(Transaction.is_projected == 0)

    if account_id:
        query = query.filter(Transaction.account_id == account_id)

    if category_id:
        if category_id == -1:
            query = query.filter(Transaction.category_id.is_(None))
        else:
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
        # Encrypted fields don't support ILIKE — filter in Python, then use IDs
        search_lower = search.strip().lower()
        all_tx_for_search = query.all()
        matching_ids = [
            tx.id for tx in all_tx_for_search
            if search_lower in (tx.description or "").lower()
            or search_lower in (tx.counterparty or "").lower()
            or search_lower in (tx.counterparty_iban or "").lower()
        ]
        query = query.filter(Transaction.id.in_(matching_ids) if matching_ids else Transaction.id == -1)

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

    return query


_NL_MONTHS = ["", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
              "Juli", "Augustus", "September", "Oktober", "November", "December"]


@router.get("/transactions")
def transaction_list(
    request: Request,
    page: int = Query(1, ge=1),
    account_id: str = Query(""),
    category_id: str = Query(""),
    tag_id: str = Query(""),
    search: str | None = Query(None),
    month: str = Query(""),        # NEW: YYYY-MM shorthand for a full month
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    amount_min: str | None = Query(None),
    amount_max: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Parse optional int query params (HTML forms send "" for empty selects)
    account_id = int(account_id) if account_id.strip() else None
    category_id = int(category_id) if category_id.strip() else None
    tag_id = int(tag_id) if tag_id.strip() else None

    # Resolve month → date_from / date_to
    current_month = month.strip()
    today = date_type.today()
    this_month = today.strftime("%Y-%m")

    if current_month and not date_from and not date_to:
        try:
            y, m = int(current_month[:4]), int(current_month[5:7])
            _, last = _calendar.monthrange(y, m)
            date_from = f"{current_month}-01"
            date_to = f"{current_month}-{last:02d}"
        except (ValueError, IndexError):
            current_month = ""

    # Compute prev/next month for navigation
    if current_month:
        y, m = int(current_month[:4]), int(current_month[5:7])
        _, last = _calendar.monthrange(y, m)
        prev_month = (date_type(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
        next_month = (date_type(y, m, last) + timedelta(days=1)).strftime("%Y-%m")
        period_label = f"{_NL_MONTHS[m]} {y}"
    else:
        # No month selected — prev goes to last month, next to this month
        first_this = date_type(today.year, today.month, 1)
        prev_month = (first_this - timedelta(days=1)).strftime("%Y-%m")
        next_month = this_month
        period_label = "Alle periodes"

    query = _build_tx_query(
        db, user, account_id, category_id, tag_id,
        search, date_from, date_to, amount_min, amount_max,
    )

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

    # Count uncategorized in current period (ignoring category filter)
    uncat_base = _build_tx_query(
        db, user, account_id, None, None, None, date_from, date_to, None, None
    )
    uncategorized_count = uncat_base.filter(Transaction.category_id.is_(None)).count()

    # Sync + fetch projected transactions for current month view
    projected_transactions = []
    if current_month:
        from app.routers.recurring import sync_projected_transactions
        y, m = int(current_month[:4]), int(current_month[5:7])
        sync_projected_transactions(user.id, y, m, db)
        proj_date_from = date_type.fromisoformat(date_from) if date_from else None
        proj_date_to = date_type.fromisoformat(date_to) if date_to else None
        proj_q = (
            db.query(Transaction)
            .join(Account)
            .options(joinedload(Transaction.category))
            .filter(Account.user_id == user.id, Transaction.is_projected == 1)
        )
        if proj_date_from:
            proj_q = proj_q.filter(Transaction.date >= proj_date_from)
        if proj_date_to:
            proj_q = proj_q.filter(Transaction.date <= proj_date_to)
        projected_transactions = proj_q.order_by(Transaction.date.asc()).all()

    filter_params = {}
    if current_month:
        filter_params["month"] = current_month
    if account_id:
        filter_params["account_id"] = account_id
    if category_id:
        filter_params["category_id"] = category_id
    if tag_id:
        filter_params["tag_id"] = tag_id
    if search:
        filter_params["search"] = search
    if not current_month:
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

    # Active recurring items for linking
    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id, RecurringTransaction.is_active == 1)
        .order_by(RecurringTransaction.name)
        .all()
    )

    return templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "categories": categories,
            "tags": tags,
            "recurring_items": recurring_items,
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
            "current_month": current_month,
            "prev_month": prev_month,
            "next_month": next_month,
            "this_month": this_month,
            "period_label": period_label,
            "uncategorized_count": uncategorized_count,
            "projected_transactions": projected_transactions,
        },
    )


@router.post("/transactions/{transaction_id}/category")
def set_category(
    request: Request,
    transaction_id: int,
    category_id: int = Form(0),
    redirect_to: str = Form("/transactions"),
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
    tx.is_reviewed = 1 if tx.category_id else 0
    db.commit()

    # Suggest creating a rule if a category was assigned and tx has a counterparty
    if category_id and tx.counterparty and redirect_to:
        sep = "&" if "?" in redirect_to else "?"
        redirect_to = f"{redirect_to}{sep}suggest_rule_tx={transaction_id}"

    return RedirectResponse(redirect_to, status_code=302)


@router.post("/transactions/{transaction_id}/exclude")
def exclude_transaction(
    request: Request,
    transaction_id: int,
    redirect_to: str = Form("/transactions"),
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

    tx.is_excluded = 1 if not tx.is_excluded else 0
    db.commit()

    return RedirectResponse(redirect_to, status_code=302)


@router.post("/transactions/{transaction_id}/link-recurring")
def link_recurring(
    request: Request,
    transaction_id: int,
    recurring_id: int = Form(0),
    redirect_to: str = Form("/transactions"),
    db: Session = Depends(get_db),
):
    """Link or unlink a transaction to/from a recurring item.
    When linking, learn from the transaction's description and try to
    auto-match similar transactions in other months.
    """
    user = require_login(request, db)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return RedirectResponse(redirect_to, status_code=302)

    if recurring_id:
        # Verify recurring item belongs to user
        item = db.query(RecurringTransaction).filter(
            RecurringTransaction.id == recurring_id,
            RecurringTransaction.user_id == user.id,
        ).first()
        if item:
            from app.routers.recurring import link_transaction_to_recurring
            link_transaction_to_recurring(tx, item)
            db.flush()
            # Find candidates for auto-matching (don't link yet — propose)
            candidates = _find_recurring_candidates(db, user.id, item, tx)
            db.commit()

            if candidates:
                # Redirect back with proposal banner
                candidate_ids = ",".join(str(c.id) for c in candidates)
                sep = "&" if "?" in redirect_to else "?"
                return RedirectResponse(
                    f"{redirect_to}{sep}recurring_proposals={candidate_ids}&recurring_item={item.id}&recurring_name={item.name}",
                    status_code=302,
                )
    else:
        # Unlink
        tx.recurring_id = None

    db.commit()
    return RedirectResponse(redirect_to, status_code=302)


@router.post("/transactions/accept-recurring-proposals")
def accept_recurring_proposals(
    request: Request,
    transaction_ids: str = Form(""),
    recurring_id: int = Form(0),
    redirect_to: str = Form("/transactions"),
    db: Session = Depends(get_db),
):
    """Accept proposed recurring matches — link all proposed transactions."""
    user = require_login(request, db)

    if not transaction_ids or not recurring_id:
        return RedirectResponse(redirect_to, status_code=302)

    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == recurring_id,
        RecurringTransaction.user_id == user.id,
    ).first()
    if not item:
        return RedirectResponse(redirect_to, status_code=302)

    tx_ids = [int(tid) for tid in transaction_ids.split(",") if tid.strip().isdigit()]
    txs = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Transaction.id.in_(tx_ids),
            Account.user_id == user.id,
            Transaction.recurring_id.is_(None),
        )
        .all()
    )
    from app.routers.recurring import link_transaction_to_recurring
    for tx in txs:
        link_transaction_to_recurring(tx, item)

    db.commit()
    return RedirectResponse(redirect_to, status_code=302)


def _find_recurring_candidates(
    db: Session, user_id: int, item: RecurringTransaction, linked_tx: Transaction
) -> list[Transaction]:
    """After a manual link, learn from the transaction's description/counterparty
    and find candidate transactions in other months that could be matched.
    Returns candidates (does NOT link them — caller decides to propose or auto-link).
    """
    # Build search words from the linked transaction (for Python filtering)
    desc = (linked_tx.description or "").strip()
    cp = (linked_tx.counterparty or "").strip()

    search_words = []
    if desc:
        item_words = item.name.lower().split()
        desc_lower = desc.lower()
        matching_words = [w for w in item_words if len(w) > 2 and w in desc_lower]
        if matching_words:
            search_words = matching_words
        elif cp:
            search_words = [cp.lower()]
        else:
            snippet = desc[:30].strip().lower()
            if len(snippet) > 5:
                search_words = [snippet]
    elif cp:
        search_words = [cp.lower()]

    if not search_words:
        return []

    # Update the recurring item's description_match if empty
    if not item.description_match and desc:
        item_words = item.name.lower().split()
        desc_lower = desc.lower()
        matching = [w for w in item_words if len(w) > 2 and w in desc_lower]
        if matching:
            item.description_match = " ".join(matching)

    # Find all unlinked transactions and filter in Python (encrypted fields)
    all_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.recurring_id.is_(None),
            Transaction.id != linked_tx.id,
        )
        .order_by(Transaction.date)
        .all()
    )
    all_candidates = []
    for tx in all_txs:
        tx_desc = (tx.description or "").lower()
        tx_cp = (tx.counterparty or "").lower()
        if all(w in tx_desc or w in tx_cp for w in search_words):
            all_candidates.append(tx)

    # Filter: one per period, same sign, no existing match
    from app.routers.recurring import _get_period_range, _find_matching_transaction

    result = []
    seen_periods = set()
    for candidate in all_candidates:
        period_start, period_end = _get_period_range(item.frequency, candidate.date)
        period_key = (period_start, period_end)
        if period_key in seen_periods:
            continue

        existing = _find_matching_transaction(db, user_id, item, period_start, period_end)
        if existing:
            seen_periods.add(period_key)
            continue

        if (candidate.amount > 0) != (linked_tx.amount > 0):
            continue

        result.append(candidate)
        seen_periods.add(period_key)

    return result


def auto_link_recurring_after_import(db: Session, user_id: int):
    """Called after CSV import — automatically link new transactions to recurring items
    based on counterparty/description matching. No user confirmation needed.
    Note: counterparty/description are encrypted, so we filter in Python."""
    from app.routers.recurring import _get_period_range, _find_matching_transaction

    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user_id, RecurringTransaction.is_active == 1)
        .all()
    )

    # Load all unlinked transactions once (avoid N+1 on encrypted fields)
    all_unlinked = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.recurring_id.is_(None),
        )
        .order_by(Transaction.date)
        .all()
    )

    for item in recurring_items:
        if not item.counterparty and not item.description_match:
            continue

        # Build search terms
        cp_term = (item.counterparty or "").lower()
        desc_words = [w.lower() for w in (item.description_match or "").split() if len(w) > 2]

        if not cp_term and not desc_words:
            continue

        for candidate in all_unlinked:
            if candidate.recurring_id:
                continue  # Already linked by a previous item in this loop

            cp = (candidate.counterparty or "").lower()
            desc = (candidate.description or "").lower()

            # Match: counterparty contains search term OR all desc words found
            match = False
            if cp_term and cp_term in cp:
                match = True
            if not match and cp_term and cp_term in desc:
                match = True
            if not match and desc_words and all(w in desc for w in desc_words):
                match = True

            if not match:
                continue

            period_start, period_end = _get_period_range(item.frequency, candidate.date)
            existing = _find_matching_transaction(db, user_id, item, period_start, period_end)
            if existing:
                continue
            from app.routers.recurring import link_transaction_to_recurring
            link_transaction_to_recurring(candidate, item)


@router.post("/transactions/{transaction_id}/reviewed")
def toggle_reviewed(
    request: Request,
    transaction_id: int,
    redirect_to: str = Form("/transactions"),
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

    tx.is_reviewed = 0 if tx.is_reviewed else 1
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
    transaction.is_reviewed = 1 if transaction.category_id else 0

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


# ===== CSV Export =====

@router.get("/transactions/export")
def export_transactions(
    request: Request,
    account_id: str = Query(""),
    category_id: str = Query(""),
    tag_id: str = Query(""),
    search: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    amount_min: str | None = Query(None),
    amount_max: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    acc_id = int(account_id) if account_id.strip() else None
    cat_id = int(category_id) if category_id.strip() else None
    tg_id  = int(tag_id) if tag_id.strip() else None

    transactions = (
        _build_tx_query(db, user, acc_id, cat_id, tg_id,
                        search, date_from, date_to, amount_min, amount_max)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["datum", "bedrag", "omschrijving", "tegenpartij", "iban_tegenpartij",
                     "categorie", "tags", "rekening", "gecontroleerd"])
    for tx in transactions:
        writer.writerow([
            tx.date.isoformat(),
            str(tx.amount),
            tx.description or "",
            tx.counterparty or "",
            tx.counterparty_iban or "",
            tx.category.name if tx.category else "",
            ";".join(t.name for t in tx.tags),
            tx.account.name,
            "ja" if tx.is_reviewed else "nee",
        ])

    output.seek(0)
    filename = f"transacties-export.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===== Bulk acties =====

@router.post("/transactions/bulk")
async def bulk_action(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    form = await request.form()

    tx_ids_raw = form.getlist("tx_ids")
    action = form.get("action", "")
    redirect_to = form.get("redirect_to", "/transactions")
    category_id_raw = form.get("bulk_category_id", "")
    tag_id_raw = form.get("bulk_tag_id", "")

    if not tx_ids_raw:
        return RedirectResponse(redirect_to, status_code=302)

    # Validate and fetch transactions belonging to this user
    tx_ids = []
    for raw in tx_ids_raw:
        try:
            tx_ids.append(int(raw))
        except (ValueError, TypeError):
            pass

    if not tx_ids:
        return RedirectResponse(redirect_to, status_code=302)

    transactions = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id.in_(tx_ids), Account.user_id == user.id)
        .all()
    )

    if action == "category":
        cat_id = int(category_id_raw) if category_id_raw.strip() else None
        for tx in transactions:
            tx.category_id = cat_id
            tx.is_reviewed = 1 if cat_id else 0

    elif action == "tag":
        tg_id = int(tag_id_raw) if tag_id_raw.strip() else None
        if tg_id:
            tag = db.query(Tag).filter(Tag.id == tg_id, Tag.user_id == user.id).first()
            if tag:
                for tx in transactions:
                    if tag not in tx.tags:
                        tx.tags.append(tag)

    elif action == "reviewed":
        for tx in transactions:
            tx.is_reviewed = 1

    elif action == "unreviewed":
        for tx in transactions:
            tx.is_reviewed = 0

    elif action == "exclude":
        for tx in transactions:
            tx.is_excluded = 1

    db.commit()
    return RedirectResponse(redirect_to, status_code=302)


# ===== Deduplicatie =====

@router.get("/transactions/duplicates")
def duplicates_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    # Find (date, amount, counterparty) combos with 2+ transactions
    dup_groups = (
        db.query(
            Transaction.date,
            Transaction.amount,
            Transaction.counterparty,
            func.count(Transaction.id).label("cnt"),
        )
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.is_excluded == 0)
        .group_by(Transaction.date, Transaction.amount, Transaction.counterparty)
        .having(func.count(Transaction.id) > 1)
        .order_by(Transaction.date.desc())
        .all()
    )

    # Fetch the actual transactions per group
    groups = []
    for grp in dup_groups:
        txs = (
            db.query(Transaction)
            .join(Account)
            .options(joinedload(Transaction.category))
            .filter(
                Account.user_id == user.id,
                Transaction.date == grp.date,
                Transaction.amount == grp.amount,
                Transaction.counterparty == grp.counterparty,
                Transaction.is_excluded == 0,
            )
            .order_by(Transaction.id)
            .all()
        )
        if len(txs) > 1:
            groups.append(txs)

    return templates.TemplateResponse(
        "transactions/duplicates.html",
        {"request": request, "user": user, "groups": groups},
    )


@router.post("/transactions/duplicates/exclude")
async def exclude_duplicates(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    form = await request.form()
    tx_ids_raw = form.getlist("tx_ids")

    for raw in tx_ids_raw:
        try:
            tx_id = int(raw)
        except (ValueError, TypeError):
            continue
        tx = (
            db.query(Transaction)
            .join(Account)
            .filter(Transaction.id == tx_id, Account.user_id == user.id)
            .first()
        )
        if tx:
            tx.is_excluded = 1

    db.commit()
    return RedirectResponse("/transactions/duplicates", status_code=302)


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
    """Step 1: parse → show preview (or column-mapper for custom CSV)."""
    user = require_login(request, db)

    content = await file.read()
    if not content:
        return templates.TemplateResponse(
            "transactions/import.html",
            {"request": request, "user": user, "banks": {k: v[0] for k, v in PARSERS.items()}, "error": "Leeg bestand"},
            status_code=400,
        )

    # ── Custom CSV: show column mapper ───────────────────────────────────────
    if bank == "custom":
        headers, csv_preview = _get_csv_headers_and_preview(content)
        if not headers:
            return templates.TemplateResponse(
                "transactions/import.html",
                {"request": request, "user": user, "banks": {k: v[0] for k, v in PARSERS.items()},
                 "error": "Kon geen kolomkoppen vinden in het CSV-bestand"},
                status_code=400,
            )
        return templates.TemplateResponse(
            "transactions/import_map.html",
            {
                "request": request, "user": user,
                "headers": headers,
                "csv_preview": csv_preview,
                "csv_data": base64.b64encode(content).decode(),
                "account_name": account_name.strip(),
                "field_options": CUSTOM_CSV_FIELDS,
            },
        )

    # ── Known bank ───────────────────────────────────────────────────────────
    if bank not in PARSERS:
        return templates.TemplateResponse(
            "transactions/import.html",
            {"request": request, "user": user, "banks": {k: v[0] for k, v in PARSERS.items()}, "error": "Onbekende bank geselecteerd"},
            status_code=400,
        )

    bank_label, parser = PARSERS[bank]
    try:
        detected_iban, parsed = parser(content)
    except ParseError as e:
        return templates.TemplateResponse(
            "transactions/import.html",
            {"request": request, "user": user, "banks": {k: v[0] for k, v in PARSERS.items()}, "error": f"Fout bij verwerken: {e}"},
            status_code=400,
        )

    if not parsed:
        return templates.TemplateResponse(
            "transactions/import.html",
            {"request": request, "user": user, "banks": {k: v[0] for k, v in PARSERS.items()}, "error": "Geen transacties gevonden in het bestand"},
            status_code=400,
        )

    existing_hashes = {row[0] for row in db.query(Transaction.import_hash).filter(
        Transaction.import_hash.in_([p.import_hash for p in parsed])
    ).all()}
    preview_rows, tx_data = _build_preview(parsed, existing_hashes)

    return templates.TemplateResponse(
        "transactions/import_preview.html",
        {
            "request": request, "user": user,
            "preview_rows": preview_rows,
            "tx_data": tx_data,
            "bank": bank,
            "bank_label": bank_label,
            "account_iban": detected_iban or "",
            "account_name": account_name.strip() or f"{bank_label} - {detected_iban or 'account'}",
            "new_count": sum(1 for r in preview_rows if not r["is_duplicate"]),
            "dup_count": sum(1 for r in preview_rows if r["is_duplicate"]),
        },
    )


@router.post("/import/map")
async def import_map(request: Request, db: Session = Depends(get_db)):
    """Step 1b (custom CSV): receive column mapping → parse → show preview."""
    user = require_login(request, db)
    form = await request.form()

    csv_data_b64 = form.get("csv_data", "")
    account_name = form.get("account_name", "").strip()

    try:
        content = base64.b64decode(csv_data_b64.encode())
    except Exception:
        return RedirectResponse("/import", status_code=302)

    col_mapping = {}
    for field, _ in CUSTOM_CSV_FIELDS:
        val = (form.get(f"col_{field}") or "").strip()
        if val:
            col_mapping[field] = val

    if "date" not in col_mapping or "amount" not in col_mapping:
        headers, csv_preview = _get_csv_headers_and_preview(content)
        return templates.TemplateResponse(
            "transactions/import_map.html",
            {
                "request": request, "user": user,
                "headers": headers, "csv_preview": csv_preview,
                "csv_data": csv_data_b64, "account_name": account_name,
                "field_options": CUSTOM_CSV_FIELDS,
                "prev_mapping": col_mapping,
                "error": "Datum en Bedrag zijn verplichte velden",
            },
        )

    parsed = _parse_custom_csv(content, col_mapping)
    if not parsed:
        headers, csv_preview = _get_csv_headers_and_preview(content)
        return templates.TemplateResponse(
            "transactions/import_map.html",
            {
                "request": request, "user": user,
                "headers": headers, "csv_preview": csv_preview,
                "csv_data": csv_data_b64, "account_name": account_name,
                "field_options": CUSTOM_CSV_FIELDS,
                "prev_mapping": col_mapping,
                "error": "Geen transacties gevonden. Controleer of de Datum- en Bedragkolommen correct zijn.",
            },
        )

    existing_hashes = {row[0] for row in db.query(Transaction.import_hash).filter(
        Transaction.import_hash.in_([p.import_hash for p in parsed])
    ).all()}
    preview_rows, tx_data = _build_preview(parsed, existing_hashes)

    return templates.TemplateResponse(
        "transactions/import_preview.html",
        {
            "request": request, "user": user,
            "preview_rows": preview_rows,
            "tx_data": tx_data,
            "bank": "custom",
            "bank_label": "Aangepast CSV",
            "account_iban": "",
            "account_name": account_name or "Aangepast account",
            "new_count": sum(1 for r in preview_rows if not r["is_duplicate"]),
            "dup_count": sum(1 for r in preview_rows if r["is_duplicate"]),
        },
    )


@router.post("/import/confirm")
async def import_confirm(request: Request, db: Session = Depends(get_db)):
    """Step 2: save confirmed transactions from preview."""
    user = require_login(request, db)
    form = await request.form()

    tx_data_b64 = form.get("tx_data", "")
    bank        = form.get("bank", "custom")
    account_iban = (form.get("account_iban") or "").strip() or None
    account_name = (form.get("account_name") or "").strip()

    try:
        tx_data = json.loads(base64.b64decode(tx_data_b64.encode()).decode())
    except Exception:
        return RedirectResponse("/import", status_code=302)

    # Find or create account
    account = db.query(Account).filter(
        Account.user_id == user.id,
        Account.bank == bank,
        Account.iban == account_iban,
    ).first()
    if not account:
        account = Account(
            user_id=user.id,
            name=account_name or f"{bank} account",
            iban=account_iban,
            bank=bank if bank in PARSERS else "custom",
        )
        db.add(account)
        db.flush()

    # Category lookup by name (for custom CSV with category column)
    categories_by_name = {
        c.name.lower(): c
        for c in db.query(Category).filter(Category.user_id == user.id).all()
    }

    active_rules = db.query(Rule).filter(Rule.user_id == user.id, Rule.is_active == 1).all()

    imported = skipped = auto_categorized = 0

    for item in tx_data:
        exists = db.query(Transaction).filter(Transaction.import_hash == item["import_hash"]).first()
        if exists:
            skipped += 1
            continue

        try:
            tx_date   = date_type.fromisoformat(item["date"])
            tx_amount = Decimal(item["amount"])
        except (ValueError, InvalidOperation):
            skipped += 1
            continue

        # Category from name
        cat_id = None
        cat_name = (item.get("category_name") or "").strip().lower()
        if cat_name and cat_name in categories_by_name:
            cat_id = categories_by_name[cat_name].id

        db_tx = Transaction(
            account_id=account.id,
            date=tx_date,
            amount=tx_amount,
            currency=item.get("currency", "EUR"),
            description=item.get("description"),
            counterparty=item.get("counterparty"),
            counterparty_iban=item.get("counterparty_iban"),
            balance_after=Decimal(item["balance_after"]) if item.get("balance_after") else None,
            import_hash=item["import_hash"],
            category_id=cat_id,
        )
        db.add(db_tx)
        db.flush()

        if cat_id:
            auto_categorized += 1
        elif active_rules and apply_rules_to_transaction(active_rules, db_tx, db):
            auto_categorized += 1

        imported += 1

    db.commit()

    # Auto-link new transactions to recurring items, then clean up projections
    auto_link_recurring_after_import(db, user.id)
    from app.routers.recurring import cleanup_matched_projected, sync_projected_transactions
    cleanup_matched_projected(user.id, db)
    # Re-sync projected transactions for current month to reflect new imports
    import datetime as _dt
    _today = _dt.date.today()
    sync_projected_transactions(user.id, _today.year, _today.month, db)
    db.commit()

    return templates.TemplateResponse(
        "transactions/import_result.html",
        {
            "request": request, "user": user,
            "imported": imported, "skipped": skipped,
            "auto_categorized": auto_categorized,
            "total": len(tx_data),
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


@router.post("/transactions/{transaction_id}/link-transfer")
def link_transfer(
    transaction_id: int,
    request: Request,
    partner_id: int = Form(...),
    redirect_to: str = Form("/transactions"),
    db: Session = Depends(get_db),
):
    """Link two transactions as a transfer pair (bidirectional)."""
    user = require_login(request, db)

    tx_a = (
        db.query(Transaction).join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    tx_b = (
        db.query(Transaction).join(Account)
        .filter(Transaction.id == partner_id, Account.user_id == user.id)
        .first()
    )

    if tx_a and tx_b and tx_a.id != tx_b.id:
        tx_a.transfer_id = tx_b.id
        tx_b.transfer_id = tx_a.id
        db.commit()

    return RedirectResponse(redirect_to, status_code=302)


@router.post("/transactions/{transaction_id}/unlink-transfer")
def unlink_transfer(
    transaction_id: int,
    request: Request,
    redirect_to: str = Form("/transactions"),
    db: Session = Depends(get_db),
):
    """Remove the transfer link from both sides of a transfer pair."""
    user = require_login(request, db)

    tx = (
        db.query(Transaction).join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )

    if tx and tx.transfer_id:
        partner = (
            db.query(Transaction).join(Account)
            .filter(Transaction.id == tx.transfer_id, Account.user_id == user.id)
            .first()
        )
        if partner:
            partner.transfer_id = None
        tx.transfer_id = None
        db.commit()

    return RedirectResponse(redirect_to, status_code=302)


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
