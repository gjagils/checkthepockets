"""Koppel overboekingen tussen eigen rekeningen automatisch (transfer_id op beide kanten).

Voorzichtig: alleen als het tegenrekening-IBAN van een boeking een andere eigen rekening
is, het bedrag precies omgekeerd is, de datum hooguit 3 dagen verschilt en er precies
één kandidaat is. Alles wat twijfelachtig is blijft ongekoppeld (handmatig kan altijd).
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Account, Transaction

MAX_DAYS_APART = 3


def _iban(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


def link_transfers(db: Session, user_id: int, transaction_ids) -> int:
    """Try to pair the given (new) transactions with a counter booking. Returns pairs linked."""
    own = {_iban(a.iban): a.id for a in db.query(Account).filter(Account.user_id == user_id) if a.iban}
    if len(own) < 2:
        return 0
    linked = 0
    for tx in db.query(Transaction).filter(Transaction.id.in_(list(transaction_ids))).all():
        if tx.transfer_id is not None:
            continue
        other_account_id = own.get(_iban(tx.counterparty_iban))
        if other_account_id is None or other_account_id == tx.account_id:
            continue
        candidates = (
            db.query(Transaction)
            .filter(
                Transaction.account_id == other_account_id,
                Transaction.amount == -tx.amount,
                Transaction.transfer_id.is_(None),
                Transaction.is_projected == 0,
                Transaction.date >= tx.date - timedelta(days=MAX_DAYS_APART),
                Transaction.date <= tx.date + timedelta(days=MAX_DAYS_APART),
            )
            .all()
        )
        if len(candidates) != 1:
            continue
        partner = candidates[0]
        tx.transfer_id = partner.id
        partner.transfer_id = tx.id
        linked += 1
    if linked:
        db.flush()
    return linked
