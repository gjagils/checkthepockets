import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import case, func, or_, and_

from app.database import get_db
from app.models import Account, Transaction, Category
from app.auth import require_login
from app.template_config import templates

router = APIRouter()

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]


@router.get("/analytics")
def analytics(
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

    # Base filter
    tx_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.transfer_id.is_(None),
    ]
    if account_id:
        tx_filter.append(Transaction.account_id == account_id)

    # Monthly income vs expenses trend (exclude_from_totals categories excluded)
    monthly_trend = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.sum(
                case(
                    (Transaction.amount > 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("income"),
            func.sum(
                case(
                    (Transaction.amount < 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*tx_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .group_by(func.extract("month", Transaction.date))
        .order_by(func.extract("month", Transaction.date))
        .all()
    )

    trend_data = {}
    for row in monthly_trend:
        m = int(row.month)
        inc = row.income or Decimal("0")
        exp = row.expenses or Decimal("0")
        trend_data[m] = {
            "income": inc,
            "expenses": exp,
            "balance": inc + exp,
        }

    # Category spending per month (top 10 categories)
    cat_monthly = (
        db.query(
            Category.id,
            Category.name,
            func.extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*tx_filter, Transaction.amount < 0, Category.exclude_from_totals == 0)
        .group_by(Category.id, Category.name, func.extract("month", Transaction.date))
        .all()
    )

    # Aggregate by category
    cat_totals = {}
    cat_by_month = {}
    for row in cat_monthly:
        cid = row.id
        cname = row.name
        m = int(row.month)
        total = abs(row.total)

        if cid not in cat_totals:
            cat_totals[cid] = {"name": cname, "total": Decimal("0")}
            cat_by_month[cid] = {}
        cat_totals[cid]["total"] += total
        cat_by_month[cid][m] = total

    # Sort by total spending and take top 10
    top_cat_ids = sorted(cat_totals, key=lambda x: cat_totals[x]["total"], reverse=True)[:10]

    categories_trend = []
    for cid in top_cat_ids:
        monthly = {}
        for m in range(1, 13):
            monthly[m] = cat_by_month.get(cid, {}).get(m, Decimal("0"))
        categories_trend.append({
            "name": cat_totals[cid]["name"],
            "total": cat_totals[cid]["total"],
            "monthly": monthly,
        })

    # Find max monthly spend for bar scaling
    max_cat_monthly = Decimal("0")
    for cat in categories_trend:
        for m in range(1, 13):
            if cat["monthly"][m] > max_cat_monthly:
                max_cat_monthly = cat["monthly"][m]

    # Years for selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    return templates.TemplateResponse(
        "analytics/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "years": years,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "trend_data": trend_data,
            "categories_trend": categories_trend,
            "max_cat_monthly": max_cat_monthly,
            "months": MONTH_NAMES_NL,
        },
    )


@router.get("/analytics/stats")
def analytics_stats(
    request: Request,
    year: int = Query(0),
    month: int = Query(0),
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year
    current_month = month  # 0 = full year

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Base filter
    base_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.transfer_id.is_(None),
        Transaction.is_projected == 0,
    ]
    if current_month:
        base_filter.append(func.extract("month", Transaction.date) == current_month)
    if account_id:
        base_filter.append(Transaction.account_id == account_id)

    # Top merchants by total spending (expenses only)
    top_merchants = (
        db.query(
            Transaction.counterparty,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Account)
        .filter(*base_filter, Transaction.amount < 0, Transaction.counterparty.isnot(None), Transaction.counterparty != "")
        .group_by(Transaction.counterparty)
        .order_by(func.sum(Transaction.amount))
        .limit(15)
        .all()
    )

    # Top categories by spending
    top_categories = (
        db.query(
            Category.name,
            Category.color,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*base_filter, Transaction.amount < 0, Category.exclude_from_totals == 0)
        .group_by(Category.id, Category.name, Category.color)
        .order_by(func.sum(Transaction.amount))
        .limit(10)
        .all()
    )

    # New counterparties this period (not seen in any previous month of this year)
    # Find all counterparties that appear this month but NOT before this period
    if current_month:
        # Counterparties seen before this month in the same year
        seen_before = db.query(Transaction.counterparty).join(Account).filter(
            Account.user_id == user.id,
            Transaction.counterparty.isnot(None),
            Transaction.counterparty != "",
            func.extract("year", Transaction.date) == current_year,
            func.extract("month", Transaction.date) < current_month,
        ).distinct().subquery()

        new_counterparties_q = (
            db.query(
                Transaction.counterparty,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("tx_count"),
            )
            .join(Account)
            .filter(
                *base_filter,
                Transaction.counterparty.isnot(None),
                Transaction.counterparty != "",
                Transaction.counterparty.notin_(
                    db.query(seen_before.c.counterparty)
                ),
            )
            .group_by(Transaction.counterparty)
            .order_by(func.count(Transaction.id).desc())
            .limit(10)
            .all()
        )
    else:
        # For full year: counterparties not seen in any previous year
        seen_before_year = db.query(Transaction.counterparty).join(Account).filter(
            Account.user_id == user.id,
            Transaction.counterparty.isnot(None),
            Transaction.counterparty != "",
            func.extract("year", Transaction.date) < current_year,
        ).distinct().subquery()

        new_counterparties_q = (
            db.query(
                Transaction.counterparty,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("tx_count"),
            )
            .join(Account)
            .filter(
                *base_filter,
                Transaction.counterparty.isnot(None),
                Transaction.counterparty != "",
                Transaction.counterparty.notin_(
                    db.query(seen_before_year.c.counterparty)
                ),
            )
            .group_by(Transaction.counterparty)
            .order_by(func.count(Transaction.id).desc())
            .limit(10)
            .all()
        )

    new_counterparties = [
        {
            "counterparty": r.counterparty,
            "total": r.total or Decimal("0"),
            "tx_count": r.tx_count or 0,
        }
        for r in new_counterparties_q
    ]

    # Total income/expenses for context
    totals = (
        db.query(
            func.sum(case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))).label("income"),
            func.sum(case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))).label("expenses"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*base_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .first()
    )

    # Years selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    MONTH_NAMES_NL_FULL = {
        0: "Heel jaar",
        1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
        9: "September", 10: "Oktober", 11: "November", 12: "December",
    }

    return templates.TemplateResponse(
        "analytics/stats.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": current_month,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "top_merchants": top_merchants,
            "top_categories": top_categories,
            "new_counterparties": new_counterparties,
            "total_income": totals.income or Decimal("0"),
            "total_expenses": totals.expenses or Decimal("0"),
            "total_tx_count": totals.tx_count or 0,
        },
    )
