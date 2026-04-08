import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Account, Transaction, Category,
    SavingsPlan, SavingsLine, SavingsEntry,
)
from app.auth import require_login
from app.template_config import templates

router = APIRouter(prefix="/savings")

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]

FREQUENCY_LABELS = {
    "monthly": "Maandelijks",
    "quarterly": "Per kwartaal",
    "biannual": "Halfjaarlijks",
    "yearly": "Jaarlijks",
    "one-off": "Eenmalig",
}

FREQUENCY_MONTHS = {
    "monthly": list(range(1, 13)),
    "quarterly": [3, 6, 9, 12],
    "biannual": [6, 12],
    "yearly": [12],
    "one-off": [],
}


def _smart_fill_entries(line: SavingsLine, target_month: int | None = None):
    """Create SavingsEntry objects based on frequency and default_amount."""
    freq = line.frequency
    amount = line.default_amount or Decimal("0")

    if freq in ("yearly", "one-off"):
        months = [target_month] if target_month else [12]
    else:
        months = FREQUENCY_MONTHS.get(freq, list(range(1, 13)))

    entries = []
    for m in range(1, 13):
        entry = SavingsEntry(
            line=line,
            month=m,
            amount=amount if m in months else None,
            status="forecast",
        )
        entries.append(entry)
    return entries


def _get_transaction_totals_by_month(
    db: Session, account_id: int, year: int, category_id: int | None = None
):
    """Get sum of transaction amounts per month for an account in a given year."""
    query = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        )
        .filter(
            Transaction.account_id == account_id,
            func.extract("year", Transaction.date) == year,
        )
    )
    if category_id:
        query = query.filter(Transaction.category_id == category_id)

    query = query.group_by(func.extract("month", Transaction.date))
    return {int(row.month): row.total for row in query.all()}


def _has_transactions_in_month(db: Session, account_id: int, year: int, month: int) -> bool:
    """Check if there are any transactions in a specific month."""
    return (
        db.query(Transaction.id)
        .filter(
            Transaction.account_id == account_id,
            func.extract("year", Transaction.date) == year,
            func.extract("month", Transaction.date) == month,
        )
        .first()
    ) is not None


def _determine_entry_status(
    db: Session, account_id: int, year: int, month: int, today: datetime.date
) -> str:
    """
    Determine the status for an entry:
    - 'confirmed' (green): month is past AND transactions exist for that month
                           AND transactions exist in a subsequent month (or month is fully past)
    - 'pending' (blue): transactions exist for this month but next month has no transactions yet
                        and the month isn't fully in the past yet
    - 'forecast' (grey): no transactions for this month, still in the future
    """
    has_tx = _has_transactions_in_month(db, account_id, year, month)

    if not has_tx:
        return "forecast"

    # Check if this month is completely in the past
    first_of_next = datetime.date(
        year if month < 12 else year + 1,
        month + 1 if month < 12 else 1,
        1,
    )
    month_is_past = today >= first_of_next

    if month_is_past:
        return "confirmed"

    # Month is current or has transactions but not fully past
    # Check if the next month already has transactions (meaning this month is "closed")
    if month < 12:
        next_has_tx = _has_transactions_in_month(db, account_id, year, month + 1)
        if next_has_tx:
            return "confirmed"

    return "pending"


def _build_category_suggestions(
    db: Session, plan: SavingsPlan, existing_category_ids: set[int]
):
    """
    Build suggested lines from transaction categories on this savings account.
    Returns list of dicts with category info for categories not yet in the plan.
    """
    rows = (
        db.query(
            Category.id,
            Category.name,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            Transaction.account_id == plan.account_id,
            func.extract("year", Transaction.date) == plan.year,
        )
        .group_by(Category.id, Category.name)
        .all()
    )

    suggestions = []
    for row in rows:
        if row.id not in existing_category_ids:
            suggestions.append({
                "category_id": row.id,
                "category_name": row.name,
                "total": row.total,
                "tx_count": row.tx_count,
            })
    return suggestions


# ── Routes ──────────────────────────────────────────────────────────────

@router.get("")
def savings_overview(
    request: Request,
    year: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    current_year = year or datetime.date.today().year

    plans = (
        db.query(SavingsPlan)
        .options(joinedload(SavingsPlan.account))
        .filter(SavingsPlan.user_id == user.id, SavingsPlan.year == current_year)
        .all()
    )

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Determine which years have plans for the year selector
    plan_years = (
        db.query(SavingsPlan.year)
        .filter(SavingsPlan.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({r[0] for r in plan_years} | {current_year})

    return templates.TemplateResponse(
        "savings/overview.html",
        {
            "request": request,
            "user": user,
            "plans": plans,
            "accounts": accounts,
            "current_year": current_year,
            "years": years,
        },
    )


@router.post("")
def create_plan(
    request: Request,
    account_id: int = Form(...),
    year: int = Form(...),
    starting_balance: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Verify account belongs to user
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id)
        .first()
    )
    if not account:
        return RedirectResponse("/savings", status_code=302)

    # Check if plan already exists
    existing = (
        db.query(SavingsPlan)
        .filter(SavingsPlan.account_id == account_id, SavingsPlan.year == year)
        .first()
    )
    if existing:
        return RedirectResponse(f"/savings/{existing.id}", status_code=302)

    try:
        balance = Decimal(starting_balance.replace(",", "."))
    except (InvalidOperation, ValueError):
        balance = Decimal("0")

    plan = SavingsPlan(
        user_id=user.id,
        account_id=account_id,
        year=year,
        starting_balance=balance,
    )
    db.add(plan)
    db.commit()

    return RedirectResponse(f"/savings/{plan.id}", status_code=302)


@router.get("/{plan_id}")
def plan_detail(
    request: Request,
    plan_id: int,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()

    plan = (
        db.query(SavingsPlan)
        .options(
            joinedload(SavingsPlan.account),
            joinedload(SavingsPlan.lines).joinedload(SavingsLine.entries),
            joinedload(SavingsPlan.lines).joinedload(SavingsLine.category),
        )
        .filter(SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    # Auto-update entry statuses based on transactions
    for line in plan.lines:
        for entry in line.entries:
            if entry.amount is not None:
                new_status = _determine_entry_status(
                    db, plan.account_id, plan.year, entry.month, today
                )
                if entry.status != new_status:
                    entry.status = new_status

    # Get transaction totals per category per month for matching info
    category_totals = {}
    for line in plan.lines:
        if line.category_id:
            totals = _get_transaction_totals_by_month(
                db, plan.account_id, plan.year, line.category_id
            )
            category_totals[line.id] = totals

    # Split lines into income and expense
    income_lines = [l for l in plan.lines if l.is_income]
    expense_lines = [l for l in plan.lines if not l.is_income]

    # Calculate running balance per month
    # Income adds, expense subtracts (amounts stored as positive)
    running_balance = {}
    balance = plan.starting_balance or Decimal("0")
    for m in range(1, 13):
        month_total = Decimal("0")
        for line in plan.lines:
            entry = next((e for e in line.entries if e.month == m), None)
            if entry and entry.amount is not None:
                if line.is_income:
                    month_total += abs(entry.amount)
                else:
                    month_total -= abs(entry.amount)
        balance += month_total
        running_balance[m] = balance

    # Calculate planned annual total per line (always positive display)
    line_totals = {}
    for line in plan.lines:
        total = sum(
            (abs(e.amount) for e in line.entries if e.amount is not None),
            Decimal("0"),
        )
        line_totals[line.id] = total

    # Suggestions from categories
    existing_category_ids = {line.category_id for line in plan.lines if line.category_id}
    category_suggestions = _build_category_suggestions(db, plan, existing_category_ids)

    # Categories for this account's dropdown
    categories = (
        db.query(Category)
        .filter(
            Category.user_id == user.id,
            Category.account_id == plan.account_id,
        )
        .order_by(Category.name)
        .all()
    )

    db.commit()

    # Parse AI suggestions from query param (if coming from analyze)
    import json, base64
    ai_suggestions = []
    suggestions_b64 = request.query_params.get("suggestions", "")
    if suggestions_b64:
        try:
            ai_suggestions = json.loads(base64.b64decode(suggestions_b64).decode())
        except Exception:
            pass
    analyze_status = request.query_params.get("analyze", "")

    return templates.TemplateResponse(
        "savings/detail.html",
        {
            "request": request,
            "user": user,
            "plan": plan,
            "income_lines": income_lines,
            "expense_lines": expense_lines,
            "months": MONTH_NAMES_NL,
            "running_balance": running_balance,
            "line_totals": line_totals,
            "category_totals": category_totals,
            "category_suggestions": category_suggestions,
            "categories": categories,
            "frequency_labels": FREQUENCY_LABELS,
            "today": today,
            "ai_suggestions": ai_suggestions,
            "analyze_status": analyze_status,
        },
    )


@router.post("/lines")
def add_line(
    request: Request,
    plan_id: int = Form(...),
    name: str = Form(...),
    category_id: int = Form(0),
    frequency: str = Form("monthly"),
    default_amount: str = Form("0"),
    target_month: int = Form(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    plan = (
        db.query(SavingsPlan)
        .filter(SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    try:
        amount = Decimal(default_amount.replace(",", "."))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")

    # Determine next sort order
    max_order = (
        db.query(func.max(SavingsLine.sort_order))
        .filter(SavingsLine.plan_id == plan_id)
        .scalar()
    ) or 0

    cat_id = category_id if category_id else None

    # Determine is_income from linked category
    line_is_income = 0
    if cat_id:
        cat = db.query(Category).filter(Category.id == cat_id).first()
        if cat:
            line_is_income = cat.is_income

    line = SavingsLine(
        plan_id=plan_id,
        name=name.strip(),
        category_id=cat_id,
        is_income=line_is_income,
        frequency=frequency,
        default_amount=amount,
        annual_budget=amount * len(FREQUENCY_MONTHS.get(frequency, list(range(1, 13)))),
        sort_order=max_order + 1,
    )
    db.add(line)
    db.flush()

    # Smart fill entries
    entries = _smart_fill_entries(line, target_month=target_month or None)
    for entry in entries:
        db.add(entry)

    # If category is set, try to fill from existing transactions
    if cat_id:
        today = datetime.date.today()
        tx_totals = _get_transaction_totals_by_month(
            db, plan.account_id, plan.year, cat_id
        )
        for entry in entries:
            if entry.month in tx_totals:
                entry.amount = tx_totals[entry.month]
                entry.status = _determine_entry_status(
                    db, plan.account_id, plan.year, entry.month, today
                )

    db.commit()

    return RedirectResponse(f"/savings/{plan_id}", status_code=302)


@router.post("/entries/update")
def update_entry(
    request: Request,
    entry_id: int = Form(...),
    amount: str = Form(""),
    db: Session = Depends(get_db),
):
    """AJAX endpoint for inline cell editing."""
    user = require_login(request, db)

    entry = (
        db.query(SavingsEntry)
        .join(SavingsLine)
        .join(SavingsPlan)
        .filter(SavingsEntry.id == entry_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not entry:
        return JSONResponse({"error": "Niet gevonden"}, status_code=404)

    plan = entry.line.plan

    amount_str = amount.strip().replace(",", ".")
    if amount_str == "" or amount_str == "-":
        entry.amount = None
        entry.status = "forecast"
    else:
        try:
            entry.amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            return JSONResponse({"error": "Ongeldig bedrag"}, status_code=400)

        # Auto-determine status
        today = datetime.date.today()
        entry.status = _determine_entry_status(
            db, plan.account_id, plan.year, entry.month, today
        )

    db.commit()

    # Recalculate line total (always positive display)
    line_total = sum(
        (abs(e.amount) for e in entry.line.entries if e.amount is not None),
        Decimal("0"),
    )

    # Recalculate full running balance
    all_lines = (
        db.query(SavingsLine)
        .options(joinedload(SavingsLine.entries))
        .filter(SavingsLine.plan_id == plan.id)
        .all()
    )
    balance = plan.starting_balance or Decimal("0")
    running_balances = {}
    for m in range(1, 13):
        month_total = Decimal("0")
        for ln in all_lines:
            e = next((x for x in ln.entries if x.month == m), None)
            if e and e.amount is not None:
                if ln.is_income:
                    month_total += abs(e.amount)
                else:
                    month_total -= abs(e.amount)
        balance += month_total
        running_balances[m] = float(balance)

    return JSONResponse({
        "ok": True,
        "entry_id": entry.id,
        "amount": float(entry.amount) if entry.amount is not None else None,
        "status": entry.status,
        "line_total": float(line_total),
        "running_balances": running_balances,
    })


@router.post("/lines/{line_id}/edit")
def edit_line(
    request: Request,
    line_id: int,
    name: str = Form(...),
    category_id: int = Form(0),
    frequency: str = Form("monthly"),
    default_amount: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    line = (
        db.query(SavingsLine)
        .join(SavingsPlan)
        .filter(SavingsLine.id == line_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not line:
        return RedirectResponse("/savings", status_code=302)

    cat_id = category_id if category_id else None

    # Determine is_income from linked category
    line_is_income = 0
    if cat_id:
        cat = db.query(Category).filter(Category.id == cat_id).first()
        if cat:
            line_is_income = cat.is_income

    try:
        amount = Decimal(default_amount.replace(",", "."))
    except (InvalidOperation, ValueError):
        amount = line.default_amount

    line.name = name.strip()
    line.category_id = cat_id
    line.is_income = line_is_income
    line.frequency = frequency
    line.default_amount = amount
    line.annual_budget = amount * len(FREQUENCY_MONTHS.get(frequency, list(range(1, 13))))

    db.commit()

    return RedirectResponse(f"/savings/{line.plan_id}", status_code=302)


@router.post("/lines/{line_id}/delete")
def delete_line(
    request: Request,
    line_id: int,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    line = (
        db.query(SavingsLine)
        .join(SavingsPlan)
        .filter(SavingsLine.id == line_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not line:
        return RedirectResponse("/savings", status_code=302)

    plan_id = line.plan_id
    db.delete(line)
    db.commit()

    return RedirectResponse(f"/savings/{plan_id}", status_code=302)


@router.post("/{plan_id}/delete")
def delete_plan(
    request: Request,
    plan_id: int,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    plan = (
        db.query(SavingsPlan)
        .filter(SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    year = plan.year
    db.delete(plan)
    db.commit()

    return RedirectResponse(f"/savings?year={year}", status_code=302)


@router.post("/{plan_id}/accept-suggestion")
def accept_ai_suggestion(
    plan_id: int,
    request: Request,
    name: str = Form(...),
    amount: str = Form(...),
    frequency: str = Form("monthly"),
    is_income: str = Form("0"),
    db: Session = Depends(get_db),
):
    """Accept an AI suggestion and create a savings line with auto-filled entries."""
    user = require_login(request, db)
    plan = db.query(SavingsPlan).filter(
        SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id
    ).first()
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    try:
        parsed_amount = Decimal(amount.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse(f"/savings/{plan_id}", status_code=302)

    income = is_income == "1" or is_income == "true"
    freq = frequency if frequency in FREQUENCY_LABELS else "monthly"

    # Create savings line
    line = SavingsLine(
        plan_id=plan.id,
        name=name.strip(),
        is_income=1 if income else 0,
        frequency=freq,
        default_amount=parsed_amount,
    )
    db.add(line)
    db.flush()

    # Create entries and fill from transactions
    _smart_fill_entries(db, line)

    # Try to fill with actual transaction data
    tx_totals = _get_transaction_totals_by_month(
        db, plan.account_id, plan.year, category_id=None
    )
    # For this line, match by searching transactions with the line name in counterparty
    search_name = name.strip().lower()
    all_txs = (
        db.query(Transaction)
        .filter(
            Transaction.account_id == plan.account_id,
            func.extract("year", Transaction.date) == plan.year,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .all()
    )
    monthly_totals = {}
    for tx in all_txs:
        cp = (tx.counterparty or "").lower()
        desc = (tx.description or "").lower()
        if search_name in cp or search_name in desc:
            m = tx.date.month
            if m not in monthly_totals:
                monthly_totals[m] = Decimal("0")
            if income:
                if tx.amount > 0:
                    monthly_totals[m] += tx.amount
            else:
                if tx.amount < 0:
                    monthly_totals[m] += abs(tx.amount)

    for entry in line.entries:
        if entry.month in monthly_totals:
            entry.amount = monthly_totals[entry.month]

    db.commit()
    return RedirectResponse(f"/savings/{plan_id}", status_code=302)


@router.post("/{plan_id}/analyze")
def analyze_savings(
    plan_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Analyze transactions on the savings account and suggest savings plan lines."""
    user = require_login(request, db)
    plan = (
        db.query(SavingsPlan)
        .options(joinedload(SavingsPlan.account), joinedload(SavingsPlan.lines))
        .filter(SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    # Get all transactions for this account in the plan year
    from sqlalchemy.orm import joinedload as jl
    from app.models import Category as Cat
    transactions = (
        db.query(Transaction)
        .options(jl(Transaction.category))
        .filter(
            Transaction.account_id == plan.account_id,
            func.extract("year", Transaction.date) == plan.year,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .order_by(Transaction.date)
        .all()
    )

    if not transactions:
        return RedirectResponse(f"/savings/{plan_id}?analyze=empty", status_code=302)

    # Transform for AI (handle encrypted fields gracefully)
    tx_data = []
    for tx in transactions:
        try:
            tx_data.append({
                "counterparty": (tx.counterparty or "").strip(),
                "description": (tx.description or "").strip(),
                "amount": float(tx.amount) if tx.amount else 0.0,
                "date": tx.date,
                "category_id": tx.category_id,
                "category_name": tx.category.name if tx.category else None,
            })
        except Exception:
            continue  # Skip transactions with decryption issues

    # Get existing line names
    existing_lines = [line.name for line in plan.lines]

    # Call AI analysis
    from app.ai_suggest import analyze_savings_with_ai, ai_available
    suggestions = None
    if ai_available():
        suggestions = analyze_savings_with_ai(
            tx_data, plan.account.name, plan.year, existing_lines
        )

    if not suggestions:
        # Fallback: use pattern detection without AI
        from app.ai_suggest import detect_recurring_patterns
        candidates = detect_recurring_patterns(tx_data)
        suggestions = [
            {
                "name": c["counterparty"][:50],
                "amount": abs(c["avg_amount"]),
                "frequency": c["frequency"] if c["frequency"] in FREQUENCY_LABELS else "monthly",
                "is_income": c["avg_amount"] > 0,
                "reasoning": f"{c['count']}x gevonden, gem. elke {c['avg_days']:.0f} dagen",
            }
            for c in candidates
            if c["counterparty"][:50] not in existing_lines
        ]

    if not suggestions:
        return RedirectResponse(f"/savings/{plan_id}?analyze=empty", status_code=302)

    # Store suggestions in session via query params (simple approach)
    import json
    import base64
    suggestions_b64 = base64.b64encode(json.dumps(suggestions).encode()).decode()

    return RedirectResponse(
        f"/savings/{plan_id}?suggestions={suggestions_b64}",
        status_code=302,
    )


@router.post("/lines/{line_id}/fill-from-transactions")
def fill_from_transactions(
    request: Request,
    line_id: int,
    db: Session = Depends(get_db),
):
    """Fill a line's entries from matching transaction categories."""
    user = require_login(request, db)

    line = (
        db.query(SavingsLine)
        .options(joinedload(SavingsLine.entries))
        .join(SavingsPlan)
        .filter(SavingsLine.id == line_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not line or not line.category_id:
        return RedirectResponse("/savings", status_code=302)

    plan = line.plan
    today = datetime.date.today()

    tx_totals = _get_transaction_totals_by_month(
        db, plan.account_id, plan.year, line.category_id
    )

    for entry in line.entries:
        if entry.month in tx_totals:
            entry.amount = tx_totals[entry.month]
            entry.status = _determine_entry_status(
                db, plan.account_id, plan.year, entry.month, today
            )

    db.commit()

    return RedirectResponse(f"/savings/{plan.id}", status_code=302)
