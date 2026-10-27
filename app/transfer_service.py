"""Overboekingen tussen eigen rekeningen: paren vinden, koppelen en categoriseren (ACT-57).

Twee soorten, afgeleid van de eigenaren en rekeninggroepen:

* eigen rekening: beide rekeningen zitten in dezelfde groep of hebben dezelfde eigenaren. Beide kanten krijgen
  *Overboekingen › Eigen rekeningen* (uitgesloten van budget en totalen).
* tussen personen: een persoonlijke rekening betaalt aan de gezamenlijke rekening van die persoon. De afzender krijgt
  *Financieel › Bijdrage aan gezamenlijk*, de ontvanger *Inkomen › Bijdrage <naam>*.

* storting op een spaarrekening (ACT-59): alleen een *vast* bedrag, dus hetzelfde bedrag tussen dezelfde twee
  rekeningen in minstens drie opeenvolgende maanden. Beide kanten krijgen *Sparen › Storting Gerd-Jan/Nelleke* (afzender
  van één persoon), *Sparen › Storting samen* (gezamenlijke afzender) of *Kinderen › <naam>* (spaarrekening van een
  ander, zoals een kind). Terugboekingen van spaar naar betaal en incidentele bedragen blijven ongemoeid.

Een bestaande categorie wordt nooit overschreven. Al gekoppelde paren met een lege kant (bijv. gekoppeld door de
bunq-sync) worden ook ingedeeld. ``find_pairs`` en ``plan_*`` lezen alleen; ``link_and_classify`` schrijft (zonder commit).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app import clock
from app.models import Account, Category, Transaction

MAX_DAYS_APART = 3
OWN = ("Overboekingen", "Eigen rekeningen")
SENDER = ("Financieel", "Bijdrage aan gezamenlijk")
SAVINGS_JOINT = ("Sparen", "Storting samen")
# Een vast stortingsbedrag: minstens zoveel keer achter elkaar met een tussenpoos van ongeveer een maand.
REGULAR_MIN_RUN = 3
REGULAR_GAP_DAYS = (20, 40)


def _iban(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


# ABN AMRO schrijft het IBAN van de tegenrekening bij periodieke overboekingen alleen in de omschrijving:
# "SEPA Periodieke overb. IBAN: NL47ABNA0468808086 BIC: ABNANL2A Naam: ..."
_IBAN_IN_TEXT = re.compile(r"IBAN:\s*([A-Z]{2}\d{2}[A-Z0-9]{10,30})")


def counterparty_iban(tx: Transaction) -> str:
    """IBAN van de tegenrekening: het veld, of anders het IBAN uit de omschrijving."""
    iban = _iban(tx.counterparty_iban)
    if iban:
        return iban
    match = _IBAN_IN_TEXT.search((tx.description or "").upper())
    return match.group(1) if match else ""


@dataclass
class Pair:
    a: Transaction
    b: Transaction
    kind: str = ""                                          # "own" | "persons" | "savings" | "" (alleen koppelen)
    assignments: list[tuple[Transaction, tuple[str, str]]] = field(default_factory=list)
    linked: bool = False                                    # al gekoppeld; alleen lege categorieën aanvullen


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
        other = own.get(counterparty_iban(tx))
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


def _is_joint(account: Account) -> bool:
    """Gezamenlijke rekening: meer eigenaren, of één eigenaar als "Nelleke & Gerd-Jan" / "Nelleke/Gerd-Jan"."""
    return len(account.owners) > 1 or any(re.search(r"[&/]", p.name) for p in account.owners)


def _savings_category(sender_acc: Account, receiver_acc: Account) -> tuple[str, str] | None:
    """Categorie voor een storting van een betaal- naar een spaarrekening."""
    sender_ids = {p.id for p in sender_acc.owners}
    if len(receiver_acc.owners) == 1 and not _is_joint(receiver_acc):
        beneficiary = receiver_acc.owners[0]
        if beneficiary.id not in sender_ids and _contribution_category(beneficiary.name) is None:
            return ("Kinderen", beneficiary.name)      # spaarrekening van een ander, bijv. een kind
    if _is_joint(sender_acc):
        return SAVINGS_JOINT
    if len(sender_acc.owners) == 1:
        contribution = _contribution_category(sender_acc.owners[0].name)
        if contribution:
            return ("Sparen", contribution[1].replace("Bijdrage", "Storting"))
    return None


def has_monthly_run(dates: list[date]) -> bool:
    """Minstens REGULAR_MIN_RUN data achter elkaar met telkens ongeveer een maand ertussen."""
    low, high = REGULAR_GAP_DAYS
    run = 1
    ordered = sorted(set(dates))
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if low <= (cur - prev).days <= high else 1
        if run >= REGULAR_MIN_RUN:
            return True
    return False


class _Regularity:
    """Is het bedrag van een overboeking een vast bedrag tussen deze twee rekeningen? Kijkt naar de hele historie."""

    def __init__(self, db: Session, accounts: dict[int, Account]):
        self.db, self.accounts, self.cache = db, accounts, {}

    def _dates(self, account_id: int, amount, other_account_id: int) -> list[date]:
        other_iban = _iban(self.accounts[other_account_id].iban)
        rows = self.db.query(Transaction).filter(
            Transaction.account_id == account_id, Transaction.amount == amount, Transaction.is_projected == 0,
        ).all()
        return [t.date for t in rows
                if (other_iban and counterparty_iban(t) == other_iban) or self._partner_on(t, other_account_id)]

    def _partner_on(self, tx: Transaction, account_id: int) -> bool:
        if tx.transfer_id is None:
            return False
        partner = self.db.get(Transaction, tx.transfer_id)
        return partner is not None and partner.account_id == account_id

    def __call__(self, sender_tx: Transaction, receiver_tx: Transaction) -> bool:
        key = (sender_tx.account_id, receiver_tx.account_id, abs(sender_tx.amount))
        if key not in self.cache:
            received = self._dates(receiver_tx.account_id, abs(sender_tx.amount), sender_tx.account_id)
            sent = self._dates(sender_tx.account_id, -abs(sender_tx.amount), receiver_tx.account_id)
            self.cache[key] = has_monthly_run(received) or has_monthly_run(sent)
        return self.cache[key]


def classify(pair: Pair, accounts: dict[int, Account],
             is_regular: Callable[[Transaction, Transaction], bool] | None = None) -> None:
    """Bepaalt soort en gewenste categorieën (zonder te schrijven)."""
    acc_a, acc_b = accounts[pair.a.account_id], accounts[pair.b.account_id]
    if acc_a.kind == "savings" or acc_b.kind == "savings":
        sender_tx, receiver_tx = (pair.a, pair.b) if pair.a.amount < 0 else (pair.b, pair.a)
        sender_acc, receiver_acc = accounts[sender_tx.account_id], accounts[receiver_tx.account_id]
        # Alleen stortingen van betaal naar spaar; terugboekingen en spaar-naar-spaar blijven ongemoeid.
        if receiver_acc.kind != "savings" or sender_acc.kind == "savings":
            return
        path = _savings_category(sender_acc, receiver_acc)
        if path and is_regular is not None and is_regular(sender_tx, receiver_tx):
            pair.kind = "savings"
            pair.assignments = [(sender_tx, path), (receiver_tx, path)]
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


def linked_pairs_to_fill(db: Session, user_id: int, since_days: int | None = None) -> list[Pair]:
    """Al gekoppelde paren waarvan minstens één kant nog geen categorie heeft."""
    query = (
        db.query(Transaction).join(Account, Account.id == Transaction.account_id)
        .filter(Account.user_id == user_id, Transaction.transfer_id.isnot(None), Transaction.category_id.is_(None),
                Transaction.is_projected == 0)
    )
    if since_days:
        query = query.filter(Transaction.date >= clock.today_nl() - timedelta(days=since_days))
    pairs, seen = [], set()
    for tx in query.order_by(Transaction.date, Transaction.id).all():
        if tx.id in seen:
            continue
        partner = db.get(Transaction, tx.transfer_id)
        if partner is None or partner.transfer_id != tx.id:
            continue
        seen.update({tx.id, partner.id})
        pairs.append(Pair(tx, partner, linked=True))
    return pairs


def plan_pairs(db: Session, user_id: int, tx_ids=None, since_days: int | None = None,
               include_linked: bool = False) -> list[Pair]:
    accounts = {a.id: a for a in db.query(Account).options(joinedload(Account.owners)).filter(Account.user_id == user_id)}
    pairs = find_pairs(db, user_id, tx_ids, since_days)
    if include_linked and tx_ids is None:
        pairs += linked_pairs_to_fill(db, user_id, since_days)
    is_regular = _Regularity(db, accounts)
    for pair in pairs:
        classify(pair, accounts, is_regular)
    return pairs


@dataclass
class Result:
    linked: int = 0
    categorized: int = 0


def link_and_classify(db: Session, user_id: int, tx_ids=None, since_days: int | None = 120) -> Result:
    """Koppelt gevonden paren en zet ontbrekende categorieën. De aanroeper commit."""
    pairs = plan_pairs(db, user_id, tx_ids, since_days, include_linked=True)
    if not pairs:
        return Result()
    cats = _shared_categories(db, user_id)
    result = Result()
    for pair in pairs:
        if not pair.linked:
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


__all__ = ["Pair", "Result", "find_pairs", "plan_pairs", "link_and_classify", "link_transfers", "has_monthly_run"]
