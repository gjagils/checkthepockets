import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.database import get_db
from app.models import Account, Budget, BudgetPreset, BudgetPresetLine, Category, Transaction
from app.auth import require_login
from app.template_config import templates

router = APIRouter(prefix="/budgets")

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

    top_level = [c for c in all_categories if c.parent_id is None and not c.is_income and not c.exclude_from_budget]
    income_top_level = [c for c in all_categories if c.parent_id is None and c.is_income and not c.exclude_from_budget]
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

    # Previous month for rollover calculation
    if current_month == 1:
        prev_year, prev_month = current_year - 1, 12
    else:
        prev_year, prev_month = current_year, current_month - 1

    # Get previous month's budgets
    prev_budgets = (
        db.query(Budget)
        .filter(
            Budget.user_id == user.id,
            Budget.year == prev_year,
            Budget.month == prev_month,
        )
        .all()
    )
    prev_budget_map = {b.category_id: b.amount for b in prev_budgets}

    # Get previous month's spending
    prev_spending_query = (
        db.query(
            Category.id,
            func.sum(Transaction.amount).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == user.id,
            func.extract("year", Transaction.date) == prev_year,
            func.extract("month", Transaction.date) == prev_month,
            Transaction.amount < 0,
            Transaction.is_excluded == 0,
            Category.exclude_from_budget == 0,
        )
    )
    if account_id:
        prev_spending_query = prev_spending_query.filter(Transaction.account_id == account_id)
    prev_spending = prev_spending_query.group_by(Category.id).all()
    prev_spending_map = {row.id: abs(row.total) for row in prev_spending}

    # Rollover per category: prev_budget - prev_spent (positive = surplus, negative = overspent)
    rollover_map = {}
    for cat_id, prev_bud in prev_budget_map.items():
        prev_sp = prev_spending_map.get(cat_id, Decimal("0"))
        rollover_map[cat_id] = prev_bud - prev_sp

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
            Transaction.is_excluded == 0,
            Category.exclude_from_budget == 0,
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
    total_rollover = Decimal("0")

    for parent in top_level:
        children = [c for c in children_map.get(parent.id, []) if not c.is_income]
        parent_budget = budget_map.get(parent.id, Decimal("0"))
        parent_spent = spending_map.get(parent.id, Decimal("0"))
        parent_rollover = rollover_map.get(parent.id, Decimal("0"))

        child_rows = []
        # If parent has children, only sum children (parent budget is display-only)
        # If parent has no children, use parent's own budget
        if children:
            group_budget = Decimal("0")
            group_spent = Decimal("0")
            group_rollover = Decimal("0")
        else:
            group_budget = parent_budget
            group_spent = parent_spent
            group_rollover = parent_rollover

        for child in children:
            cb = budget_map.get(child.id, Decimal("0"))
            cs = spending_map.get(child.id, Decimal("0"))
            cr = rollover_map.get(child.id, Decimal("0"))
            cprev = prev_spending_map.get(child.id, Decimal("0"))
            group_budget += cb
            group_spent += cs
            group_rollover += cr
            child_rows.append({
                "id": child.id,
                "name": child.name,
                "color": child.color,
                "budget": cb,
                "spent": cs,
                "remaining": cb - cs,
                "rollover": cr,
                "effective_budget": cb + cr,
                "effective_remaining": cb + cr - cs,
                "prev_spent": cprev,
            })

        total_budgeted += group_budget
        total_spent += group_spent
        total_rollover += group_rollover

        budget_data.append({
            "parent": parent,
            "children": child_rows,
            "group_budget": group_budget,
            "group_spent": group_spent,
            "group_remaining": group_budget - group_spent,
            "group_rollover": group_rollover,
            "group_effective": group_budget + group_rollover,
            "group_effective_remaining": group_budget + group_rollover - group_spent,
            "parent_budget": parent_budget,
            "parent_spent": parent_spent,
            "parent_rollover": parent_rollover,
        })

    # Build income budget data (same structure as expense budget_data)
    # Get actual income per category for this month
    income_spending_query = (
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
            Transaction.amount > 0,
            Transaction.is_excluded == 0,
        )
    )
    if account_id:
        income_spending_query = income_spending_query.filter(Transaction.account_id == account_id)
    income_spending = income_spending_query.group_by(Category.id).all()
    income_actual_map = {row.id: row.total for row in income_spending}

    income_budget_data = []
    total_income_budgeted = Decimal("0")
    total_income_actual = Decimal("0")

    for parent in income_top_level:
        children = children_map.get(parent.id, [])
        parent_budget = budget_map.get(parent.id, Decimal("0"))
        parent_actual = income_actual_map.get(parent.id, Decimal("0"))

        child_rows = []
        if children:
            group_budget = Decimal("0")
            group_actual = Decimal("0")
        else:
            group_budget = parent_budget
            group_actual = parent_actual

        for child in children:
            cb = budget_map.get(child.id, Decimal("0"))
            ca = income_actual_map.get(child.id, Decimal("0"))
            group_budget += cb
            group_actual += ca
            child_rows.append({
                "id": child.id,
                "name": child.name,
                "color": child.color,
                "budget": cb,
                "actual": ca,
                "difference": ca - cb,
            })

        total_income_budgeted += group_budget
        total_income_actual += group_actual

        income_budget_data.append({
            "parent": parent,
            "children": child_rows,
            "group_budget": group_budget,
            "group_actual": group_actual,
            "group_difference": group_actual - group_budget,
            "parent_budget": parent_budget,
            "parent_actual": parent_actual,
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
            Transaction.is_excluded == 0,
        )
    )
    if account_id:
        income_query = income_query.filter(Transaction.account_id == account_id)

    income_result = income_query.first()
    total_income = income_result.income or Decimal("0")
    unallocated = total_income - total_budgeted

    # Load presets for this user
    presets = (
        db.query(BudgetPreset)
        .filter(BudgetPreset.user_id == user.id)
        .order_by(BudgetPreset.name)
        .all()
    )

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
            "income_budget_data": income_budget_data,
            "total_income_budgeted": total_income_budgeted,
            "total_income_actual": total_income_actual,
            "unallocated": unallocated,
            "total_rollover": total_rollover,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "presets": presets,
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


@router.post("/average")
def budget_from_average(
    request: Request,
    to_year: int = Form(...),
    to_month: int = Form(...),
    num_months: int = Form(3),
    db: Session = Depends(get_db),
):
    """Set budget per category based on average spending over the last N months."""
    user = require_login(request, db)

    # Calculate the N months before the target month
    months_to_check = []
    y, m = to_year, to_month
    for _ in range(num_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months_to_check.append((y, m))

    if not months_to_check:
        return RedirectResponse(f"/budgets?year={to_year}&month={to_month}", status_code=302)

    # Build OR conditions for the month ranges
    from sqlalchemy import or_, and_, tuple_

    month_conditions = or_(
        *[
            and_(
                func.extract("year", Transaction.date) == yr,
                func.extract("month", Transaction.date) == mn,
            )
            for yr, mn in months_to_check
        ]
    )

    # Get average spending per category over those months
    avg_spending = (
        db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total"),
        )
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.category_id.isnot(None),
            Transaction.amount < 0,
            month_conditions,
        )
        .group_by(Transaction.category_id)
        .all()
    )

    count = 0
    for row in avg_spending:
        avg_amount = abs(row.total) / num_months
        # Round to nearest euro
        avg_amount = avg_amount.quantize(Decimal("1"))

        existing = (
            db.query(Budget)
            .filter(
                Budget.user_id == user.id,
                Budget.category_id == row.category_id,
                Budget.year == to_year,
                Budget.month == to_month,
            )
            .first()
        )
        if existing:
            existing.amount = avg_amount
        else:
            db.add(Budget(
                user_id=user.id,
                category_id=row.category_id,
                year=to_year,
                month=to_month,
                amount=avg_amount,
            ))
        count += 1

    db.commit()

    return RedirectResponse(f"/budgets?year={to_year}&month={to_month}", status_code=302)


@router.post("/preset/save")
def save_budget_preset(
    request: Request,
    name: str = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    db: Session = Depends(get_db),
):
    """Save current month's budgets as a named preset."""
    user = require_login(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse(f"/budgets?year={year}&month={month}", status_code=302)

    # Get existing preset or create new
    preset = (
        db.query(BudgetPreset)
        .filter(BudgetPreset.user_id == user.id, BudgetPreset.name == name)
        .first()
    )
    if preset:
        # Delete existing lines; we'll recreate
        db.query(BudgetPresetLine).filter(BudgetPresetLine.preset_id == preset.id).delete()
    else:
        preset = BudgetPreset(user_id=user.id, name=name)
        db.add(preset)
        db.flush()

    # Copy current month's budgets into preset
    budgets = (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.year == year, Budget.month == month)
        .all()
    )
    for b in budgets:
        db.add(BudgetPresetLine(preset_id=preset.id, category_id=b.category_id, amount=b.amount))

    db.commit()
    return RedirectResponse(f"/budgets?year={year}&month={month}", status_code=302)


@router.post("/preset/load")
def load_budget_preset(
    request: Request,
    preset_id: int = Form(...),
    to_year: int = Form(...),
    to_month: int = Form(...),
    db: Session = Depends(get_db),
):
    """Apply a preset to the current month (overwrites existing budgets)."""
    user = require_login(request, db)

    preset = (
        db.query(BudgetPreset)
        .filter(BudgetPreset.id == preset_id, BudgetPreset.user_id == user.id)
        .first()
    )
    if not preset:
        return RedirectResponse(f"/budgets?year={to_year}&month={to_month}", status_code=302)

    for line in preset.lines:
        existing = (
            db.query(Budget)
            .filter(
                Budget.user_id == user.id,
                Budget.category_id == line.category_id,
                Budget.year == to_year,
                Budget.month == to_month,
            )
            .first()
        )
        if existing:
            existing.amount = line.amount
        else:
            db.add(Budget(
                user_id=user.id,
                category_id=line.category_id,
                year=to_year,
                month=to_month,
                amount=line.amount,
            ))

    db.commit()
    return RedirectResponse(f"/budgets?year={to_year}&month={to_month}", status_code=302)


@router.post("/preset/delete")
def delete_budget_preset(
    request: Request,
    preset_id: int = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    db: Session = Depends(get_db),
):
    """Delete a saved budget preset."""
    user = require_login(request, db)

    preset = (
        db.query(BudgetPreset)
        .filter(BudgetPreset.id == preset_id, BudgetPreset.user_id == user.id)
        .first()
    )
    if preset:
        db.delete(preset)
        db.commit()

    return RedirectResponse(f"/budgets?year={year}&month={month}", status_code=302)
