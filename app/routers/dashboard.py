import calendar
import datetime
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import case, func, or_

from app.database import get_db
from app.models import Account, Transaction, Category, RecurringTransaction, Budget
from app.auth import require_login
from app.template_config import templates

router = APIRouter()

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]


MONTH_NAMES_NL_FULL = {
    0: "Heel jaar",
    1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
    9: "September", 10: "Oktober", 11: "November", 12: "December",
}


@router.get("/dashboard")
def dashboard(
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

    # Base transaction filter
    tx_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.transfer_id.is_(None),
    ]
    if current_month:
        tx_filter.append(func.extract("month", Transaction.date) == current_month)
    if account_id:
        tx_filter.append(Transaction.account_id == account_id)

    # Total income / expenses (exclude categories marked as exclude_from_totals)
    totals = (
        db.query(
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
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*tx_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .first()
    )

    income = totals.income or Decimal("0")
    expenses = totals.expenses or Decimal("0")
    tx_count = totals.tx_count or 0
    balance = income + expenses

    # Savings rate: (income + expenses) / income * 100
    if income > 0:
        savings_rate = (balance / income * 100).quantize(Decimal("0.1"))
    else:
        savings_rate = Decimal("0")

    # Monthly totals (only shown when viewing full year)
    monthly_data = {}
    if not current_month:
        monthly_filter = [
            Account.user_id == user.id,
            func.extract("year", Transaction.date) == current_year,
            Transaction.is_excluded == 0,
            Transaction.transfer_id.is_(None),
        ]
        if account_id:
            monthly_filter.append(Transaction.account_id == account_id)

        monthly = (
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
            .filter(*monthly_filter)
            .group_by(func.extract("month", Transaction.date))
            .order_by(func.extract("month", Transaction.date))
            .all()
        )

        for row in monthly:
            m = int(row.month)
            monthly_data[m] = {
                "income": row.income or Decimal("0"),
                "expenses": row.expenses or Decimal("0"),
            }

    # Top spending categories (subcategories) - kept for bar chart
    top_categories = (
        db.query(
            Category.name,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*tx_filter, Transaction.amount < 0, Category.exclude_from_totals == 0)
        .group_by(Category.name)
        .order_by(func.sum(Transaction.amount))
        .limit(10)
        .all()
    )

    # Category breakdown with parent/child hierarchy for month view
    category_breakdown = []
    budget_map = {}
    if current_month:
        # Get budgets for this month
        budgets = (
            db.query(Budget)
            .filter(
                Budget.user_id == user.id,
                Budget.year == current_year,
                Budget.month == current_month,
            )
            .all()
        )
        budget_map = {b.category_id: b.amount for b in budgets}

        # Get all spending per category for this period
        cat_spending = (
            db.query(
                Category.id,
                Category.name,
                Category.parent_id,
                Category.is_income,
                Category.color,
                Category.sort_order,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("tx_count"),
            )
            .join(Transaction, Transaction.category_id == Category.id)
            .join(Account, Account.id == Transaction.account_id)
            .filter(*tx_filter, Category.exclude_from_totals == 0)
            .group_by(Category.id, Category.name, Category.parent_id, Category.is_income, Category.color, Category.sort_order)
            .all()
        )

        # Also count uncategorized
        uncat = (
            db.query(
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("tx_count"),
            )
            .join(Account)
            .filter(*tx_filter, Transaction.category_id.is_(None))
            .first()
        )

        # Build maps
        spend_map = {}
        for row in cat_spending:
            spend_map[row.id] = {
                "id": row.id,
                "name": row.name,
                "parent_id": row.parent_id,
                "is_income": row.is_income,
                "color": row.color,
                "sort_order": row.sort_order or 0,
                "total": row.total or Decimal("0"),
                "tx_count": row.tx_count or 0,
            }

        # Get all categories for this user to build full hierarchy
        all_cats = (
            db.query(Category)
            .filter(Category.user_id == user.id)
            .order_by(Category.sort_order, Category.name)
            .all()
        )

        parents = [c for c in all_cats if c.parent_id is None]
        children_map = {}
        for c in all_cats:
            if c.parent_id is not None:
                children_map.setdefault(c.parent_id, []).append(c)

        # Build breakdown: income categories first, then expenses
        for is_income_pass in [1, 0]:
            for parent in parents:
                if parent.is_income != is_income_pass:
                    continue
                children = children_map.get(parent.id, [])
                parent_data = spend_map.get(parent.id, {"total": Decimal("0"), "tx_count": 0})

                child_rows = []
                group_total = Decimal("0") if children else parent_data["total"]
                group_count = 0 if children else parent_data["tx_count"]
                group_budget = Decimal("0") if children else budget_map.get(parent.id, Decimal("0"))

                for child in children:
                    cd = spend_map.get(child.id, {"total": Decimal("0"), "tx_count": 0})
                    cb = budget_map.get(child.id, Decimal("0"))
                    if cd["total"] == Decimal("0") and cd["tx_count"] == 0 and cb == Decimal("0"):
                        continue
                    group_total += cd["total"]
                    group_count += cd["tx_count"]
                    group_budget += cb
                    child_rows.append({
                        "id": child.id,
                        "name": child.name,
                        "color": child.color,
                        "total": cd["total"],
                        "tx_count": cd["tx_count"],
                        "budget": cb,
                    })

                if group_total == Decimal("0") and group_count == 0:
                    continue

                category_breakdown.append({
                    "parent_id": parent.id,
                    "parent_name": parent.name,
                    "parent_color": parent.color,
                    "is_income": parent.is_income,
                    "group_total": group_total,
                    "group_count": group_count,
                    "group_budget": group_budget,
                    "children": child_rows,
                })

        # Add uncategorized if any
        uncat_total = uncat.total or Decimal("0") if uncat else Decimal("0")
        uncat_count = uncat.tx_count or 0 if uncat else 0
        if uncat_total != Decimal("0") or uncat_count > 0:
            category_breakdown.append({
                "parent_id": -1,
                "parent_name": "Zonder categorie",
                "parent_color": None,
                "is_income": 0,
                "group_total": uncat_total,
                "group_count": uncat_count,
                "group_budget": Decimal("0"),
                "children": [],
            })

    # Recurring projections: upcoming expected items for rest of current period
    recurring_items = (
        db.query(RecurringTransaction)
        .filter(
            RecurringTransaction.user_id == user.id,
            RecurringTransaction.is_active == 1,
        )
        .order_by(RecurringTransaction.name)
        .all()
    )

    # For each recurring item, check if it's been matched this period
    view_month = current_month if current_month else today.month
    period_start = date(current_year, view_month, 1)
    last_day = calendar.monthrange(current_year, view_month)[1]
    period_end = date(current_year, view_month, last_day)

    recurring_due = []
    recurring_confirmed = []
    projected_expenses = Decimal("0")
    projected_income = Decimal("0")

    for item in recurring_items:
        # Only show monthly items (or items due this period)
        if item.frequency == "monthly":
            start, end = period_start, period_end
        elif item.frequency == "weekly":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif item.frequency == "quarterly":
            q_month = ((view_month - 1) // 3) * 3 + 1
            start = date(current_year, q_month, 1)
            end_month = q_month + 2
            end_year = current_year
            if end_month > 12:
                end_month -= 12
                end_year += 1
            qld = calendar.monthrange(end_year, end_month)[1]
            end = date(end_year, end_month, qld)
        elif item.frequency == "yearly":
            start = date(current_year, 1, 1)
            end = date(current_year, 12, 31)
        else:
            start, end = period_start, period_end

        # Find matching transaction
        match_query = (
            db.query(Transaction)
            .join(Account)
            .filter(
                Account.user_id == user.id,
                Transaction.date >= start,
                Transaction.date <= end,
            )
        )
        conditions = []
        if item.counterparty:
            conditions.append(Transaction.counterparty.ilike(f"%{item.counterparty}%"))
        if item.description_match:
            conditions.append(Transaction.description.ilike(f"%{item.description_match}%"))
        if conditions:
            match_query = match_query.filter(or_(*conditions))
        else:
            continue

        match = match_query.first()

        entry = {
            "name": item.name,
            "amount": item.amount_expected,
            "frequency": item.frequency,
            "category": item.category.name if item.category else None,
        }

        if match:
            recurring_confirmed.append(entry)
        else:
            recurring_due.append(entry)
            if item.amount_expected < 0:
                projected_expenses += item.amount_expected
            else:
                projected_income += item.amount_expected

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
            "current_month": current_month,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "income": income,
            "expenses": expenses,
            "balance": balance,
            "savings_rate": savings_rate,
            "tx_count": tx_count,
            "monthly_data": monthly_data,
            "months": MONTH_NAMES_NL,
            "top_categories": top_categories,
            "category_breakdown": category_breakdown,
            "recurring_due": recurring_due,
            "recurring_confirmed": recurring_confirmed,
            "projected_expenses": projected_expenses,
            "projected_income": projected_income,
        },
    )
