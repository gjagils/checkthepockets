"""Overboekingen tussen eigen rekeningen: paren vinden, koppelen en categoriseren (ACT-57).

Twee soorten, afgeleid van de eigenaren en rekeninggroepen:

* eigen rekening: beide rekeningen zitten in dezelfde groep of hebben dezelfde eigenaren. Beide kanten krijgen
  *Overboekingen › Eigen rekeningen* (uitgesloten van budget en totalen).
* tussen personen: een persoonlijke rekening betaalt aan de gezamenlijke rekening van die persoon. De afzender krijgt
  *Financieel › Bijdrage aan gezamenlijk*, de ontvanger *Inkomen › Bijdrage <naam>*.

Overboekingen van of naar een spaarrekening blijven bij hun eigen (Sparen-)categorie. Een bestaande categorie wordt
nooit overschreven. ``find_pairs`` en ``plan_*`` lezen alleen; ``link_and_classify`` schrijft (zonder commit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from app import clock
from app.models import Account, Category, Transaction

MAX_DAYS_APART = 3
OWN = ("Overboekingen", "Eigen rekeningen")
SENDER = ("Financieel", "Bijdrage aan gezamenlijk")


def _iban(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


@dataclass
class Pair:
    a: Transaction
    b: Transaction
    kind: str = ""                                          # "own" | "persons" | "" (onbekend/spaar)
    assignments: list[tuple[Transaction, tuple[str, str]]] = field(default_factory=list)


def find_pairs(db: Session, user_id: int, tx_ids=None, since_days: int | None = None) -> list[Pair]:
    """Paren van niet-gekoppelde boekingen: tegenrekening-IBAN is een andere eigen rekening, bedrag precies omgekeerd,
    ≤ 3 dagen verschil en precies één kandidaat. Twijfelgevallen blijven buiten beeld."""
    own = {_iban(a.iban): a.id for a in db.query(Account).filter(Account.user_id == user_id) if a.iban}
    if len(own) < 2:
        return []
    query = (
        db.query(Transaction).join(Account, Account.id == Transaction.account_id)
        .filter(Account.user_id == user_id, Transaction.transfer_id.is_(None), Transaction.is_projected == 0)
    )
    if tx_ids is not None:
        query = query.filter(Transaction.id.in_(list(tx_ids)))
    if since_days:
        query = query.filter(Transaction.date >= clock.today_nl() - timedelta(days=since_days))
    pairs: list[Pair] = []
    used: set[int] = set()
    for tx in query.order_by(Transaction.date, Transaction.id).all():
        if tx.id in used:
            continue
        other = own.get(_iban(tx.counterparty_iban))
        if other is None or other == tx.account_id:
            continue
        def candidates_for(source: Transaction, target_account_id: int) -> list[Transaction]:
            return (
                db.query(Transaction)
                .filter(
                    Transaction.account_id == target_account_id, Transaction.amount == -source.amount,
                    Transaction.transfer_id.is_(None), Transaction.is_projected == 0,
                    Transaction.date >= source.date - timedelta(days=MAX_DAYS_APART),
                    Transaction.date <= source.date + timedelta(days=MAX_DAYS_APART),
                ).all()
            )

        candidates = [c for c in candidates_for(tx, other) if c.id not in used]
        if len(candidates) != 1:
            continue
        # wederzijds uniek: ook de tegenboeking moet maar één kandidaat (deze) hebben
        if [c.id for c in candidates_for(candidates[0], tx.account_id) if c.id not in used] != [tx.id]:
            continue
        used.update({tx.id, candidates[0].id})
        pairs.append(Pair(tx, candidates[0]))
    return pairs


def _person_in(owner_name: str, sender_name: str) -> bool:
    """Gezamenlijke eigenaar: een andere persoon waarvan de naam die van de afzender bevat ("Nelleke/Gerd-Jan")."""
    return sender_name.lower() in owner_name.lower() and owner_name.lower() != sender_name.lower()


def _contribution_category(sender_name: str) -> tuple[str, str] | None:
    lower = sender_name.lower()
    if "gerd" in lower:
        return ("Inkomen", "Bijdrage Gerd-Jan")
    if "nelleke" in lower:
        return ("Inkomen", "Bijdrage Nelleke")
    return None


def classify(pair: Pair, accounts: dict[int, Account]) -> None:
    """Bepaalt soort en gewenste categorieën (zonder te schrijven)."""
    acc_a, acc_b = accounts[pair.a.account_id], accounts[pair.b.account_id]
    if acc_a.kind == "savings" or acc_b.kind == "savings":
        return
    owners_a, owners_b = {p.id for p in acc_a.owners}, {p.id for p in acc_b.owners}
    if (acc_a.group_id is not None and acc_a.group_id == acc_b.group_id) or (owners_a and owners_a == owners_b):
        pair.kind = "own"
        pair.assignments = [(pair.a, OWN), (pair.b, OWN)]
        return
    sender_tx, receiver_tx = (pair.a, pair.b) if pair.a.amount < 0 else (pair.b, pair.a)
    sender_acc, receiver_acc = accounts[sender_tx.account_id], accounts[receiver_tx.account_id]
    if len(sender_acc.owners) != 1:
        return
    sender = sender_acc.owners[0]
    joint = any(p.id != sender.id and (_person_in(p.name, sender.name)) for p in receiver_acc.owners) or (
        len(receiver_acc.owners) > 1 and sender.id in {p.id for p in receiver_acc.owners})
    contribution = _contribution_category(sender.name)
    if joint and contribution:
        pair.kind = "persons"
        pair.assignments = [(sender_tx, SENDER), (receiver_tx, contribution)]


def _shared_categories(db: Session, user_id: int) -> dict[tuple[str, str], Category]:
    cats = db.query(Category).filter(Category.user_id == user_id, Category.account_id.is_(None),
                                     Category.is_archived == 0).all()
    by_id = {c.id: c for c in cats}
    return {(by_id[c.parent_id].name, c.name): c for c in cats if c.parent_id in by_id}


def plan_pairs(db: Session, user_id: int, tx_ids=None, since_days: int | None = None) -> list[Pair]:
    accounts = {a.id: a for a in db.query(Account).options(joinedload(Account.owners)).filter(Account.user_id == user_id)}
    pairs = find_pairs(db, user_id, tx_ids, since_days)
    for pair in pairs:
        classify(pair, accounts)
    return pairs


@dataclass
class Result:
    linked: int = 0
    categorized: int = 0


def link_and_classify(db: Session, user_id: int, tx_ids=None, since_days: int | None = 120) -> Result:
    """Koppelt gevonden paren en zet ontbrekende categorieën. De aanroeper commit."""
    pairs = plan_pairs(db, user_id, tx_ids, since_days)
    if not pairs:
        return Result()
    cats = _shared_categories(db, user_id)
    result = Result()
    for pair in pairs:
        pair.a.transfer_id, pair.b.transfer_id = pair.b.id, pair.a.id
        result.linked += 1
        for tx, path in pair.assignments:
            category = cats.get(path)
            if category is not None and tx.category_id is None:
                tx.category_id = category.id
                result.categorized += 1
    db.flush()
    return result


def link_transfers(db: Session, user_id: int, transaction_ids) -> int:
    """Alleen koppelen (bunq-sync); geeft het aantal gekoppelde paren terug."""
    pairs = find_pairs(db, user_id, transaction_ids)
    for pair in pairs:
        pair.a.transfer_id, pair.b.transfer_id = pair.b.id, pair.a.id
    if pairs:
        db.flush()
    return len(pairs)


__all__ = ["Pair", "Result", "find_pairs", "plan_pairs", "link_and_classify", "link_transfers"]
