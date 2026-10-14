"""Query helpers shared by routers, middleware and the scheduler (kept out of the routers)."""
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import Account, Transaction


def inbox_query(db: Session, user_id: int):
    """Transacties zonder categorie, excl. split-parents, projecties en excluded."""
    split_parent_ids = (
        db.query(Transaction.parent_id)
        .filter(Transaction.parent_id.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    return (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.account))
        .filter(
            Account.user_id == user_id,
            Transaction.category_id.is_(None),
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.id.notin_(split_parent_ids),
        )
    )


def inbox_count(db: Session, user_id: int) -> int:
    return inbox_query(db, user_id).count()


def transaction_years(db: Session, user_id: int, *extra_years: int) -> list[int]:
    """Sorted years in which the user has transactions, plus `extra_years` (e.g. the current year)."""
    rows = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user_id)
        .distinct()
        .all()
    )
    return sorted({int(row.yr) for row in rows} | set(extra_years))
