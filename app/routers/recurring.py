import calendar
import hashlib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import List

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.models import Account, Transaction, Category, RecurringTransaction, RecurringSuggestion
from app.auth import require_login
from app.template_config import templates

router = APIRouter()

FREQUENCIES = {
    "weekly": "Wekelijks",
    "monthly": "Maandelijks",
    "quarterly": "Per kwartaal",
    "yearly": "Jaarlijks",
}

NL_MONTH_ABBREVS = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]

MONTH_NAMES_NL = [
    "", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
    "Juli", "Augustus", "September", "Oktober", "November", "December",
]


def _get_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date for the current period based on frequency."""
    if frequency == "weekly":
        start = ref_date - timedelta(days=ref_date.weekday())
        end = start + timedelta(days=6)
    elif frequency == "monthly":
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    elif frequency == "quarterly":
        q_month = ((ref_date.month - 1) // 3) * 3 + 1
        start = date(ref_date.year, q_month, 1)
        end_month = q_month + 2
        end_year = ref_date.year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        last_day = calendar.monthrange(end_year, end_month)[1]
        end = date(end_year, end_month, last_day)
    elif frequency == "yearly":
        start = date(ref_date.year, 1, 1)
        end = date(ref_date.year, 12, 31)
    else:
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    return start, end


def _get_previous_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date of the period BEFORE the current one."""
    current_start, _ = _get_period_range(frequency, ref_date)
    prev_date = current_start - timedelta(days=1)
    return _get_period_range(frequency, prev_date)


def link_transaction_to_recurring(tx: Transaction, item: RecurringTransaction):
    """Link a transaction to a recurring item and apply category if missing."""
    tx.recurring_id = item.id
    if item.category_id and not tx.category_id:
        tx.category_id = item.category_id
        tx.is_reviewed = 1


def _find_matching_transaction(
    db: Session, user_id: int, recurring: RecurringTransaction, start: date, end: date
) -> Transaction | None:
    """Find a transaction matching this recurring item in the given period.
    Checks both auto-matching (counterparty/description) and manual links (recurring_id).
    """
    # First: check manually linked transactions
    linked = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.recurring_id == recurring.id,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .first()
    )
    if linked:
        return linked

    # Fall back to auto-matching by counterparty/description
    # Note: these fields are encrypted, so ILIKE won't work — filter in Python
    search_cp = (recurring.counterparty or "").lower()
    search_desc = (recurring.description_match or "").lower()
    if not search_cp and not search_desc:
        return None

    candidates = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .order_by(Transaction.date.desc())
        .all()
    )
    for tx in candidates:
        cp = (tx.counterparty or "").lower()
        desc = (tx.description or "").lower()
        if search_cp and search_cp in cp:
            return tx
        if search_cp and search_cp in desc:
            return tx
        if search_desc and search_desc in desc:
            return tx
    return None


def find_candidates_for_projected(
    db: Session,
    user_id: int,
    projected_tx: Transaction,
    days: int = 30,
    amount_tolerance: float = 0.15,
    limit: int = 10,
) -> list[Transaction]:
    """Find real transactions that might correspond to a projected (verwacht) transaction.

    Matches on:
    - same sign amount within ``amount_tolerance`` (default ±15%)
    - counterparty of the projected tx (or the linked recurring) is contained in
      the candidate's counterparty or description (case-insensitive)
    - within ``days`` (default ±30) of the projected date
    - same user, not excluded, not itself projected, not already linked to
      another recurring item
    """
    proj_amount = projected_tx.amount
    if proj_amount is None:
        return []
    proj_amount = Decimal(proj_amount)
    abs_amount = abs(proj_amount)
    delta = abs_amount * Decimal(str(amount_tolerance))
    amount_low = abs_amount - delta
    amount_high = abs_amount + delta

    start = projected_tx.date - timedelta(days=days)
    end = projected_tx.date + timedelta(days=days)

    # Collect search terms from projected tx + its recurring parent (if any)
    search_terms: list[str] = []
    for v in (projected_tx.counterparty, projected_tx.description):
        if v:
            search_terms.append(v.lower())
    if projected_tx.recurring_id:
        rec = db.query(RecurringTransaction).filter(
            RecurringTransaction.id == projected_tx.recurring_id
        ).first()
        if rec:
            if rec.counterparty:
                search_terms.append(rec.counterparty.lower())
            if rec.description_match:
                search_terms.append(rec.description_match.lower())
    # Deduplicate and drop very short terms (avoid matching "a", "bv")
    search_terms = [t for t in {s.strip() for s in search_terms} if len(t) >= 3]
    if not search_terms:
        return []

    # Encrypted fields → filter in Python. Query by date + sign + rough amount window.
    q = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.is_projected == 0,
            Transaction.is_excluded == 0,
            Transaction.date >= start,
            Transaction.date <= end,
        )
    )
    if proj_amount < 0:
        q = q.filter(Transaction.amount < 0)
    else:
        q = q.filter(Transaction.amount > 0)

    candidates = q.order_by(Transaction.date.desc()).all()

    matches: list[Transaction] = []
    for tx in candidates:
        if tx.amount is None:
            continue
        tx_abs = abs(Decimal(tx.amount))
        if tx_abs < amount_low or tx_abs > amount_high:
            continue
        # Skip ones already linked to the same recurring
        if projected_tx.recurring_id and tx.recurring_id == projected_tx.recurring_id:
            continue
        cp = (tx.counterparty or "").lower()
        desc = (tx.description or "").lower()
        haystack = cp + " " + desc
        if any(term in haystack for term in search_terms):
            matches.append(tx)
            if len(matches) >= limit:
                break
    return matches


def _parse_active_months(values: List[str]) -> str | None:
    """Convert list of month number strings to stored comma-separated string, or None for all."""
    nums = sorted({int(v) for v in values if v.isdigit() and 1 <= int(v) <= 12})
    if len(nums) == 12:
        return None  # all months = no restriction
    return ",".join(str(m) for m in nums) if nums else None


def _active_months_set(item: RecurringTransaction) -> set[int]:
    """Return the set of active month numbers for a recurring item (1-12). Empty = all."""
    if not item.active_months:
        return set(range(1, 13))
    try:
        return {int(m) for m in item.active_months.split(",") if m.strip()}
    except ValueError:
        return set(range(1, 13))


def _is_in_active_period(item: RecurringTransaction, today: date) -> bool:
    """Check if a recurring item is within its configured active period."""
    if item.start_date and item.start_date > today:
        return False
    if item.end_date and item.end_date < today:
        return False
    months = _active_months_set(item)
    if today.month not in months:
        return False
    return True


def _is_active_in_month(item: RecurringTransaction, year: int, month: int) -> bool:
    """Check if a recurring item should be active in the given year/month."""
    ref = date(year, month, 1)
    if item.start_date and item.start_date > date(year, month, calendar.monthrange(year, month)[1]):
        return False
    if item.end_date and item.end_date < ref:
        return False
    months = _active_months_set(item)
    if month not in months:
        return False
    return True


def _projected_hash(item_id: int, year: int, month: int) -> str:
    """Canonical hash for a projected transaction. Always use this function."""
    return f"projected-{item_id}-{year}-{month:02d}"


def _cleanup_legacy_projected_hashes(db: Session, item_id: int, year: int, month: int) -> bool:
    """Delete any projected transactions with the old ISO-date hash format.
    Returns True if anything was deleted."""
    ref = date(year, month, 1)
    # The old format used period_start.isoformat(), e.g. "projected-5-2026-04-01"
    legacy_hash = f"projected-{item_id}-{ref.isoformat()}"
    canonical_hash = _projected_hash(item_id, year, month)
    if legacy_hash == canonical_hash:
        return False  # Same format, nothing to clean
    legacy = db.query(Transaction).filter(Transaction.import_hash == legacy_hash).first()
    if legacy:
        db.delete(legacy)
        return True
    return False


def sync_projected_transactions(user_id: int, year: int, month: int, db: Session) -> None:
    """
    For the given month:
    - Create projected Transaction placeholders for active recurring items with no real match.
    - Delete projected placeholders where a real transaction now exists.
    - Skip months before the user's first real transaction (no data yet).
    Uses canonical hash format and cleans up legacy hashes to avoid duplicates.
    """
    ref = date(year, month, 1)

    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user_id, RecurringTransaction.is_active == 1)
        .all()
    )

    # Need at least one account to attach projected transactions to
    default_account = (
        db.query(Account)
        .filter(Account.user_id == user_id)
        .order_by(Account.id)
        .first()
    )
    if not default_account:
        return

    # Find the first real transaction date — don't create projections before this
    first_tx = (
        db.query(func.min(Transaction.date))
        .join(Account)
        .filter(Account.user_id == user_id, Transaction.is_projected == 0)
        .scalar()
    )
    # If no transactions at all, or this month is before the first transaction month: skip
    if first_tx and date(year, month, calendar.monthrange(year, month)[1]) < date(first_tx.year, first_tx.month, 1):
        # Clean up any stale projections for months before first data
        stale_projected = (
            db.query(Transaction)
            .join(Account)
            .filter(
                Account.user_id == user_id,
                Transaction.is_projected == 1,
                func.extract("year", Transaction.date) == year,
                func.extract("month", Transaction.date) == month,
            )
            .all()
        )
        for sp in stale_projected:
            db.delete(sp)
        if stale_projected:
            db.commit()
        return

    changed = False
    with db.no_autoflush:
        for item in recurring_items:
            # Always clean up legacy hash format first
            if _cleanup_legacy_projected_hashes(db, item.id, year, month):
                changed = True

            if not _is_active_in_month(item, year, month):
                # Clean up any stale projected tx for this item+period
                proj_hash = _projected_hash(item.id, year, month)
                stale = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
                if stale:
                    db.delete(stale)
                    changed = True
                continue

            # Determine the period for this item's frequency in the given month
            period_start, period_end = _get_period_range(item.frequency, ref)
            proj_hash = _projected_hash(item.id, year, month)

            # Check if a real (non-projected) transaction already matches
            real_tx = _find_matching_transaction(db, user_id, item, period_start, period_end)

            if real_tx:
                # Real match exists — delete projected placeholder if present
                proj = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
                if proj:
                    db.delete(proj)
                    changed = True
            else:
                # No real match — ensure projected placeholder exists (upsert logic)
                proj = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
                if proj:
                    # Update existing projected transaction in case amount/category changed
                    proj.amount = item.amount_expected
                    proj.description = item.name
                    proj.counterparty = item.counterparty or item.name
                    proj.category_id = item.category_id
                    proj.recurring_id = item.id
                    changed = True
                else:
                    db.add(Transaction(
                        account_id=default_account.id,
                        date=period_start,
                        amount=item.amount_expected,
                        currency="EUR",
                        description=item.name,
                        counterparty=item.counterparty or item.name,
                        import_hash=proj_hash,
                        is_projected=1,
                        is_excluded=0,
                        category_id=item.category_id,
                        recurring_id=item.id,
                    ))
                    changed = True

    if changed:
        db.commit()


def cleanup_matched_projected(user_id: int, db: Session) -> None:
    """Delete projected transactions that now have a matching real transaction.
    Also cleans up orphaned projected transactions (no recurring item, or inactive item)."""
    projected = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id, Transaction.is_projected == 1)
        .all()
    )
    changed = False
    with db.no_autoflush:
        for proj in projected:
            if not proj.recurring_id:
                db.delete(proj)
                changed = True
                continue
            item = db.query(RecurringTransaction).filter(
                RecurringTransaction.id == proj.recurring_id
            ).first()
            if not item:
                # Recurring item was deleted — remove orphaned projection
                db.delete(proj)
                changed = True
                continue
            if not item.is_active:
                # Recurring item was deactivated — remove projection
                db.delete(proj)
                changed = True
                continue
            period_start, period_end = _get_period_range(item.frequency, proj.date)
            real_tx = _find_matching_transaction(db, user_id, item, period_start, period_end)
            if real_tx:
                db.delete(proj)
                changed = True
    if changed:
        db.commit()


@router.post("/recurring/analyze")
def analyze_recurring(request: Request, db: Session = Depends(get_db)):
    """AI-powered detection of recurring transaction patterns."""
    user = require_login(request, db)

    # Fetch all non-excluded, non-projected transactions from last 18 months
    cutoff = date.today() - timedelta(days=548)
    transactions = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.date >= cutoff,
        )
        .all()
    )

    tx_data = [
        {
            "counterparty": tx.counterparty,
            "description": tx.description,
            "amount": tx.amount,
            "date": tx.date,
            "category_id": tx.category_id,
            "category_name": tx.category.name if tx.category else None,
        }
        for tx in transactions
    ]

    from app.ai_suggest import detect_recurring_patterns, enrich_recurring_with_ai, ai_available

    # Step 1: Python pattern detection
    candidates = detect_recurring_patterns(tx_data)

    if not candidates:
        return RedirectResponse("/recurring?analyze=empty", status_code=302)

    # Existing recurring names (to filter duplicates)
    existing = [
        r.name.lower()
        for r in db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id)
        .all()
    ]
    # Also add existing counterparty matches
    existing_cp = [
        r.counterparty.lower()
        for r in db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id, RecurringTransaction.counterparty.isnot(None))
        .all()
    ]

    # Filter out candidates that are already tracked
    filtered = [
        c for c in candidates
        if c["counterparty"].lower() not in existing
        and c["counterparty"].lower() not in existing_cp
    ]

    if not filtered:
        return RedirectResponse("/recurring?analyze=empty", status_code=302)

    # Step 2: AI enrichment (if available)
    categories = [
        {"id": c.id, "name": c.name}
        for c in db.query(Category).filter(Category.user_id == user.id).all()
    ]

    ai_results = None
    if ai_available():
        existing_names = [r.name for r in db.query(RecurringTransaction)
                          .filter(RecurringTransaction.user_id == user.id).all()]
        ai_results = enrich_recurring_with_ai(filtered, categories, existing_names)

    # Use AI results if available, otherwise use raw candidates
    suggestions = ai_results if ai_results else [
        {
            "name": c["counterparty"],
            "counterparty_match": c["counterparty"],
            "frequency": c["frequency"],
            "amount": c["avg_amount"],
            "category_id": c["category_id"],
            "category_name": c["category_name"],
            "reasoning": f"{c['count']}x gevonden, gem. elke {c['avg_days']} dagen",
        }
        for c in filtered[:15]
    ]

    # Clear old suggestions and write new ones to DB
    db.query(RecurringSuggestion).filter(RecurringSuggestion.user_id == user.id).delete()
    for s in suggestions:
        db.add(RecurringSuggestion(
            user_id=user.id,
            name=s.get("name") or s.get("counterparty_match") or "?",
            amount=Decimal(str(s["amount"])),
            frequency=s["frequency"],
            counterparty_match=s.get("counterparty_match") or s.get("name"),
            category_id=s.get("category_id"),
            category_name=s.get("category_name"),
            reasoning=s.get("reasoning"),
        ))
    db.commit()

    return RedirectResponse("/recurring?analyze=done", status_code=302)


def _render_recurring_page(
    request: Request, db: Session, user, *,
    from_tx: int | None = None,
    analyze_status: str = "",
):
    """Shared rendering logic for the recurring page (used by GET and POST analyze)."""
    today = date.today()

    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id)
        .order_by(RecurringTransaction.is_active.desc(), RecurringTransaction.name)
        .all()
    )

    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )

    # Find earliest real transaction — don't flag "missed" before this date
    first_tx_date = (
        db.query(func.min(Transaction.date))
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.is_projected == 0)
        .scalar()
    )

    # Load all linked transactions per recurring item (for display)
    linked_txs_by_item = {}
    all_linked = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.recurring_id.isnot(None),
            Transaction.is_projected == 0,
        )
        .order_by(Transaction.date.desc())
        .all()
    )
    for tx in all_linked:
        linked_txs_by_item.setdefault(tx.recurring_id, []).append(tx)

    items_active = []
    items_due = []
    items_missed = []
    items_inactive = []

    for item in recurring_items:
        in_period = _is_in_active_period(item, today)

        if not item.is_active or not in_period:
            cur_start, cur_end = _get_period_range(item.frequency, today)
            match = _find_matching_transaction(db, user.id, item, cur_start, cur_end)
            items_inactive.append({
                "item": item, "period_start": cur_start, "period_end": cur_end,
                "matched_transaction": match, "is_due": False, "in_active_period": in_period,
                "linked_transactions": linked_txs_by_item.get(item.id, []),
            })
            continue

        cur_start, cur_end = _get_period_range(item.frequency, today)
        cur_match = _find_matching_transaction(db, user.id, item, cur_start, cur_end)
        prev_start, prev_end = _get_previous_period_range(item.frequency, today)
        prev_match = _find_matching_transaction(db, user.id, item, prev_start, prev_end)

        # If previous period is before first transaction, treat as "not missed"
        prev_before_data = first_tx_date and prev_end < first_tx_date

        # Find candidate transactions for unmatched items (due/missed)
        candidates = []
        if cur_match is None:
            search_terms = []
            if item.counterparty:
                search_terms.append(item.counterparty.lower())
            if item.description_match:
                search_terms.extend([w.lower() for w in item.description_match.split() if len(w) > 2])
            if search_terms:
                period_txs = (
                    db.query(Transaction)
                    .join(Account)
                    .filter(
                        Account.user_id == user.id,
                        Transaction.is_excluded == 0,
                        Transaction.is_projected == 0,
                        Transaction.recurring_id.is_(None),
                        Transaction.date >= cur_start,
                        Transaction.date <= cur_end,
                    )
                    .order_by(Transaction.date.desc())
                    .all()
                )
                for tx in period_txs:
                    cp = (tx.counterparty or "").lower()
                    desc = (tx.description or "").lower()
                    if any(term in cp or term in desc for term in search_terms):
                        candidates.append(tx)

        entry = {
            "item": item, "period_start": cur_start, "period_end": cur_end,
            "matched_transaction": cur_match,
            "prev_period_start": prev_start, "prev_period_end": prev_end,
            "prev_matched_transaction": prev_match,
            "is_due": cur_match is None, "in_active_period": True,
            "linked_transactions": linked_txs_by_item.get(item.id, []),
            "candidates": candidates,
        }

        if cur_match:
            items_active.append(entry)
        elif prev_match is None and not prev_before_data:
            items_missed.append(entry)
        else:
            items_due.append(entry)

    # Pre-fill from AI suggestion
    from_suggestion_id = request.query_params.get("from_suggestion")
    suggestion_transactions = []

    prefill = None
    if from_suggestion_id:
        suggestion = db.query(RecurringSuggestion).filter(
            RecurringSuggestion.id == int(from_suggestion_id),
            RecurringSuggestion.user_id == user.id,
        ).first()
        if suggestion:
            prefill = {
                "name": suggestion.name,
                "amount_expected": float(suggestion.amount),
                "category_id": suggestion.category_id or "",
                "counterparty": suggestion.counterparty_match or "",
                "frequency": suggestion.frequency,
                "suggestion_id": suggestion.id,
                "tx_display": f"{suggestion.name} · AI-suggestie",
            }
            # Find matching transactions to show as evidence
            # Note: ILIKE doesn't work on encrypted fields, so we filter in Python
            if suggestion.counterparty_match:
                search_term = suggestion.counterparty_match.lower()
                cutoff = date.today() - timedelta(days=548)
                all_txs = (
                    db.query(Transaction)
                    .join(Account)
                    .filter(
                        Account.user_id == user.id,
                        Transaction.is_excluded == 0,
                        Transaction.is_projected == 0,
                        Transaction.date >= cutoff,
                    )
                    .order_by(Transaction.date.desc())
                    .all()
                )
                suggestion_transactions = [
                    tx for tx in all_txs
                    if (tx.counterparty and search_term in tx.counterparty.lower())
                    or (tx.description and search_term in tx.description.lower())
                ][:20]

    if not prefill and from_tx:
        tx = (
            db.query(Transaction).join(Account)
            .filter(Transaction.id == from_tx, Account.user_id == user.id)
            .first()
        )
        if tx:
            prefill = {
                "name": tx.counterparty or tx.description or "",
                "amount_expected": float(tx.amount),
                "category_id": tx.category_id or "",
                "counterparty": tx.counterparty or "",
                "tx_display": f"{tx.counterparty or tx.description or '?'}  ·  €{tx.amount}",
            }

    return templates.TemplateResponse(
        "recurring/list.html",
        {
            "request": request, "user": user,
            "items_active": items_active, "items_due": items_due,
            "items_missed": items_missed, "items_inactive": items_inactive,
            "categories": categories, "frequencies": FREQUENCIES,
            "nl_month_abbrevs": NL_MONTH_ABBREVS,
            "total_active": len(items_active), "total_due": len(items_due),
            "total_missed": len(items_missed), "today": today,
            "prefill": prefill,
            "suggestion_transactions": suggestion_transactions,
            "recurring_suggestions": db.query(RecurringSuggestion)
                .filter(RecurringSuggestion.user_id == user.id)
                .order_by(RecurringSuggestion.id)
                .all(),
            "analyze_status": analyze_status,
            "show_analyze_btn": True,
        },
    )


@router.get("/recurring")
def recurring_list(
    request: Request,
    from_tx: int = Query(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    analyze_status = request.query_params.get("analyze", "")
    return _render_recurring_page(request, db, user, from_tx=from_tx, analyze_status=analyze_status)


@router.post("/recurring/suggestion/{suggestion_id}/accept")
def accept_suggestion(suggestion_id: int, request: Request, db: Session = Depends(get_db)):
    """Accept an AI suggestion — creates a RecurringTransaction and deletes the suggestion."""
    user = require_login(request, db)
    s = db.query(RecurringSuggestion).filter(
        RecurringSuggestion.id == suggestion_id, RecurringSuggestion.user_id == user.id
    ).first()
    if s:
        item = RecurringTransaction(
            user_id=user.id,
            name=s.name,
            amount_expected=s.amount,
            frequency=s.frequency,
            counterparty=s.counterparty_match,
            category_id=s.category_id,
        )
        db.add(item)
        db.flush()  # Get item.id

        # Auto-link matching transactions to this new recurring item
        # Note: counterparty is encrypted, so ILIKE won't work — filter in Python
        if item.counterparty:
            search_term = item.counterparty.lower()
            all_txs = (
                db.query(Transaction)
                .join(Account)
                .filter(
                    Account.user_id == user.id,
                    Transaction.is_excluded == 0,
                    Transaction.is_projected == 0,
                    Transaction.recurring_id.is_(None),
                )
                .order_by(Transaction.date.desc())
                .all()
            )
            seen_periods = set()
            for tx in all_txs:
                cp = (tx.counterparty or "").lower()
                desc = (tx.description or "").lower()
                if search_term not in cp and search_term not in desc:
                    continue
                period_start, period_end = _get_period_range(item.frequency, tx.date)
                period_key = f"{period_start}-{period_end}"
                if period_key in seen_periods:
                    continue
                seen_periods.add(period_key)
                link_transaction_to_recurring(tx, item)

        db.delete(s)
        db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/suggestion/{suggestion_id}/dismiss")
def dismiss_suggestion(suggestion_id: int, request: Request, db: Session = Depends(get_db)):
    """Dismiss an AI suggestion — deletes it without creating a recurring item."""
    user = require_login(request, db)
    s = db.query(RecurringSuggestion).filter(
        RecurringSuggestion.id == suggestion_id, RecurringSuggestion.user_id == user.id
    ).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring")
async def create_recurring(
    request: Request,
    name: str = Form(...),
    amount_expected: str = Form(...),
    frequency: str = Form(...),
    category_id: str = Form(""),
    counterparty: str = Form(""),
    description_match: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    active_months: List[str] = Form(default=[]),
    link_tx_ids: List[str] = Form(default=[]),
    dismiss_suggestion_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse("/recurring", status_code=302)
    if frequency not in FREQUENCIES:
        return RedirectResponse("/recurring", status_code=302)

    try:
        parsed_amount = Decimal(amount_expected.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse("/recurring", status_code=302)

    cat_id = int(category_id) if category_id.strip() else None
    if cat_id:
        cat = db.query(Category).filter(
            Category.id == cat_id, Category.user_id == user.id
        ).first()
        if not cat:
            cat_id = None

    from datetime import date as date_type
    parsed_start = None
    parsed_end = None
    try:
        if start_date.strip():
            parsed_start = date_type.fromisoformat(start_date.strip())
        if end_date.strip():
            parsed_end = date_type.fromisoformat(end_date.strip())
    except ValueError:
        pass

    item = RecurringTransaction(
        user_id=user.id,
        name=name,
        amount_expected=parsed_amount,
        frequency=frequency,
        category_id=cat_id,
        counterparty=counterparty.strip() or None,
        description_match=description_match.strip() or None,
        start_date=parsed_start,
        end_date=parsed_end,
        active_months=_parse_active_months(active_months),
    )
    db.add(item)
    db.flush()

    # Delete the AI suggestion if this was created from one
    if dismiss_suggestion_id.strip().isdigit():
        suggestion = db.query(RecurringSuggestion).filter(
            RecurringSuggestion.id == int(dismiss_suggestion_id),
            RecurringSuggestion.user_id == user.id,
        ).first()
        if suggestion:
            db.delete(suggestion)

    # Link selected transactions and update dates if changed
    if link_tx_ids:
        tx_ids = [int(tid) for tid in link_tx_ids if tid.strip().isdigit()]
        if tx_ids:
            # Read date overrides from form
            form_data = await request.form()
            txs = (
                db.query(Transaction)
                .join(Account)
                .filter(
                    Transaction.id.in_(tx_ids),
                    Account.user_id == user.id,
                )
                .all()
            )
            for tx in txs:
                link_transaction_to_recurring(tx, item)
                # Update date if user changed it
                new_date_str = form_data.get(f"tx_date_{tx.id}", "")
                if new_date_str:
                    try:
                        new_date = date_type.fromisoformat(new_date_str)
                        if new_date != tx.date:
                            tx.date = new_date
                    except ValueError:
                        pass

    db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/link-selected")
async def link_selected_transactions(
    item_id: int,
    request: Request,
    transaction_ids: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Link multiple selected transactions to a recurring item, with optional date changes."""
    user = require_login(request, db)

    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse("/recurring", status_code=302)

    tx_ids = [int(tid) for tid in transaction_ids if tid.strip().isdigit()]
    if tx_ids:
        form_data = await request.form()
        txs = (
            db.query(Transaction)
            .join(Account)
            .filter(Transaction.id.in_(tx_ids), Account.user_id == user.id)
            .all()
        )
        from datetime import date as date_type
        for tx in txs:
            link_transaction_to_recurring(tx, item)
            new_date_str = form_data.get(f"tx_date_{tx.id}", "")
            if new_date_str:
                try:
                    new_date = date_type.fromisoformat(new_date_str)
                    if new_date != tx.date:
                        tx.date = new_date
                except ValueError:
                    pass
        db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/relink-all")
def relink_all(
    request: Request,
    db: Session = Depends(get_db),
):
    """Re-run auto-linking: match unlinked transactions to recurring items,
    then cleanup and sync projected transactions."""
    user = require_login(request, db)

    from app.routers.transactions import auto_link_recurring_after_import
    from datetime import date

    auto_link_recurring_after_import(db, user.id)

    cleanup_matched_projected(user.id, db)

    today = date.today()
    for offset in range(0, 3):
        m = today.month + offset
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        sync_projected_transactions(user.id, y, m, db)

    db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/apply-all-categories")
def apply_all_categories(
    request: Request,
    db: Session = Depends(get_db),
):
    """Apply categories from ALL recurring items to their linked transactions."""
    user = require_login(request, db)

    items = (
        db.query(RecurringTransaction)
        .filter(
            RecurringTransaction.user_id == user.id,
            RecurringTransaction.category_id.isnot(None),
        )
        .all()
    )

    updated = 0
    for item in items:
        linked_txs = (
            db.query(Transaction)
            .join(Account)
            .filter(
                Account.user_id == user.id,
                Transaction.recurring_id == item.id,
                Transaction.is_projected == 0,
                Transaction.category_id.is_(None),
            )
            .all()
        )
        for tx in linked_txs:
            tx.category_id = item.category_id
            tx.is_reviewed = 1
            updated += 1

    db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/apply-category")
def apply_category_to_linked(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Apply the recurring item's category to all linked transactions that don't have one."""
    user = require_login(request, db)

    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item or not item.category_id:
        return RedirectResponse("/recurring", status_code=302)

    linked_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.recurring_id == item.id,
            Transaction.is_projected == 0,
            Transaction.category_id.is_(None),
        )
        .all()
    )
    for tx in linked_txs:
        tx.category_id = item.category_id
        tx.is_reviewed = 1

    db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/edit")
def edit_recurring(
    item_id: int,
    request: Request,
    name: str = Form(...),
    amount_expected: str = Form(...),
    frequency: str = Form(...),
    category_id: str = Form(""),
    counterparty: str = Form(""),
    description_match: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    active_months: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse("/recurring", status_code=302)

    name = name.strip()
    if not name:
        return RedirectResponse("/recurring", status_code=302)

    try:
        parsed_amount = Decimal(amount_expected.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return RedirectResponse("/recurring", status_code=302)

    from datetime import date as date_type
    parsed_start = None
    parsed_end = None
    try:
        if start_date.strip():
            parsed_start = date_type.fromisoformat(start_date.strip())
        if end_date.strip():
            parsed_end = date_type.fromisoformat(end_date.strip())
    except ValueError:
        pass

    item.name = name
    item.amount_expected = parsed_amount
    item.frequency = frequency if frequency in FREQUENCIES else item.frequency
    item.counterparty = counterparty.strip() or None
    item.description_match = description_match.strip() or None
    item.start_date = parsed_start
    item.end_date = parsed_end
    item.active_months = _parse_active_months(active_months)

    cat_id = int(category_id) if category_id.strip() else None
    if cat_id:
        cat = db.query(Category).filter(
            Category.id == cat_id, Category.user_id == user.id
        ).first()
        item.category_id = cat.id if cat else None
    else:
        item.category_id = None

    db.commit()

    # Delete ALL projected transactions for this item (frequency may have changed)
    from app.models import Transaction as Tx
    stale = (
        db.query(Tx)
        .filter(Tx.recurring_id == item.id, Tx.is_projected == 1)
        .all()
    )
    for s in stale:
        db.delete(s)
    db.commit()

    # Re-sync projected for current month with new settings
    today = date.today()
    sync_projected_transactions(user.id, today.year, today.month, db)

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/link")
def link_transaction(
    item_id: int,
    request: Request,
    transaction_id: int = Form(...),
    redirect_to: str = Form(""),
    shift_to_date: str = Form(""),
    db: Session = Depends(get_db),
):
    """Manually link a transaction to a recurring item.

    Als ``shift_to_date`` wordt meegegeven (YYYY-MM-DD) en de periode van die
    datum afwijkt van de periode waarin de transactie nu valt, wordt de
    zichtbare datum verschoven en de originele bankdatum bewaard in
    ``original_date``.
    """
    user = require_login(request, db)

    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if not item:
        return RedirectResponse("/recurring", status_code=302)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if tx:
        if shift_to_date:
            try:
                target_date = date.fromisoformat(shift_to_date)
            except ValueError:
                target_date = None
            if target_date:
                cur_start, cur_end = _get_period_range(item.frequency, tx.date)
                if not (cur_start <= target_date <= cur_end):
                    # Verschuiven: bewaar oorspronkelijke datum eenmalig
                    if tx.original_date is None:
                        tx.original_date = tx.date
                    tx.date = target_date
        link_transaction_to_recurring(tx, item)
        # Remove any projected transactions for this recurring in the same period
        # so the "verwacht" rij verdwijnt zodra je gekoppeld hebt.
        cleanup_matched_projected(user.id, db)
        db.commit()

    target = redirect_to if redirect_to.startswith("/") else "/recurring"
    return RedirectResponse(target, status_code=302)


@router.post("/recurring/{item_id}/unlink")
def unlink_transaction(
    item_id: int,
    request: Request,
    transaction_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Remove manual link between a transaction and a recurring item."""
    user = require_login(request, db)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if tx and tx.recurring_id == item_id:
        tx.recurring_id = None
        db.commit()

    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/toggle")
def toggle_recurring(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if item:
        item.is_active = 0 if item.is_active else 1
        db.commit()
    return RedirectResponse("/recurring", status_code=302)


@router.post("/recurring/{item_id}/delete")
def delete_recurring(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    item = db.query(RecurringTransaction).filter(
        RecurringTransaction.id == item_id, RecurringTransaction.user_id == user.id
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/recurring", status_code=302)
