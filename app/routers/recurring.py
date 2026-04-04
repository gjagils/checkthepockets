import calendar
import hashlib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import List

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

NL_MONTH_ABBREVS = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]

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


def _get_previous_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date of the period BEFORE the current one."""
    current_start, _ = _get_period_range(frequency, ref_date)
    prev_date = current_start - timedelta(days=1)
    return _get_period_range(frequency, prev_date)


def _find_matching_transaction(
    db: Session, user_id: int, recurring: RecurringTransaction, start: date, end: date
) -> Transaction | None:
    """Find a transaction matching this recurring item in the given period.
    Checks both auto-matching (counterparty/description) and manual links (recurring_id).
    """
    # First: check manually linked transactions
    linked = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.recurring_id == recurring.id,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .first()
    )
    if linked:
        return linked

    # Fall back to auto-matching by counterparty/description
    conditions = []
    if recurring.counterparty:
        conditions.append(Transaction.counterparty.ilike(f"%{recurring.counterparty}%"))
    if recurring.description_match:
        conditions.append(Transaction.description.ilike(f"%{recurring.description_match}%"))

    if not conditions:
        return None

    return (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            or_(*conditions),
        )
        .order_by(Transaction.date.desc())
        .first()
    )


def _parse_active_months(values: List[str]) -> str | None:
    """Convert list of month number strings to stored comma-separated string, or None for all."""
    nums = sorted({int(v) for v in values if v.isdigit() and 1 <= int(v) <= 12})
    if len(nums) == 12:
        return None  # all months = no restriction
    return ",".join(str(m) for m in nums) if nums else None


def _active_months_set(item: RecurringTransaction) -> set[int]:
    """Return the set of active month numbers for a recurring item (1-12). Empty = all."""
    if not item.active_months:
        return set(range(1, 13))
    try:
        return {int(m) for m in item.active_months.split(",") if m.strip()}
    except ValueError:
        return set(range(1, 13))


def _is_in_active_period(item: RecurringTransaction, today: date) -> bool:
    """Check if a recurring item is within its configured active period."""
    if item.start_date and item.start_date > today:
        return False
    if item.end_date and item.end_date < today:
        return False
    months = _active_months_set(item)
    if today.month not in months:
        return False
    return True


def _is_active_in_month(item: RecurringTransaction, year: int, month: int) -> bool:
    """Check if a recurring item should be active in the given year/month."""
    ref = date(year, month, 1)
    if item.start_date and item.start_date > date(year, month, calendar.monthrange(year, month)[1]):
        return False
    if item.end_date and item.end_date < ref:
        return False
    months = _active_months_set(item)
    if month not in months:
        return False
    return True


def sync_projected_transactions(user_id: int, year: int, month: int, db: Session) -> None:
    """
    For the given month:
    - Create projected Transaction placeholders for active recurring items with no real match.
    - Delete projected placeholders where a real transaction now exists.
    """
    ref = date(year, month, 1)

    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user_id, RecurringTransaction.is_active == 1)
        .all()
    )

    # Need at least one account to attach projected transactions to
    default_account = (
        db.query(Account)
        .filter(Account.user_id == user_id)
        .order_by(Account.id)
        .first()
    )
    if not default_account:
        return

    changed = False
    for item in recurring_items:
        if not _is_active_in_month(item, year, month):
            # Clean up any stale projected tx for this item+period
            proj_hash = f"projected-{item.id}-{year}-{month:02d}"
            stale = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
            if stale:
                db.delete(stale)
                changed = True
            continue

        # Determine the period for this item's frequency in the given month
        period_start, period_end = _get_period_range(item.frequency, ref)
        proj_hash = f"projected-{item.id}-{period_start.isoformat()}"

        # Check if a real (non-projected) transaction already matches
        real_tx = _find_matching_transaction(db, user_id, item, period_start, period_end)

        if real_tx:
            # Real match exists — delete projected placeholder if present
            proj = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
            if proj:
                db.delete(proj)
                changed = True
        else:
            # No real match — ensure projected placeholder exists
            proj = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
            if not proj:
                # Determine account: prefer recurring item's category account, else default
                db.add(Transaction(
                    account_id=default_account.id,
                    date=period_start,
                    amount=item.amount_expected,
                    currency="EUR",
                    description=item.name,
                    counterparty=item.counterparty or item.name,
                    import_hash=proj_hash,
                    is_projected=1,
                    is_excluded=0,
                    category_id=item.category_id,
                    recurring_id=item.id,
                ))
                changed = True

    if changed:
        db.commit()


def cleanup_matched_projected(user_id: int, db: Session) -> None:
    """Delete projected transactions that now have a matching real transaction."""
    projected = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id, Transaction.is_projected == 1)
        .all()
    )
    changed = False
    for proj in projected:
        if not proj.recurring_id:
            db.delete(proj)
            changed = True
            continue
        item = db.query(RecurringTransaction).filter(
            RecurringTransaction.id == proj.recurring_id
        ).first()
        if not item:
            db.delete(proj)
            changed = True
            continue
        period_start, period_end = _get_period_range(item.frequency, proj.date)
        real_tx = _find_matching_transaction(db, user_id, item, period_start, period_end)
        if real_tx:
            db.delete(proj)
            changed = True
    if changed:
        db.commit()


@router.get("/recurring")
def recurring_list(
    request: Request,
    from_tx: int = Query(None),
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

    items_active = []    # active period, matched this period
    items_due = []       # active period, not matched yet (current period still ongoing)
    items_missed = []    # active period, previous period was NOT matched (overdue)
    items_inactive = []  # is_active=0 or outside active period

    for item in recurring_items:
        in_period = _is_in_active_period(item, today)

        if not item.is_active or not in_period:
            cur_start, cur_end = _get_period_range(item.frequency, today)
            match = _find_matching_transaction(db, user.id, item, cur_start, cur_end)
            items_inactive.append({
                "item": item,
                "period_start": cur_start,
                "period_end": cur_end,
                "matched_transaction": match,
                "is_due": False,
                "in_active_period": in_period,
            })
            continue

        cur_start, cur_end = _get_period_range(item.frequency, today)
        cur_match = _find_matching_transaction(db, user.id, item, cur_start, cur_end)

        prev_start, prev_end = _get_previous_period_range(item.frequency, today)
        prev_match = _find_matching_transaction(db, user.id, item, prev_start, prev_end)

        entry = {
            "item": item,
            "period_start": cur_start,
            "period_end": cur_end,
            "matched_transaction": cur_match,
            "prev_period_start": prev_start,
            "prev_period_end": prev_end,
            "prev_matched_transaction": prev_match,
            "is_due": cur_match is None,
            "in_active_period": True,
        }

        if cur_match:
            items_active.append(entry)
        elif prev_match is None:
            items_missed.append(entry)
        else:
            items_due.append(entry)

    total_active = len(items_active)
    total_due = len(items_due)
    total_missed = len(items_missed)

    prefill = None
    if from_tx:
        tx = (
            db.query(Transaction)
            .join(Account)
            .filter(Transaction.id == from_tx, Account.user_id == user.id)
            .first()
        )
        if tx:
            prefill = {
                "name": tx.counterparty or tx.description or "",
                "amount_expected": float(tx.amount),
                "category_id": tx.category_id or "",
                "counterparty": tx.counterparty or "",
                "tx_display": f"{tx.counterparty or tx.description or '?'}  ·  €{tx.amount}",
            }

    return templates.TemplateResponse(
        "recurring/list.html",
        {
            "request": request,
            "user": user,
            "items_active": items_active,
            "items_due": items_due,
            "items_missed": items_missed,
            "items_inactive": items_inactive,
            "categories": categories,
            "frequencies": FREQUENCIES,
            "nl_month_abbrevs": NL_MONTH_ABBREVS,
            "total_active": total_active,
            "total_due": total_due,
            "total_missed": total_missed,
            "today": today,
            "prefill": prefill,
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
    start_date: str = Form(""),
    end_date: str = Form(""),
    active_months: List[str] = Form(default=[]),
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

    from datetime import date as date_type
    parsed_start = None
    parsed_end = None
    try:
        if start_date.strip():
            parsed_start = date_type.fromisoformat(start_date.strip())
        if end_date.strip():
            parsed_end = date_type.fromisoformat(end_date.strip())
    except ValueError:
        pass

    item = RecurringTransaction(
        user_id=user.id,
        name=name,
        amount_expected=parsed_amount,
        frequency=frequency,
        category_id=cat_id,
        counterparty=counterparty.strip() or None,
        description_match=description_match.strip() or None,
        start_date=parsed_start,
        end_date=parsed_end,
        active_months=_parse_active_months(active_months),
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
    start_date: str = Form(""),
    end_date: str = Form(""),
    active_months: List[str] = Form(default=[]),
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

    from datetime import date as date_type
    parsed_start = None
    parsed_end = None
    try:
        if start_date.strip():
            parsed_start = date_type.fromisoformat(start_date.strip())
        if end_date.strip():
            parsed_end = date_type.fromisoformat(end_date.strip())
    except ValueError:
        pass

    item.name = name
    item.amount_expected = parsed_amount
    item.frequency = frequency if frequency in FREQUENCIES else item.frequency
    item.counterparty = counterparty.strip() or None
    item.description_match = description_match.strip() or None
    item.start_date = parsed_start
    item.end_date = parsed_end
    item.active_months = _parse_active_months(active_months)

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


@router.post("/recurring/{item_id}/link")
def link_transaction(
    item_id: int,
    request: Request,
    transaction_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Manually link a transaction to a recurring item."""
    user = require_login(request, db)

    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse("/recurring", status_code=302)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if tx:
        tx.recurring_id = item.id
        db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/unlink")
def unlink_transaction(
    item_id: int,
    request: Request,
    transaction_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Remove manual link between a transaction and a recurring item."""
    user = require_login(request, db)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if tx and tx.recurring_id == item_id:
        tx.recurring_id = None
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
