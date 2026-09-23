"""Projected recurring transactions and linking of real transactions.

Shared by the recurring, transaction, budget and dashboard routes, the bank
sync and the scheduler; no HTTP handling here.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account, RecurringTransaction, Transaction
from app.recurring_schedule import get_period_range, is_active_in_month, projected_hash


def link_transaction_to_recurring(tx: Transaction, item: RecurringTransaction):
    """Link a transaction to a recurring item and apply category if missing."""
    tx.recurring_id = item.id
    if item.category_id and not tx.category_id:
        tx.category_id = item.category_id
        tx.is_reviewed = 1


def find_matching_transaction(
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
    fallback: list[Transaction] = []  # bedrag+datum matcht, tekst niet — tonen als back-up
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
        if search_terms and any(term in haystack for term in search_terms):
            matches.append(tx)
            if len(matches) >= limit:
                break
        else:
            if len(fallback) < limit:
                fallback.append(tx)

    # Geen tekst-matches? Toon dan bedrag+datum kandidaten (beperkt)
    if not matches and fallback:
        matches = fallback[:limit]
    return matches


def _cleanup_legacy_projected_hashes(db: Session, item_id: int, year: int, month: int) -> bool:
    """Delete any projected transactions with the old ISO-date hash format.
    Returns True if anything was deleted."""
    ref = date(year, month, 1)
    # The old format used period_start.isoformat(), e.g. "projected-5-2026-04-01"
    legacy_hash = f"projected-{item_id}-{ref.isoformat()}"
    canonical_hash = projected_hash(item_id, year, month)
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

            # Backfill account_id vanuit gekoppelde echte transacties wanneer NULL.
            # Voorkomt dat de projection op de laagst-id rekening (default_account) belandt
            # terwijl de recurring al een duidelijk bedoeld account heeft via linked tx.
            if not item.account_id:
                most_used_account_id = (
                    db.query(Transaction.account_id)
                    .filter(
                        Transaction.recurring_id == item.id,
                        Transaction.is_projected == 0,
                        Transaction.account_id.isnot(None),
                    )
                    .group_by(Transaction.account_id)
                    .order_by(func.count(Transaction.id).desc(), Transaction.account_id.asc())
                    .limit(1)
                    .scalar()
                )
                if most_used_account_id:
                    item.account_id = most_used_account_id
                    changed = True

            if not is_active_in_month(item, year, month):
                # Clean up any stale projected tx for this item+period
                proj_hash = projected_hash(item.id, year, month)
                stale = db.query(Transaction).filter(Transaction.import_hash == proj_hash).first()
                if stale:
                    db.delete(stale)
                    changed = True
                continue

            # Determine the period for this item's frequency in the given month
            period_start, period_end = get_period_range(item.frequency, ref)
            proj_hash = projected_hash(item.id, year, month)

            # Check if a real (non-projected) transaction already matches
            real_tx = find_matching_transaction(db, user_id, item, period_start, period_end)

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
                    # Update existing projected transaction in case amount/category/account changed
                    proj.amount = item.amount_expected
                    proj.description = item.name
                    proj.counterparty = item.counterparty or item.name
                    proj.category_id = item.category_id
                    proj.recurring_id = item.id
                    if item.account_id:
                        proj.account_id = item.account_id
                    changed = True
                else:
                    # Gebruik de gekoppelde rekening van de recurring indien aanwezig
                    proj_account_id = item.account_id or default_account.id
                    db.add(Transaction(
                        account_id=proj_account_id,
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
            # Projection op een andere rekening dan het item nu expliciet heeft
            # (bv. gemaakt toen item.account_id nog NULL was en op fallback belandde)
            if item.account_id and proj.account_id != item.account_id:
                db.delete(proj)
                changed = True
                continue
            period_start, period_end = get_period_range(item.frequency, proj.date)
            real_tx = find_matching_transaction(db, user_id, item, period_start, period_end)
            if real_tx:
                db.delete(proj)
                changed = True
    if changed:
        db.commit()


def find_recurring_candidates(
    db: Session, user_id: int, item: RecurringTransaction, linked_tx: Transaction
) -> list[Transaction]:
    """After a manual link, learn from the transaction's description/counterparty
    and find candidate transactions in other months that could be matched.
    Returns candidates (does NOT link them — caller decides to propose or auto-link).
    """
    # Build search words from the linked transaction (for Python filtering)
    desc = (linked_tx.description or "").strip()
    cp = (linked_tx.counterparty or "").strip()

    search_words = []
    if desc:
        item_words = item.name.lower().split()
        desc_lower = desc.lower()
        matching_words = [w for w in item_words if len(w) > 2 and w in desc_lower]
        if matching_words:
            search_words = matching_words
        elif cp:
            search_words = [cp.lower()]
        else:
            snippet = desc[:30].strip().lower()
            if len(snippet) > 5:
                search_words = [snippet]
    elif cp:
        search_words = [cp.lower()]

    if not search_words:
        return []

    # Update the recurring item's description_match if empty
    if not item.description_match and desc:
        item_words = item.name.lower().split()
        desc_lower = desc.lower()
        matching = [w for w in item_words if len(w) > 2 and w in desc_lower]
        if matching:
            item.description_match = " ".join(matching)

    # Find all unlinked transactions and filter in Python (encrypted fields)
    all_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.recurring_id.is_(None),
            Transaction.id != linked_tx.id,
        )
        .order_by(Transaction.date)
        .all()
    )
    all_candidates = []
    for tx in all_txs:
        tx_desc = (tx.description or "").lower()
        tx_cp = (tx.counterparty or "").lower()
        if all(w in tx_desc or w in tx_cp for w in search_words):
            all_candidates.append(tx)

    # Filter: one per period, same sign, no existing match
    result = []
    seen_periods = set()
    for candidate in all_candidates:
        period_start, period_end = get_period_range(item.frequency, candidate.date)
        period_key = (period_start, period_end)
        if period_key in seen_periods:
            continue

        existing = find_matching_transaction(db, user_id, item, period_start, period_end)
        if existing:
            seen_periods.add(period_key)
            continue

        if (candidate.amount > 0) != (linked_tx.amount > 0):
            continue

        result.append(candidate)
        seen_periods.add(period_key)

    return result


def auto_link_recurring_after_import(db: Session, user_id: int):
    """Called after CSV import — automatically link new transactions to recurring items
    based on counterparty/description matching. No user confirmation needed.
    Note: counterparty/description are encrypted, so we filter in Python."""
    recurring_items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user_id, RecurringTransaction.is_active == 1)
        .all()
    )

    # Load all unlinked transactions once (avoid N+1 on encrypted fields)
    all_unlinked = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.recurring_id.is_(None),
        )
        .order_by(Transaction.date)
        .all()
    )

    for item in recurring_items:
        if not item.counterparty and not item.description_match:
            continue

        # Build search terms
        cp_term = (item.counterparty or "").lower()
        desc_words = [w.lower() for w in (item.description_match or "").split() if len(w) > 2]

        if not cp_term and not desc_words:
            continue

        for candidate in all_unlinked:
            if candidate.recurring_id:
                continue  # Already linked by a previous item in this loop

            cp = (candidate.counterparty or "").lower()
            desc = (candidate.description or "").lower()

            # Match: counterparty contains search term OR all desc words found
            match = False
            if cp_term and cp_term in cp:
                match = True
            if not match and cp_term and cp_term in desc:
                match = True
            if not match and desc_words and all(w in desc for w in desc_words):
                match = True

            if not match:
                continue

            period_start, period_end = get_period_range(item.frequency, candidate.date)

            # Check if there's already a LINKED transaction for this recurring item
            # in this period. Don't use find_matching_transaction here because it
            # auto-matches and would find the candidate itself, skipping it forever.
            already_linked = (
                db.query(Transaction)
                .join(Account)
                .filter(
                    Account.user_id == user_id,
                    Transaction.recurring_id == item.id,
                    Transaction.date >= period_start,
                    Transaction.date <= period_end,
                    Transaction.is_projected == 0,
                )
                .first()
            )
            if already_linked:
                continue

            link_transaction_to_recurring(candidate, item)
