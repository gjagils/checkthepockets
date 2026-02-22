import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Account, Transaction, Category
from app.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]


@router.get("/dashboard")
def dashboard(
    request: Request,
    year: int = Query(0),
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Base transaction filter
    tx_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
    ]
    if account_id:
        tx_filter.append(Transaction.account_id == account_id)

    # Total income / expenses
    totals = (
        db.query(
            func.sum(
                func.case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))
            ).label("income"),
            func.sum(
                func.case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))
            ).label("expenses"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Account)
        .filter(*tx_filter)
        .first()
    )

    income = totals.income or Decimal("0")
    expenses = totals.expenses or Decimal("0")
    tx_count = totals.tx_count or 0
    balance = income + expenses

    # Monthly totals
    monthly = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.sum(
                func.case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))
            ).label("income"),
            func.sum(
                func.case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))
            ).label("expenses"),
        )
        .join(Account)
        .filter(*tx_filter)
        .group_by(func.extract("month", Transaction.date))
        .order_by(func.extract("month", Transaction.date))
        .all()
    )

    monthly_data = {}
    for row in monthly:
        m = int(row.month)
        monthly_data[m] = {
            "income": row.income or Decimal("0"),
            "expenses": row.expenses or Decimal("0"),
        }

    # Top spending categories (subcategories)
    top_categories = (
        db.query(
            Category.name,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*tx_filter, Transaction.amount < 0)
        .group_by(Category.name)
        .order_by(func.sum(Transaction.amount))
        .limit(10)
        .all()
    )

    # Years with transactions for selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "years": years,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "income": income,
            "expenses": expenses,
            "balance": balance,
            "tx_count": tx_count,
            "monthly_data": monthly_data,
            "months": MONTH_NAMES_NL,
            "top_categories": top_categories,
        },
    )
