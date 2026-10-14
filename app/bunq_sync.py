"""bunq-synchronisatie (ACT-31b): rekeningen koppelen en betalingen importeren.

Betalingen krijgen een eigen identiteit (het bunq-id) in de import_hash, zodat twee
identieke betalingen op één dag allebei bewaard worden. Betalingen die al uit een
CSV-import op dezelfde rekening staan worden herkend op datum, bedrag en tegenpartij of
omschrijving (één-op-één) en overgeslagen, zodat een eerdere CSV-historie niet dubbel komt.
"""
import datetime
import logging
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.account_merge import _same_booking
from app.bunq_client import BunqAccount, BunqClient, BunqError, BunqPayment, BunqSession
from app.import_service import existing_import_hashes, store_parsed_transactions
from app.models import Account, BunqAccountLink, BunqConnection, ImportBatch, Rule, Transaction
from app.parsers.base import ParsedTransaction
from app.transfer_linking import link_transfers

logger = logging.getLogger(__name__)

BUNQ_SOURCE = "bunq"


@dataclass
class LinkReport:
    link: BunqAccountLink
    fetched: int = 0
    new: int = 0
    already_imported: int = 0
    matched_existing: int = 0   # staat al via CSV (of andere bron) op deze rekening
    transfers_linked: int = 0
    error: str | None = None


def _iban_key(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


def account_kind_for(bunq_kind: str | None) -> str:
    return "savings" if bunq_kind and "Savings" in bunq_kind else "payment"


def refresh_links(db: Session, connection: BunqConnection, accounts: list[BunqAccount]) -> list[BunqAccountLink]:
    """Upsert the links with what bunq reports now; keeps the user's choices."""
    existing = {l.bunq_account_id: l for l in db.query(BunqAccountLink).filter_by(connection_id=connection.id)}
    for acc in accounts:
        link = existing.get(acc.id)
        if link is None:
            link = BunqAccountLink(connection_id=connection.id, bunq_account_id=acc.id, enabled=0)
            db.add(link)
            existing[acc.id] = link
        link.description = acc.description
        link.iban = acc.iban
        link.bunq_kind = acc.kind
        link.bunq_status = acc.status
        link.balance = acc.balance
    db.flush()
    return sorted(existing.values(), key=lambda l: (l.bunq_status != "ACTIVE", l.description or ""))


def resolve_account(db: Session, user_id: int, link: BunqAccountLink, choice: str, kind: str) -> Account:
    """Find or create the own account a bunq account imports into.

    `choice` is "auto" (match on IBAN, else create), "new", or an existing account id.
    """
    kind = kind if kind in ("payment", "savings") else account_kind_for(link.bunq_kind)
    account = None
    if choice.isdigit():
        account = db.query(Account).filter(Account.id == int(choice), Account.user_id == user_id).first()
    elif choice == "auto":
        account = next(
            (a for a in db.query(Account).filter(Account.user_id == user_id)
             if a.iban and _iban_key(a.iban) == _iban_key(link.iban)), None)
    if account is None:
        account = Account(user_id=user_id, name=link.description or link.iban or "bunq", iban=link.iban,
                          bank="bunq", kind=kind)
        db.add(account)
        db.flush()
    else:
        account.kind = kind
        if not account.iban and link.iban:
            account.iban = link.iban
    return account


def _to_parsed(payment: BunqPayment) -> ParsedTransaction:
    return ParsedTransaction(
        date=payment.booked_on,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        counterparty=payment.counterparty_name,
        counterparty_iban=payment.counterparty_iban,
        balance_after=payment.balance_after,
        external_id=str(payment.id),
    )


def _existing_pool(db: Session, account: Account) -> dict[tuple, list[Transaction]]:
    """Transactions on this account that did not come from a bunq sync (e.g. CSV)."""
    rows = (
        db.query(Transaction)
        .outerjoin(ImportBatch, Transaction.import_batch_id == ImportBatch.id)
        .filter(Transaction.account_id == account.id,
                or_(ImportBatch.id.is_(None), ImportBatch.source != BUNQ_SOURCE))
        .order_by(Transaction.id)
    )
    pool: dict[tuple, list[Transaction]] = {}
    for tx in rows:
        pool.setdefault((tx.date, tx.amount), []).append(tx)
    return pool


def sync_link(db: Session, client: BunqClient, session: BunqSession, link: BunqAccountLink,
              user_id: int, dry_run: bool) -> LinkReport:
    report = LinkReport(link=link)
    account = link.account
    if account is None:
        report.error = "Geen eigen rekening gekoppeld."
        return report
    try:
        payments = client.list_payments(session, link.bunq_account_id, link.last_payment_id)
    except BunqError as exc:
        report.error = str(exc)
        return report

    payments.sort(key=lambda p: p.id)
    report.fetched = len(payments)
    parsed_all = [(p, _to_parsed(p)) for p in payments]
    known = existing_import_hashes(db, account, [parsed.import_hash for _, parsed in parsed_all])
    pool = _existing_pool(db, account)

    fresh: list[ParsedTransaction] = []
    for _, parsed in parsed_all:
        if parsed.import_hash in known:
            report.already_imported += 1
            continue
        candidates = pool.get((parsed.date, parsed.amount), [])
        match = next((t for t in candidates if _same_booking(parsed, t)), None)
        if match is not None:
            candidates.remove(match)
            report.matched_existing += 1
            continue
        fresh.append(parsed)
    report.new = len(fresh)
    if dry_run:
        return report

    batch = ImportBatch(user_id=user_id, account_id=account.id, source=BUNQ_SOURCE, total_count=len(payments))
    db.add(batch)
    db.flush()
    rules = db.query(Rule).filter(Rule.user_id == user_id, Rule.is_active == 1).all()
    result = store_parsed_transactions(db, account, fresh, rules, batch.id)
    batch.imported_count = result.imported
    batch.skipped_count = report.fetched - result.imported
    if payments:
        link.last_payment_id = max(p.id for p in payments)
    link.last_synced_at = datetime.datetime.utcnow()
    db.flush()

    new_ids = [t.id for t in db.query(Transaction.id).filter(Transaction.import_batch_id == batch.id)]
    report.transfers_linked = link_transfers(db, user_id, new_ids)
    return report


def sync_connection(db: Session, connection: BunqConnection, client: BunqClient, dry_run: bool) -> list[LinkReport]:
    """Sync all enabled accounts of a connection. Persists the session state; caller commits."""
    session = client.connect(connection.api_key, connection.private_key_pem, connection.installation_token)
    connection.private_key_pem = session.private_key_pem
    connection.installation_token = session.installation_token

    links = (
        db.query(BunqAccountLink)
        .filter(BunqAccountLink.connection_id == connection.id, BunqAccountLink.enabled == 1)
        .order_by(BunqAccountLink.id).all()
    )
    reports = [sync_link(db, client, session, link, connection.user_id, dry_run) for link in links]
    if not dry_run and any(r.new or r.transfers_linked for r in reports):
        _post_import(db, connection.user_id)
    connection.last_checked_at = datetime.datetime.utcnow()
    connection.last_status = "error" if any(r.error for r in reports) else "ok"
    connection.last_error = "; ".join(r.error for r in reports if r.error) or None
    return reports


def _post_import(db: Session, user_id: int) -> None:
    """Same follow-up as the Enable Banking sync: recurring links and projections."""
    from app.recurring_service import (
        auto_link_recurring_after_import, cleanup_matched_projected, sync_projected_transactions,
    )
    today = datetime.date.today()
    db.flush()
    auto_link_recurring_after_import(db, user_id)
    cleanup_matched_projected(user_id, db)
    sync_projected_transactions(user_id, today.year, today.month, db)
