import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Account, Budget, Category, Transaction
from app.auth import require_login
from sqlalchemy import case

router = APIRouter(prefix="/budgets")
templates = Jinja2Templates(directory="app/templates")

MONTH_NAMES_NL = {
    1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
    9: "September", 10: "Oktober", 11: "November", 12: "December",
}


@router.get("")
def budget_overview(
    request: Request,
    year: int = Query(0),
    month: int = Query(0),
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year
    current_month = month if month else today.month

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Get all categories with hierarchy
    cat_query = db.query(Category).filter(Category.user_id == user.id)
    if account_id:
        cat_query = cat_query.filter(Category.account_id == account_id)
    all_categories = cat_query.order_by(Category.sort_order, Category.name).all()

    top_level = [c for c in all_categories if c.parent_id is None and not c.is_income]
    children_map = {}
    for c in all_categories:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

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

    # Get actual spending per category for this month
    # Include both parent-level and subcategory transactions
    spending_query = (
        db.query(
            Category.id,
            func.sum(Transaction.amount).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == user.id,
            func.extract("year", Transaction.date) == current_year,
            func.extract("month", Transaction.date) == current_month,
            Transaction.amount < 0,
        )
    )
    if account_id:
        spending_query = spending_query.filter(Transaction.account_id == account_id)

    spending = spending_query.group_by(Category.id).all()
    spending_map = {row.id: abs(row.total) for row in spending}

    # Build data for template
    budget_data = []
    total_budgeted = Decimal("0")
    total_spent = Decimal("0")

    for parent in top_level:
        children = children_map.get(parent.id, [])
        parent_budget = budget_map.get(parent.id, Decimal("0"))
        parent_spent = spending_map.get(parent.id, Decimal("0"))

        child_rows = []
        group_budget = parent_budget
        group_spent = parent_spent

        for child in children:
            if child.is_income:
                continue
            cb = budget_map.get(child.id, Decimal("0"))
            cs = spending_map.get(child.id, Decimal("0"))
            group_budget += cb
            group_spent += cs
            child_rows.append({
                "id": child.id,
                "name": child.name,
                "color": child.color,
                "budget": cb,
                "spent": cs,
                "remaining": cb - cs,
            })

        total_budgeted += group_budget
        total_spent += group_spent

        budget_data.append({
            "parent": parent,
            "children": child_rows,
            "group_budget": group_budget,
            "group_spent": group_spent,
            "group_remaining": group_budget - group_spent,
            "parent_budget": parent_budget,
            "parent_spent": parent_spent,
        })

    # Get total income for this month (for zero-based budget view)
    income_query = (
        db.query(
            func.sum(
                case(
                    (Transaction.amount > 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("income"),
        )
        .join(Account)
        .filter(
            Account.user_id == user.id,
            func.extract("year", Transaction.date) == current_year,
            func.extract("month", Transaction.date) == current_month,
        )
    )
    if account_id:
        income_query = income_query.filter(Transaction.account_id == account_id)

    income_result = income_query.first()
    total_income = income_result.income or Decimal("0")
    unallocated = total_income - total_budgeted

    # Years with transactions
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    return templates.TemplateResponse(
        "budgets/overview.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": current_month,
            "years": years,
            "months": MONTH_NAMES_NL,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "budget_data": budget_data,
            "total_budgeted": total_budgeted,
            "total_spent": total_spent,
            "total_remaining": total_budgeted - total_spent,
            "total_income": total_income,
            "unallocated": unallocated,
        },
    )


@router.post("/save")
def save_budget(
    request: Request,
    category_id: int = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    amount: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Verify category belongs to user
    cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not cat:
        return JSONResponse({"ok": False}, status_code=400)

    parsed = Decimal(amount.replace(",", ".").strip() or "0")

    budget = (
        db.query(Budget)
        .filter(
            Budget.user_id == user.id,
            Budget.category_id == category_id,
            Budget.year == year,
            Budget.month == month,
        )
        .first()
    )

    if budget:
        budget.amount = parsed
    else:
        budget = Budget(
            user_id=user.id,
            category_id=category_id,
            year=year,
            month=month,
            amount=parsed,
        )
        db.add(budget)

    db.commit()

    return JSONResponse({"ok": True, "amount": float(parsed)})


@router.post("/copy")
def copy_budgets(
    request: Request,
    from_year: int = Form(...),
    from_month: int = Form(...),
    to_year: int = Form(...),
    to_month: int = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    source = (
        db.query(Budget)
        .filter(
            Budget.user_id == user.id,
            Budget.year == from_year,
            Budget.month == from_month,
        )
        .all()
    )

    for src in source:
        existing = (
            db.query(Budget)
            .filter(
                Budget.user_id == user.id,
                Budget.category_id == src.category_id,
                Budget.year == to_year,
                Budget.month == to_month,
            )
            .first()
        )
        if existing:
            existing.amount = src.amount
        else:
            db.add(Budget(
                user_id=user.id,
                category_id=src.category_id,
                year=to_year,
                month=to_month,
                amount=src.amount,
            ))

    db.commit()

    return RedirectResponse(f"/budgets?year={to_year}&month={to_month}", status_code=302)
