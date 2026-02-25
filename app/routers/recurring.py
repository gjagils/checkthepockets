import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.models import Account, Transaction, Category, RecurringTransaction
from app.auth import require_login
from app.template_config import templates

router = APIRouter()

FREQUENCIES = {
    "weekly": "Wekelijks",
    "monthly": "Maandelijks",
    "quarterly": "Per kwartaal",
    "yearly": "Jaarlijks",
}

MONTH_NAMES_NL = [
    "", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
    "Juli", "Augustus", "September", "Oktober", "November", "December",
]


def _get_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date for the current period based on frequency."""
    if frequency == "weekly":
        start = ref_date - timedelta(days=ref_date.weekday())
        end = start + timedelta(days=6)
    elif frequency == "monthly":
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    elif frequency == "quarterly":
        q_month = ((ref_date.month - 1) // 3) * 3 + 1
        start = date(ref_date.year, q_month, 1)
        end_month = q_month + 2
        end_year = ref_date.year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        last_day = calendar.monthrange(end_year, end_month)[1]
        end = date(end_year, end_month, last_day)
    elif frequency == "yearly":
        start = date(ref_date.year, 1, 1)
        end = date(ref_date.year, 12, 31)
    else:
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    return start, end


def _find_matching_transaction(
    db: Session, user_id: int, recurring: RecurringTransaction, start: date, end: date
) -> Transaction | None:
    """Find a transaction matching this recurring item in the given period."""
    query = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.date >= start,
            Transaction.date <= end,
        )
    )

    conditions = []
    if recurring.counterparty:
        conditions.append(Transaction.counterparty.ilike(f"%{recurring.counterparty}%"))
    if recurring.description_match:
        conditions.append(Transaction.description.ilike(f"%{recurring.description_match}%"))

    if conditions:
        query = query.filter(or_(*conditions))
    else:
        return None

    return query.order_by(Transaction.date.desc()).first()


@router.get("/recurring")
def recurring_list(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = date.today()

    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id)
        .order_by(RecurringTransaction.is_active.desc(), RecurringTransaction.name)
        .all()
    )

    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )

    # Check status for each recurring item
    items_with_status = []
    for item in recurring_items:
        start, end = _get_period_range(item.frequency, today)
        match = _find_matching_transaction(db, user.id, item, start, end)

        items_with_status.append({
            "item": item,
            "period_start": start,
            "period_end": end,
            "matched_transaction": match,
            "is_due": match is None and item.is_active,
        })

    # Summary
    total_active = sum(1 for i in items_with_status if i["item"].is_active)
    total_due = sum(1 for i in items_with_status if i["is_due"])
    total_confirmed = sum(1 for i in items_with_status if i["matched_transaction"] and i["item"].is_active)

    return templates.TemplateResponse(
        "recurring/list.html",
        {
            "request": request,
            "user": user,
            "items": items_with_status,
            "categories": categories,
            "frequencies": FREQUENCIES,
            "total_active": total_active,
            "total_due": total_due,
            "total_confirmed": total_confirmed,
            "today": today,
        },
    )


@router.post("/recurring")
def create_recurring(
    request: Request,
    name: str = Form(...),
    amount_expected: str = Form(...),
    frequency: str = Form(...),
    category_id: str = Form(""),
    counterparty: str = Form(""),
    description_match: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse("/recurring", status_code=302)
    if frequency not in FREQUENCIES:
        return RedirectResponse("/recurring", status_code=302)

    try:
        parsed_amount = Decimal(amount_expected.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse("/recurring", status_code=302)

    cat_id = int(category_id) if category_id.strip() else None
    if cat_id:
        cat = db.query(Category).filter(
            Category.id == cat_id, Category.user_id == user.id
        ).first()
        if not cat:
            cat_id = None

    item = RecurringTransaction(
        user_id=user.id,
        name=name,
        amount_expected=parsed_amount,
        frequency=frequency,
        category_id=cat_id,
        counterparty=counterparty.strip() or None,
        description_match=description_match.strip() or None,
    )
    db.add(item)
    db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/edit")
def edit_recurring(
    item_id: int,
    request: Request,
    name: str = Form(...),
    amount_expected: str = Form(...),
    frequency: str = Form(...),
    category_id: str = Form(""),
    counterparty: str = Form(""),
    description_match: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse("/recurring", status_code=302)

    name = name.strip()
    if not name:
        return RedirectResponse("/recurring", status_code=302)

    try:
        parsed_amount = Decimal(amount_expected.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse("/recurring", status_code=302)

    item.name = name
    item.amount_expected = parsed_amount
    item.frequency = frequency if frequency in FREQUENCIES else item.frequency
    item.counterparty = counterparty.strip() or None
    item.description_match = description_match.strip() or None

    cat_id = int(category_id) if category_id.strip() else None
    if cat_id:
        cat = db.query(Category).filter(
            Category.id == cat_id, Category.user_id == user.id
        ).first()
        item.category_id = cat.id if cat else None
    else:
        item.category_id = None

    db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/toggle")
def toggle_recurring(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if item:
        item.is_active = 0 if item.is_active else 1
        db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/delete")
def delete_recurring(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/recurring", status_code=302)
