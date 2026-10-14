"""Query helpers shared by routers, middleware and the scheduler (kept out of the routers)."""
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
