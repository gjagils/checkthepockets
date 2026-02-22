import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.database import get_db
from app.models import Account, Transaction, Category, Budget
from app.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MONTH_NAMES_NL = [
    "", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
    "Juli", "Augustus", "September", "Oktober", "November", "December",
]


def _get_spending_by_category(db: Session, user_id: int, year: int, month: int) -> dict[int, Decimal]:
    """Get total spending (negative amounts) per category for a given month."""
    rows = (
        db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total"),
        )
        .join(Account)
        .filter(
            Account.user_id == user_id,
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.category_id.isnot(None),
            Transaction.amount < 0,
        )
        .group_by(Transaction.category_id)
        .all()
    )
    return {cat_id: abs(total) for cat_id, total in rows}


@router.get("/budgets")
def budget_overview(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    today = date.today()
    y = year or today.year
    m = month or today.month

    # Clamp month
    if m < 1:
        m = 12
        y -= 1
    elif m > 12:
        m = 1
        y += 1

    # Previous / next month
    prev_m, prev_y = (m - 1, y) if m > 1 else (12, y - 1)
    next_m, next_y = (m + 1, y) if m < 12 else (1, y + 1)

    # Days progress in month
    days_in_month = calendar.monthrange(y, m)[1]
    if y == today.year and m == today.month:
        day_progress = today.day / days_in_month
    elif date(y, m, 1) < today:
        day_progress = 1.0
    else:
        day_progress = 0.0

    # Load budgets and spending
    budgets = (
        db.query(Budget)
        .filter(Budget.user_id == user.id)
        .all()
    )
    spending = _get_spending_by_category(db, user.id, y, m)

    # Also include child category spending under parent budget
    categories_by_id = {}
    all_cats = db.query(Category).filter(Category.user_id == user.id).all()
    for cat in all_cats:
        categories_by_id[cat.id] = cat

    # Build budget lines
    budget_lines = []
    total_budgeted = Decimal("0")
    total_spent = Decimal("0")

    for b in budgets:
        cat = categories_by_id.get(b.category_id)
        if not cat:
            continue

        # Sum spending for this category + children
        cat_ids = [cat.id] + [c.id for c in cat.children]
        spent = sum(spending.get(cid, Decimal("0")) for cid in cat_ids)
        pct = float(spent / b.amount * 100) if b.amount else 0

        total_budgeted += b.amount
        total_spent += spent

        budget_lines.append({
            "budget": b,
            "category": cat,
            "spent": spent,
            "remaining": b.amount - spent,
            "pct": min(pct, 100),
            "over": spent > b.amount,
            "over_amount": spent - b.amount if spent > b.amount else Decimal("0"),
        })

    budget_lines.sort(key=lambda x: x["category"].name)

    # Categories without a budget (for the add form)
    budgeted_cat_ids = {b.category_id for b in budgets}
    available_categories = [
        c for c in all_cats
        if c.id not in budgeted_cat_ids
    ]
    available_categories.sort(key=lambda c: c.name)

    return templates.TemplateResponse(
        "budgets/overview.html",
        {
            "request": request,
            "user": user,
            "budget_lines": budget_lines,
            "available_categories": available_categories,
            "year": y,
            "month": m,
            "month_name": MONTH_NAMES_NL[m],
            "prev_year": prev_y,
            "prev_month": prev_m,
            "next_year": next_y,
            "next_month": next_m,
            "is_current_month": y == today.year and m == today.month,
            "day_progress": day_progress,
            "total_budgeted": total_budgeted,
            "total_spent": total_spent,
            "total_remaining": total_budgeted - total_spent,
        },
    )


@router.post("/budgets")
def create_budget(
    request: Request,
    category_id: int = Form(...),
    amount: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Validate category belongs to user
    cat = db.query(Category).filter(
        Category.id == category_id, Category.user_id == user.id
    ).first()
    if not cat:
        return RedirectResponse("/budgets", status_code=302)

    # Parse amount
    try:
        parsed_amount = Decimal(amount.strip().replace(",", "."))
        if parsed_amount <= 0:
            return RedirectResponse("/budgets", status_code=302)
    except (InvalidOperation, ValueError):
        return RedirectResponse("/budgets", status_code=302)

    # Check for existing budget on this category
    existing = db.query(Budget).filter(
        Budget.user_id == user.id, Budget.category_id == category_id
    ).first()
    if existing:
        existing.amount = parsed_amount
    else:
        budget = Budget(
            user_id=user.id,
            category_id=category_id,
            amount=parsed_amount,
        )
        db.add(budget)

    db.commit()
    return RedirectResponse("/budgets", status_code=302)


@router.post("/budgets/{budget_id}/edit")
def edit_budget(
    budget_id: int,
    request: Request,
    amount: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    budget = db.query(Budget).filter(
        Budget.id == budget_id, Budget.user_id == user.id
    ).first()
    if not budget:
        return RedirectResponse("/budgets", status_code=302)

    try:
        parsed_amount = Decimal(amount.strip().replace(",", "."))
        if parsed_amount <= 0:
            return RedirectResponse("/budgets", status_code=302)
    except (InvalidOperation, ValueError):
        return RedirectResponse("/budgets", status_code=302)

    budget.amount = parsed_amount
    db.commit()
    return RedirectResponse("/budgets", status_code=302)


@router.post("/budgets/{budget_id}/delete")
def delete_budget(
    budget_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    budget = db.query(Budget).filter(
        Budget.id == budget_id, Budget.user_id == user.id
    ).first()
    if budget:
        db.delete(budget)
        db.commit()
    return RedirectResponse("/budgets", status_code=302)
