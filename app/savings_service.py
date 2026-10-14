"""Savings plan queries that the router needs more than once (kept out of app/routers/savings.py)."""
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Transaction


def transaction_totals_by_category(db: Session, account_id: int, year: int, category_ids) -> dict[int, dict[int, Decimal]]:
    """{category_id: {month: total}} of real transactions on the account in `year`, in one query.

    Same filters as the per-category helper in the router (no excluded or projected transactions);
    replaces one query per category line (and per month on top of that for the December balance).
    """
    category_ids = {c for c in category_ids if c}
    totals: dict[int, dict[int, Decimal]] = {c: {} for c in category_ids}
    if not category_ids:
        return totals
    rows = (
        db.query(
            Transaction.category_id,
            func.extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        )
        .filter(
            Transaction.account_id == account_id,
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.category_id.in_(category_ids),
            func.extract("year", Transaction.date) == year,
        )
        .group_by(Transaction.category_id, func.extract("month", Transaction.date))
        .all()
    )
    for category_id, month, total in rows:
        totals[category_id][int(month)] = total
    return totals
