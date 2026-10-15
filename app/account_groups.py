"""Rekeninggroepen (ACT-55a): rekeningen die functioneel één rekening vormen."""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Account, AccountGroup


@event.listens_for(Session, "before_flush")
def _give_new_accounts_a_group(session, flush_context, instances):
    """Een nieuwe rekening start in een eigen groep, zodat elke rekening altijd een groep heeft."""
    for obj in list(session.new):
        if isinstance(obj, Account) and obj.group is None and obj.group_id is None:
            obj.group = AccountGroup(user_id=obj.user_id, name=obj.name)


def delete_empty_groups(db: Session, user_id: int) -> int:
    """Verwijder groepen zonder rekeningen (na verplaatsen, samenvoegen of verwijderen)."""
    empty = [
        g for g in db.query(AccountGroup).filter(AccountGroup.user_id == user_id).all()
        if not g.accounts
    ]
    for group in empty:
        db.delete(group)
    return len(empty)


def set_account_group(db: Session, account: Account, group_id: int | None) -> AccountGroup:
    """Zet een rekening in een bestaande groep, of in een nieuwe eigen groep (``None``)."""
    if group_id is None:
        if account.group is not None and len(account.group.accounts) == 1:
            return account.group  # staat al alleen in een eigen groep
        group = AccountGroup(user_id=account.user_id, name=account.name)
        db.add(group)
    else:
        group = (
            db.query(AccountGroup)
            .filter(AccountGroup.id == group_id, AccountGroup.user_id == account.user_id)
            .first()
        )
        if group is None:
            raise ValueError("Groep niet gevonden")
    account.group = group
    db.flush()
    delete_empty_groups(db, account.user_id)
    return group


def group_label(group: AccountGroup) -> str:
    """Naam voor in keuzelijsten: de groepsnaam, bij meerdere rekeningen met de rekeningnamen."""
    names = sorted(a.name for a in group.accounts)
    if len(names) <= 1:
        return group.name
    return f"{group.name} ({' + '.join(names)})"
