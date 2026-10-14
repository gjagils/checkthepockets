"""Look up an object that must belong to the logged-in user, or answer 404.

Convention for routes (docs/WORKFLOW.md): an id that does not exist *or* belongs to someone else is a
404 for page routes and JSON routes alike, never a silent redirect and never a 403 (which would reveal
that the object exists).
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Account, Transaction


def get_owned_or_404(db: Session, model, object_id, user_id: int, *, owner_column: str = "user_id"):
    obj = None
    if object_id is not None:
        obj = db.query(model).filter(
            model.id == object_id, getattr(model, owner_column) == user_id,
        ).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    return obj


def get_owned_transaction_or_404(db: Session, transaction_id, user_id: int) -> Transaction:
    """Transactions belong to a user through their account."""
    tx = None
    if transaction_id is not None:
        tx = (
            db.query(Transaction).join(Account, Account.id == Transaction.account_id)
            .filter(Transaction.id == transaction_id, Account.user_id == user_id).first()
        )
    if tx is None:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    return tx
