import json
import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import case, func, or_

from app.database import get_db
from app.models import Account, Transaction, Category, Budget
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


def _decimal_to_float(d):
    """Convert Decimal to float for JSON serialization."""
    return float(d) if d else 0.0


@router.get("/dashboard")
def dashboard(
    request: Request,
    year: int = Query(0),
    month: int = Query(0),
    category_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year

    # Years for selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    # Base transaction filters
    base_tx_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.is_projected == 0,
        Transaction.transfer_id.is_(None),
    ]

    # Determine which level we're at
    if month and category_id:
        # Level 3: subcategories within a parent category for a specific month
        return _level3_subcategories(
            request, db, user, current_year, month, category_id,
            years, base_tx_filter, today,
        )
    elif month:
        # Level 2: parent categories for a specific month
        return _level2_categories(
            request, db, user, current_year, month,
            years, base_tx_filter, today,
        )
    else:
        # Level 1: yearly overview (12 months)
        return _level1_yearly(
            request, db, user, current_year,
            years, base_tx_filter, today,
        )


def _level1_yearly(request, db, user, current_year, years, base_tx_filter, today):
    """Level 1: Yearly overview — one row per month."""

    # Budget per month: income vs expense
    budget_monthly = (
        db.query(
            Budget.month.label("month"),
            func.sum(
                case(
                    (Category.is_income == 1, Budget.amount),
                    else_=Decimal("0"),
                )
            ).label("income_budget"),
            func.sum(
                case(
                    ((Category.is_income == 0) & (Category.exclude_from_budget == 0),
                     Budget.amount),
                    else_=Decimal("0"),
                )
            ).label("expense_budget"),
        )
        .join(Category, Budget.category_id == Category.id)
        .filter(
            Budget.user_id == user.id,
            Budget.year == current_year,
            Category.exclude_from_totals == 0,
        )
        .group_by(Budget.month)
        .all()
    )
    budget_by_month = {
        int(row.month): {
            "income_budget": row.income_budget or Decimal("0"),
            "expense_budget": row.expense_budget or Decimal("0"),
        }
        for row in budget_monthly
    }

    # Actual income/expenses per month
    actual_monthly = (
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
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*base_tx_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .group_by(func.extract("month", Transaction.date))
        .all()
    )
    actual_by_month = {
        int(row.month): {
            "income": row.income or Decimal("0"),
            "expenses": row.expenses or Decimal("0"),
        }
        for row in actual_monthly
    }

    # Uncategorized per month (count + amount of expenses only)
    uncat_monthly = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.count(Transaction.id).label("count"),
            func.sum(
                case(
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("amount"),
        )
        .join(Account)
        .filter(*base_tx_filter, Transaction.category_id.is_(None))
        .group_by(func.extract("month", Transaction.date))
        .all()
    )
    uncat_by_month = {
        int(row.month): {"count": row.count, "amount": row.amount or Decimal("0")}
        for row in uncat_monthly
    }

    # Expected (projected) income/expenses per month from unmatched recurring items
    projected_monthly = (
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
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Account)
        .filter(
            Account.user_id == user.id,
            func.extract("year", Transaction.date) == current_year,
            Transaction.is_projected == 1,
            Transaction.is_excluded == 0,
        )
        .group_by(func.extract("month", Transaction.date))
        .all()
    )
    projected_by_month = {
        int(row.month): {
            "income": row.income or Decimal("0"),
            "expenses": row.expenses or Decimal("0"),
        }
        for row in projected_monthly
    }

    # Build rows
    overview_rows = []
    for m in range(1, 13):
        bd = budget_by_month.get(m, {})
        ad = actual_by_month.get(m, {})
        pd = projected_by_month.get(m, {})
        overview_rows.append({
            "label": MONTH_NAMES_NL[m],
            "key": m,
            "link": f"/dashboard?year={current_year}&month={m}",
            "income_budget": bd.get("income_budget", Decimal("0")),
            "income_actual": ad.get("income", Decimal("0")),
            "income_expected": pd.get("income", Decimal("0")),
            "expense_budget": bd.get("expense_budget", Decimal("0")),
            "expense_actual": ad.get("expenses", Decimal("0")),
            "expense_expected": pd.get("expenses", Decimal("0")),
            "uncat_count": uncat_by_month.get(m, {}).get("count", 0),
            "uncat_amount": uncat_by_month.get(m, {}).get("amount", Decimal("0")),
            "is_current": (m == today.month and current_year == today.year),
        })

    # JSON for Chart.js
    overview_json = json.dumps([
        {
            "label": r["label"],
            "income_budget": _decimal_to_float(r["income_budget"]),
            "income_actual": _decimal_to_float(r["income_actual"]),
            "income_expected": _decimal_to_float(r.get("income_expected", Decimal("0"))),
            "expense_budget": _decimal_to_float(r["expense_budget"]),
            "expense_actual": _decimal_to_float(r["expense_actual"]),
            "expense_expected": _decimal_to_float(r.get("expense_expected", Decimal("0"))),
            "uncat_count": r["uncat_count"],
            "uncat_amount": _decimal_to_float(r["uncat_amount"]),
        }
        for r in overview_rows
    ])

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": 0,
            "current_category_id": 0,
            "current_category_name": None,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "title": f"Jaaroverzicht {current_year}",
            "breadcrumbs": [],
            "overview_rows": overview_rows,
            "overview_json": overview_json,
        },
    )


def _level2_categories(request, db, user, current_year, month, years, base_tx_filter, today):
    """Level 2: Month view — one row per parent category."""

    month_filter = base_tx_filter + [
        func.extract("month", Transaction.date) == month,
    ]

    # Get all categories for hierarchy
    all_cats = (
        db.query(Category)
        .filter(Category.user_id == user.id, Category.exclude_from_totals == 0)
        .order_by(Category.sort_order, Category.name)
        .all()
    )
    parents = [c for c in all_cats if c.parent_id is None]
    children_map = {}
    for c in all_cats:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

    # Budgets for this month
    budgets = (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.year == current_year, Budget.month == month)
        .all()
    )
    budget_map = {b.category_id: b.amount for b in budgets}

    # Actual spending per category
    cat_spending = (
        db.query(
            Category.id,
            func.sum(
                case(
                    (Transaction.amount > 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("income"),
            func.sum(
                case(
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*month_filter, Category.exclude_from_totals == 0)
        .group_by(Category.id)
        .all()
    )
    spend_map = {
        row.id: {"income": row.income or Decimal("0"), "expenses": row.expenses or Decimal("0")}
        for row in cat_spending
    }

    # Uncategorized count + amount (expenses only) this month
    uncat_result = (
        db.query(
            func.count(Transaction.id).label("count"),
            func.sum(
                case(
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("amount"),
        )
        .join(Account)
        .filter(*month_filter, Transaction.category_id.is_(None))
        .first()
    )
    uncat_count = uncat_result.count or 0 if uncat_result else 0
    uncat_amount = uncat_result.amount or Decimal("0") if uncat_result else Decimal("0")

    # Build rows per parent category (aggregate children)
    overview_rows = []
    for parent in parents:
        children = children_map.get(parent.id, [])
        child_ids = [c.id for c in children]
        all_ids = [parent.id] + child_ids

        # Sum budgets
        income_budget = Decimal("0")
        expense_budget = Decimal("0")
        for cid in all_ids:
            cat = next((c for c in all_cats if c.id == cid), None)
            if not cat:
                continue
            b = budget_map.get(cid, Decimal("0"))
            if cat.is_income:
                income_budget += b
            else:
                expense_budget += b

        # Sum actuals
        income_actual = Decimal("0")
        expense_actual = Decimal("0")
        for cid in all_ids:
            sd = spend_map.get(cid, {})
            income_actual += sd.get("income", Decimal("0"))
            expense_actual += sd.get("expenses", Decimal("0"))

        # Skip empty rows
        if (income_budget == 0 and income_actual == 0 and
                expense_budget == 0 and expense_actual == 0):
            continue

        has_children = len(children) > 0
        overview_rows.append({
            "label": parent.name,
            "key": parent.id,
            "link": f"/dashboard?year={current_year}&month={month}&category_id={parent.id}" if has_children else None,
            "income_budget": income_budget,
            "income_actual": income_actual,
            "expense_budget": expense_budget,
            "expense_actual": expense_actual,
            "uncat_count": 0,
            "uncat_amount": Decimal("0"),
            "is_current": False,
            "color": parent.color,
        })

    # Add uncategorized row if any — show amount as expenses
    if uncat_count > 0:
        overview_rows.append({
            "label": "Niet gecategoriseerd",
            "key": -1,
            "link": f"/transactions?year={current_year}&month={month}&uncategorized=1",
            "income_budget": Decimal("0"),
            "income_actual": Decimal("0"),
            "expense_budget": Decimal("0"),
            "expense_actual": uncat_amount,
            "uncat_count": uncat_count,
            "uncat_amount": uncat_amount,
            "is_current": False,
        })

    # JSON for Chart.js
    overview_json = json.dumps([
        {
            "label": r["label"],
            "income_budget": _decimal_to_float(r["income_budget"]),
            "income_actual": _decimal_to_float(r["income_actual"]),
            "income_expected": _decimal_to_float(r.get("income_expected", Decimal("0"))),
            "expense_budget": _decimal_to_float(r["expense_budget"]),
            "expense_actual": _decimal_to_float(r["expense_actual"]),
            "expense_expected": _decimal_to_float(r.get("expense_expected", Decimal("0"))),
            "uncat_count": r["uncat_count"],
            "uncat_amount": _decimal_to_float(r["uncat_amount"]),
        }
        for r in overview_rows
    ])

    month_name = MONTH_NAMES_NL_FULL.get(month, "")
    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": month,
            "current_category_id": 0,
            "current_category_name": None,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "title": f"{month_name} {current_year} — Categorieën",
            "breadcrumbs": [
                {"label": f"Jaaroverzicht {current_year}", "url": f"/dashboard?year={current_year}"},
            ],
            "overview_rows": overview_rows,
            "overview_json": overview_json,
        },
    )


def _level3_subcategories(request, db, user, current_year, month, category_id,
                          years, base_tx_filter, today):
    """Level 3: Subcategories within a parent category for a specific month."""

    month_filter = base_tx_filter + [
        func.extract("month", Transaction.date) == month,
    ]

    # Get parent category
    parent_cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not parent_cat:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/dashboard?year={current_year}&month={month}", status_code=302)

    # Get children
    children = (
        db.query(Category)
        .filter(Category.parent_id == category_id, Category.user_id == user.id)
        .order_by(Category.sort_order, Category.name)
        .all()
    )

    # Budgets for this month
    budgets = (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.year == current_year, Budget.month == month)
        .all()
    )
    budget_map = {b.category_id: b.amount for b in budgets}

    # Actual spending per subcategory
    sub_ids = [c.id for c in children] or [parent_cat.id]
    cat_spending = (
        db.query(
            Category.id,
            Category.name,
            Category.color,
            func.sum(
                case(
                    (Transaction.amount > 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("income"),
            func.sum(
                case(
                    (Transaction.amount < 0, func.abs(Transaction.amount)),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*month_filter, Category.id.in_(sub_ids))
        .group_by(Category.id, Category.name, Category.color)
        .all()
    )
    spend_map = {
        row.id: {"name": row.name, "color": row.color,
                 "income": row.income or Decimal("0"),
                 "expenses": row.expenses or Decimal("0")}
        for row in cat_spending
    }

    # Build rows
    overview_rows = []
    items = children if children else [parent_cat]
    for cat in items:
        sd = spend_map.get(cat.id, {})
        b = budget_map.get(cat.id, Decimal("0"))
        income_actual = sd.get("income", Decimal("0"))
        expense_actual = sd.get("expenses", Decimal("0"))
        income_budget = b if cat.is_income else Decimal("0")
        expense_budget = Decimal("0") if cat.is_income else b

        if income_budget == 0 and income_actual == 0 and expense_budget == 0 and expense_actual == 0:
            continue

        overview_rows.append({
            "label": cat.name,
            "key": cat.id,
            "link": None,  # No deeper drill-down
            "income_budget": income_budget,
            "income_actual": income_actual,
            "expense_budget": expense_budget,
            "expense_actual": expense_actual,
            "uncat_count": 0,
            "uncat_amount": Decimal("0"),
            "is_current": False,
            "color": cat.color,
        })

    # JSON for Chart.js
    overview_json = json.dumps([
        {
            "label": r["label"],
            "income_budget": _decimal_to_float(r["income_budget"]),
            "income_actual": _decimal_to_float(r["income_actual"]),
            "income_expected": _decimal_to_float(r.get("income_expected", Decimal("0"))),
            "expense_budget": _decimal_to_float(r["expense_budget"]),
            "expense_actual": _decimal_to_float(r["expense_actual"]),
            "expense_expected": _decimal_to_float(r.get("expense_expected", Decimal("0"))),
            "uncat_count": r["uncat_count"],
            "uncat_amount": _decimal_to_float(r["uncat_amount"]),
        }
        for r in overview_rows
    ])

    month_name = MONTH_NAMES_NL_FULL.get(month, "")
    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": month,
            "current_category_id": category_id,
            "current_category_name": parent_cat.name,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "title": f"{month_name} {current_year} — {parent_cat.name}",
            "breadcrumbs": [
                {"label": f"Jaaroverzicht {current_year}", "url": f"/dashboard?year={current_year}"},
                {"label": f"{month_name} {current_year}", "url": f"/dashboard?year={current_year}&month={month}"},
            ],
            "overview_rows": overview_rows,
            "overview_json": overview_json,
        },
    )
