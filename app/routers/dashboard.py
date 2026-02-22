import calendar
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.database import get_db
from app.models import Account, Transaction, Category, Budget, RecurringTransaction
from app.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]
MONTH_NAMES_FULL = [
    "", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
    "Juli", "Augustus", "September", "Oktober", "November", "December",
]


def _split_parent_ids_subquery(db: Session):
    """Subquery for transaction IDs that have been split (have children)."""
    return (
        db.query(Transaction.parent_id)
        .filter(Transaction.parent_id.isnot(None))
        .distinct()
        .subquery()
    )


@router.get("/dashboard")
def dashboard(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = date.today()
    y = year or today.year
    m = month or today.month

    if m < 1:
        m = 12
        y -= 1
    elif m > 12:
        m = 1
        y += 1

    prev_m, prev_y = (m - 1, y) if m > 1 else (12, y - 1)
    next_m, next_y = (m + 1, y) if m < 12 else (1, y + 1)

    split_ids = _split_parent_ids_subquery(db)

    # === Income vs Expenses for selected month ===
    month_totals = (
        db.query(
            func.sum(func.case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))).label("income"),
            func.sum(func.case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))).label("expenses"),
            func.count(Transaction.id).label("count"),
        )
        .join(Account)
        .filter(
            Account.user_id == user.id,
            extract("year", Transaction.date) == y,
            extract("month", Transaction.date) == m,
            Transaction.id.notin_(split_ids),
        )
        .first()
    )

    income = month_totals.income or Decimal("0")
    expenses = abs(month_totals.expenses or Decimal("0"))
    net = income - expenses
    tx_count = month_totals.count or 0

    # === Spending by category (top categories) ===
    cat_spending_rows = (
        db.query(
            Category.id,
            Category.name,
            Category.color,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Account.user_id == user.id,
            extract("year", Transaction.date) == y,
            extract("month", Transaction.date) == m,
            Transaction.amount < 0,
            Transaction.id.notin_(split_ids),
        )
        .group_by(Category.id, Category.name, Category.color)
        .order_by(func.sum(Transaction.amount).asc())
        .all()
    )

    # Uncategorized spending
    uncat = (
        db.query(func.sum(Transaction.amount))
        .join(Account)
        .filter(
            Account.user_id == user.id,
            extract("year", Transaction.date) == y,
            extract("month", Transaction.date) == m,
            Transaction.amount < 0,
            Transaction.category_id.is_(None),
            Transaction.id.notin_(split_ids),
        )
        .scalar()
    )
    uncat_amount = abs(uncat) if uncat else Decimal("0")

    cat_spending = []
    max_cat_amount = Decimal("0")
    for cat_id, cat_name, cat_color, total, count in cat_spending_rows:
        amt = abs(total)
        if amt > max_cat_amount:
            max_cat_amount = amt
        cat_spending.append({
            "id": cat_id,
            "name": cat_name,
            "color": cat_color or "#1F6FB2",
            "amount": amt,
            "count": count,
        })

    if uncat_amount > max_cat_amount:
        max_cat_amount = uncat_amount

    # Calculate bar widths relative to max
    for cs in cat_spending:
        cs["pct"] = float(cs["amount"] / max_cat_amount * 100) if max_cat_amount else 0

    if uncat_amount > 0:
        cat_spending.append({
            "id": None,
            "name": "Zonder categorie",
            "color": "#999999",
            "amount": uncat_amount,
            "count": 0,
            "pct": float(uncat_amount / max_cat_amount * 100) if max_cat_amount else 0,
        })

    # === Monthly trend (last 6 months) ===
    trend_months = []
    for i in range(5, -1, -1):
        tm = m - i
        ty = y
        while tm <= 0:
            tm += 12
            ty -= 1

        row = (
            db.query(
                func.sum(func.case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))).label("inc"),
                func.sum(func.case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))).label("exp"),
            )
            .join(Account)
            .filter(
                Account.user_id == user.id,
                extract("year", Transaction.date) == ty,
                extract("month", Transaction.date) == tm,
                Transaction.id.notin_(split_ids),
            )
            .first()
        )

        t_inc = row.inc or Decimal("0")
        t_exp = abs(row.exp or Decimal("0"))

        trend_months.append({
            "label": f"{MONTH_NAMES_NL[tm]}",
            "year": ty,
            "month": tm,
            "income": t_inc,
            "expenses": t_exp,
            "net": t_inc - t_exp,
        })

    # Max for trend chart scaling
    trend_max = max(
        (max(t["income"], t["expenses"]) for t in trend_months),
        default=Decimal("1"),
    )
    if trend_max == 0:
        trend_max = Decimal("1")

    for t in trend_months:
        t["income_pct"] = float(t["income"] / trend_max * 100)
        t["expenses_pct"] = float(t["expenses"] / trend_max * 100)

    # === Recurring status ===
    recurring_items = (
        db.query(RecurringTransaction)
        .filter(
            RecurringTransaction.user_id == user.id,
            RecurringTransaction.is_active == 1,
        )
        .all()
    )

    # === Budget usage summary ===
    budgets = db.query(Budget).filter(Budget.user_id == user.id).all()
    budget_total = sum(b.amount for b in budgets) if budgets else Decimal("0")
    budget_used_pct = float(expenses / budget_total * 100) if budget_total else 0

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "year": y,
            "month": m,
            "month_name": MONTH_NAMES_FULL[m],
            "prev_year": prev_y,
            "prev_month": prev_m,
            "next_year": next_y,
            "next_month": next_m,
            "is_current_month": y == today.year and m == today.month,
            "income": income,
            "expenses": expenses,
            "net": net,
            "tx_count": tx_count,
            "cat_spending": cat_spending,
            "trend_months": trend_months,
            "recurring_count": len(recurring_items),
            "budget_total": budget_total,
            "budget_used_pct": min(budget_used_pct, 100),
        },
    )
