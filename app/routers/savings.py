import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Account, Transaction, Category, Rule,
    SavingsPlan, SavingsLine, SavingsEntry,
)
from app.auth import require_login
from app.template_config import templates
from app.rules_engine import apply_single_rule

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


def _months_for_frequency(frequency: str, target_month: int | None = None) -> list[int]:
    """Return the months (1..12) where this frequency 'fires', given an optional start month."""
    if frequency == "monthly":
        return list(range(1, 13))
    if frequency == "quarterly":
        start = target_month or 3
        return sorted({((start - 1 + 3 * i) % 12) + 1 for i in range(4)})
    if frequency == "biannual":
        start = target_month or 6
        return sorted({((start - 1 + 6 * i) % 12) + 1 for i in range(2)})
    if frequency == "yearly":
        return [target_month or 12]
    if frequency == "one-off":
        return [target_month] if target_month else []
    return list(range(1, 13))


def _smart_fill_entries(line: SavingsLine, target_month: int | None = None):
    """Create SavingsEntry objects based on frequency and default_amount."""
    amount = line.default_amount or Decimal("0")
    months = _months_for_frequency(line.frequency, target_month)

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


def _months_fully_categorized(db: Session, account_id: int, year: int) -> set[int]:
    """Maanden waarin het account transacties heeft én ALLE transacties een categorie hebben.
    Voor die maanden mogen we veilig aannemen dat een categorie zonder match echt 0 is."""
    total_rows = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.count(Transaction.id).label("total"),
        )
        .filter(
            Transaction.account_id == account_id,
            func.extract("year", Transaction.date) == year,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .group_by(func.extract("month", Transaction.date))
        .all()
    )
    uncat_rows = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.count(Transaction.id).label("cnt"),
        )
        .filter(
            Transaction.account_id == account_id,
            func.extract("year", Transaction.date) == year,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.category_id.is_(None),
        )
        .group_by(func.extract("month", Transaction.date))
        .all()
    )
    uncat_map = {int(r.month): int(r.cnt) for r in uncat_rows}
    return {
        int(r.month)
        for r in total_rows
        if int(r.total) > 0 and uncat_map.get(int(r.month), 0) == 0
    }


def _determine_entry_status(
    db: Session, account_id: int, year: int, month: int, today: datetime.date
) -> str:
    """Legacy status helper — kept as fallback for non-category lines.
    See `_determine_color_status` for the new actual-vs-expected coloring."""
    has_tx = _has_transactions_in_month(db, account_id, year, month)

    if not has_tx:
        return "forecast"

    first_of_next = datetime.date(
        year if month < 12 else year + 1,
        month + 1 if month < 12 else 1,
        1,
    )
    month_is_past = today >= first_of_next

    if month_is_past:
        return "match"

    if month < 12:
        next_has_tx = _has_transactions_in_month(db, account_id, year, month + 1)
        if next_has_tx:
            return "match"

    return "current"


def _determine_color_status(
    actual: Decimal | None,
    expected: Decimal | None,
    is_income: bool,
    month: int,
    year: int,
    today: datetime.date,
    month_fully_categorized: bool = False,
) -> str:
    """Bepaal de kleurstatus voor een spaarcel.

    - 'forecast' (transparant): toekomstige maand of geen actual
    - 'current' (grijs): lopende maand
    - 'above' (groen): beter dan verwacht
    - 'match' (blauw): gelijk aan verwacht
    - 'below' (rood): slechter dan verwacht (incl. niet-gerealiseerd in een
      maand waarin alle transacties gecategoriseerd zijn)
    """
    # Toekomst
    if (year, month) > (today.year, today.month):
        return "forecast"
    # Lopende maand — altijd grijs ongeacht waarde
    if (year, month) == (today.year, today.month):
        return "current"
    # Verleden maand zonder actual: als de maand volledig gecategoriseerd is
    # weten we zeker dat 0 ontvangen/uitgegeven is voor deze categorie.
    if actual is None:
        if month_fully_categorized:
            actual = Decimal("0")
        else:
            return "forecast"

    actual_abs = abs(actual)
    expected_abs = abs(expected) if expected is not None else Decimal("0")

    if actual_abs == expected_abs:
        return "match"
    if is_income:
        return "above" if actual_abs > expected_abs else "below"
    return "above" if actual_abs < expected_abs else "below"


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

    # Auto-sync amounts & statuses:
    # - Category-linked lines: pull the per-month sum of that category's transactions
    #   into the entry, en kleur op basis van actual vs expected (default_amount).
    # - Lines without a category: status puur op basis van past/current/future + waarde.
    fully_cat_months = _months_fully_categorized(db, plan.account_id, plan.year)
    category_totals = {}
    for line in plan.lines:
        is_inc = bool(line.is_income)
        if line.category_id:
            tx_totals = _get_transaction_totals_by_month(
                db, plan.account_id, plan.year, line.category_id
            )
            category_totals[line.id] = tx_totals
            for entry in line.entries:
                actual = tx_totals.get(entry.month)
                if actual is not None and entry.amount != actual:
                    entry.amount = actual
                entry.status = _determine_color_status(
                    actual, line.default_amount, is_inc,
                    entry.month, plan.year, today,
                    month_fully_categorized=(entry.month in fully_cat_months),
                )
        else:
            for entry in line.entries:
                # Voor regels zonder categorie: amount is wat de gebruiker zelf zette,
                # dus dat geldt zowel als actual als als expected (= altijd 'match' in 't verleden).
                entry.status = _determine_color_status(
                    entry.amount, entry.amount, is_inc,
                    entry.month, plan.year, today,
                )

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
    is_income: str = Form(""),
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

    # Determine is_income: from form field, or fallback to linked category
    if is_income in ("1", "true"):
        line_is_income = 1
    elif is_income in ("0", "false"):
        line_is_income = 0
    elif cat_id:
        cat = db.query(Category).filter(Category.id == cat_id).first()
        line_is_income = cat.is_income if cat else 0
    else:
        line_is_income = 0

    tm = target_month or None
    months_for_line = _months_for_frequency(frequency, tm)

    line = SavingsLine(
        plan_id=plan_id,
        name=name.strip(),
        category_id=cat_id,
        is_income=line_is_income,
        frequency=frequency,
        default_amount=amount,
        annual_budget=amount * len(months_for_line),
        sort_order=max_order + 1,
    )
    db.add(line)
    db.flush()

    # Smart fill entries
    entries = _smart_fill_entries(line, target_month=tm)
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

    today = datetime.date.today()
    amount_str = amount.strip().replace(",", ".")
    new_amount: Decimal | None
    if amount_str == "" or amount_str == "-":
        new_amount = None
    else:
        try:
            new_amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            return JSONResponse({"error": "Ongeldig bedrag"}, status_code=400)

    entry.amount = new_amount

    # Propagate to future forecast cells in the same line:
    # only cells that still match the previous default (i.e. weren't manually set)
    # AND are still 'forecast' get updated. Cells with actuals are left alone.
    for sibling in entry.line.entries:
        if sibling.id == entry.id:
            continue
        if sibling.month <= entry.month:
            continue
        if sibling.status != "forecast":
            continue
        if sibling.amount is None:
            continue
        sibling.amount = new_amount

    # Refresh statuses for ALL entries in this line met de nieuwe color-logic.
    line = entry.line
    is_inc = bool(line.is_income)
    if line.category_id:
        tx_totals = _get_transaction_totals_by_month(
            db, plan.account_id, plan.year, line.category_id
        )
    else:
        tx_totals = {}

    for e in line.entries:
        actual = tx_totals.get(e.month) if line.category_id else e.amount
        expected = line.default_amount if line.category_id else e.amount
        e.status = _determine_color_status(
            actual, expected, is_inc, e.month, plan.year, today,
        )

    db.commit()

    # Recalculate line total (always positive display)
    line_total = sum(
        (abs(e.amount) for e in entry.line.entries if e.amount is not None),
        Decimal("0"),
    )

    # Build per-entry update info so the frontend can refresh other cells too
    entries_payload = [
        {
            "id": e.id,
            "month": e.month,
            "amount": float(e.amount) if e.amount is not None else None,
            "status": e.status,
        }
        for e in entry.line.entries
    ]

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
        "line_id": entry.line_id,
        "entries": entries_payload,
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
    target_month: int = Form(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    line = (
        db.query(SavingsLine)
        .options(joinedload(SavingsLine.entries), joinedload(SavingsLine.plan))
        .join(SavingsPlan)
        .filter(SavingsLine.id == line_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not line:
        return RedirectResponse("/savings", status_code=302)

    cat_id = category_id if category_id else None
    tm = target_month or None

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

    months_for_line = _months_for_frequency(frequency, tm)

    line.name = name.strip()
    line.category_id = cat_id
    line.is_income = line_is_income
    line.frequency = frequency
    line.default_amount = amount
    line.annual_budget = amount * len(months_for_line)

    # Refill forecast entries based on the new frequency / amount.
    # Confirmed/pending cells (with actual transactions) are left alone.
    months_set = set(months_for_line)
    for entry in line.entries:
        if entry.status != "forecast":
            continue
        if entry.month in months_set:
            entry.amount = amount
        else:
            entry.amount = None

    # If the line has a category, sync amounts from transactions for months
    # that have transactions (mirrors the on-page-load behaviour).
    if cat_id:
        tx_totals = _get_transaction_totals_by_month(
            db, line.plan.account_id, line.plan.year, cat_id
        )
        today = datetime.date.today()
        for entry in line.entries:
            if entry.month in tx_totals:
                entry.amount = tx_totals[entry.month]
                entry.status = _determine_entry_status(
                    db, line.plan.account_id, line.plan.year, entry.month, today
                )

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


@router.post("/{plan_id}/quick-add")
def quick_add_line(
    plan_id: int,
    request: Request,
    # Categorie
    category_mode: str = Form("existing"),  # 'existing' | 'new'
    category_id: int = Form(0),
    new_category_name: str = Form(""),
    new_category_is_income: int = Form(0),
    new_category_parent_id: int = Form(0),
    # Optionele matching-regel
    create_rule: int = Form(0),
    rule_match_field: str = Form("description"),
    rule_match_value: str = Form(""),
    # Plan-rij
    line_name: str = Form(...),
    frequency: str = Form("monthly"),
    default_amount: str = Form("0"),
    target_month: int = Form(0),
    db: Session = Depends(get_db),
):
    """Maak in één POST een categorie (optioneel nieuw), optioneel een rule die
    transacties op die categorie zet, en een SavingsLine met gevulde entries."""
    user = require_login(request, db)

    plan = (
        db.query(SavingsPlan)
        .options(joinedload(SavingsPlan.account))
        .filter(SavingsPlan.id == plan_id, SavingsPlan.user_id == user.id)
        .first()
    )
    if not plan:
        return RedirectResponse("/savings", status_code=302)

    # ── 1. Categorie ──────────────────────────────────────────────
    cat: Category | None = None
    if category_mode == "new":
        name = new_category_name.strip()
        if not name:
            return RedirectResponse(f"/savings/{plan_id}", status_code=302)

        # Optionele parent — als gegeven: nieuwe categorie wordt subcategorie,
        # erft account_id en is_income van de parent (net als /categories POST).
        parent: Category | None = None
        if new_category_parent_id:
            parent = (
                db.query(Category)
                .filter(
                    Category.id == new_category_parent_id,
                    Category.user_id == user.id,
                )
                .first()
            )

        cat_account_id = parent.account_id if parent else plan.account_id
        cat_is_income = parent.is_income if parent else (1 if new_category_is_income else 0)
        cat_parent_id = parent.id if parent else None

        # Voorkom duplicaten op (user, account, parent, name)
        cat = (
            db.query(Category)
            .filter(
                Category.user_id == user.id,
                Category.account_id == cat_account_id,
                Category.parent_id.is_(cat_parent_id) if cat_parent_id is None else Category.parent_id == cat_parent_id,
                Category.name == name,
            )
            .first()
        )
        if not cat:
            max_order = (
                db.query(Category.sort_order)
                .filter(
                    Category.user_id == user.id,
                    Category.parent_id.is_(cat_parent_id) if cat_parent_id is None else Category.parent_id == cat_parent_id,
                )
                .order_by(Category.sort_order.desc())
                .first()
            )
            next_order = (max_order[0] + 1) if max_order and max_order[0] is not None else 0
            cat = Category(
                user_id=user.id,
                account_id=cat_account_id,
                parent_id=cat_parent_id,
                name=name,
                is_income=cat_is_income,
                sort_order=next_order,
            )
            db.add(cat)
            db.flush()
    else:
        if category_id:
            cat = (
                db.query(Category)
                .filter(Category.id == category_id, Category.user_id == user.id)
                .first()
            )

    # ── 2. Optionele matching-regel ───────────────────────────────
    if create_rule and cat and rule_match_value.strip():
        rule = Rule(
            user_id=user.id,
            name=f"Auto: {cat.name}"[:100],
            is_active=1,
            match_field=rule_match_field if rule_match_field in ("description", "counterparty", "counterparty_iban") else "description",
            match_type="contains",
            match_value=rule_match_value.strip(),
            condition_account_id=plan.account_id,
            assign_category_id=cat.id,
        )
        db.add(rule)
        db.flush()
        # Pas direct toe op bestaande transacties (alleen ongecategoriseerd)
        apply_single_rule(db, user.id, rule.id, only_uncategorized=True)

    # ── 3. SavingsLine + entries ──────────────────────────────────
    try:
        amount = Decimal(default_amount.replace(",", "."))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")

    tm = target_month or None
    months_for_line = _months_for_frequency(frequency, tm)

    max_order = (
        db.query(func.max(SavingsLine.sort_order))
        .filter(SavingsLine.plan_id == plan_id)
        .scalar()
    ) or 0

    line = SavingsLine(
        plan_id=plan_id,
        name=line_name.strip() or (cat.name if cat else "Nieuwe regel"),
        category_id=cat.id if cat else None,
        is_income=cat.is_income if cat else 0,
        frequency=frequency,
        default_amount=amount,
        annual_budget=amount * len(months_for_line),
        sort_order=max_order + 1,
    )
    db.add(line)
    db.flush()

    entries = _smart_fill_entries(line, target_month=tm)
    for entry in entries:
        db.add(entry)

    # Vul entries vanuit transacties als er een categorie is
    if cat:
        today = datetime.date.today()
        tx_totals = _get_transaction_totals_by_month(
            db, plan.account_id, plan.year, cat.id
        )
        for entry in entries:
            if entry.month in tx_totals:
                entry.amount = tx_totals[entry.month]
                entry.status = _determine_entry_status(
                    db, plan.account_id, plan.year, entry.month, today
                )

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
    remaining_suggestions: str = Form(""),
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

    # Create entries based on frequency
    entries = _smart_fill_entries(line)
    for entry in entries:
        db.add(entry)
    db.flush()

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

    # Pass remaining suggestions back so they don't disappear
    if remaining_suggestions.strip():
        return RedirectResponse(f"/savings/{plan_id}?suggestions={remaining_suggestions}", status_code=302)
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
