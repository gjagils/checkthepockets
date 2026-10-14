"""Enable Banking synchronisation, shared by the manual sync page and the scheduler (ACT-42a).

Before this module the banking router and the scheduler each had their own implementation: the
scheduler matched accounts on a raw IBAN comparison only, created no ImportBatch, wrote no status
fields, and one failing account rolled back everything. Now both call `sync_account` /
`sync_connection`:

* accounts are matched on external_uid first and on the normalised IBAN second (reauthorisation);
* every sync creates an ImportBatch and sets `last_sync_status` / `last_sync_error` on the connection;
* `sync_connection` isolates each account in a savepoint, so one failing account leaves the others intact.

Services here flush; the caller commits. (`post_import` still commits internally via the rules and
recurring services; that is ACT-42c.)
"""
import json
import logging
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app import clock
from app.import_service import store_parsed_transactions
from app.models import Account, BankConnection, ImportBatch, Rule
from app.parsers.base import ParsedTransaction

logger = logging.getLogger(__name__)


def normalize_iban(value: str | None) -> str | None:
    """Canoniek IBAN: spaties weg, uppercase. Voorkomt match-misses door
    verschillen tussen API-responses (NL81 BUNQ 2088 ...) en DB-records
    (NL81BUNQ2088...)."""
    if not value:
        return None
    clean = "".join(value.split()).upper()
    return clean or None


@dataclass
class SyncResult:
    status: str                    # "ok" | "no_transactions" | "fetch_error"
    error: str | None = None
    account: Account | None = None
    batch: ImportBatch | None = None
    total: int = 0
    imported: int = 0
    skipped: int = 0
    auto_categorized: int = 0


def resolve_account(db: Session, conn: BankConnection, account_uid: str, account_iban: str | None) -> Account:
    """Find or create the Account for one bank account of a connection.

    Match order:
      1. external_uid (stable Enable Banking account uid);
      2. (bank, normalised IBAN), even when the Account has another external_uid. That covers
         reauthorisation after 90 days (new uid for the same account) and legacy accounts created
         before the external_uid column.
    external_uid is only moved to the current uid after an Account was found or created, so a sync can
    never silently create a duplicate Account for a bank + IBAN that already has one.
    """
    user_id = conn.user_id
    bank_key = conn.bank_name.lower().replace(" ", "_")
    display = (conn.display_name or conn.bank_name).strip()
    preferred_name = f"{display} - {account_iban}" if account_iban else display
    account = db.query(Account).filter(
        Account.user_id == user_id, Account.external_uid == account_uid,
    ).first()
    matched_by = "external_uid" if account else None

    if not account and account_iban:
        # Matched in Python: stored IBANs may still contain whitespace or other casing.
        candidates = db.query(Account).filter(
            Account.user_id == user_id, Account.bank == bank_key, Account.iban.isnot(None),
        ).all()
        matches = [a for a in candidates if normalize_iban(a.iban) == account_iban]
        if matches:
            legacy = [a for a in matches if a.external_uid is None]
            if legacy:
                account, matched_by = legacy[0], "iban_legacy_fallback"
            else:
                account, matched_by = matches[0], "iban_fallback_reauth"
                logger.warning(
                    "Bank sync: matched Account id=%s on IBAN %s although it had another external_uid=%s; "
                    "the new uid=%s was linked. Possibly a reauthorisation.",
                    account.id, account_iban, account.external_uid, account_uid,
                )

    if account:
        if account.external_uid != account_uid:
            account.external_uid = account_uid
        if account_iban and normalize_iban(account.iban) != account_iban:
            account.iban = account_iban
        # Keep the name in step with the connection's display name unless the user gave it a custom one.
        autogen_prefixes = (f"{conn.bank_name} -", f"{display} -", f"{conn.bank_name}")
        if account.name == f"{conn.bank_name} - account" or any(account.name.startswith(p) for p in autogen_prefixes):
            account.name = preferred_name
        logger.info("Bank sync: using existing Account id=%s name=%s matched_by=%s",
                    account.id, account.name, matched_by)
        return account

    account = Account(user_id=user_id, name=preferred_name, iban=account_iban or None,
                      bank=bank_key, external_uid=account_uid)
    db.add(account)
    db.flush()
    # A sync that creates an Account is suspicious for an existing user (it should exist since connecting).
    logger.warning(
        "Bank sync: created NEW Account id=%s name=%s bank=%s iban=%s uid=%s; check that no other "
        "Account exists for this IBAN.", account.id, account.name, bank_key, account_iban, account_uid,
    )
    return account


def sync_account(
    db: Session,
    conn: BankConnection,
    account_uid: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    client=None,
) -> SyncResult:
    """Fetch and import the transactions of one bank account. Flushes; the caller commits.

    `client` is the enable_banking module (injectable for tests). A fetch failure is reported in the
    result (and on the connection), not raised.
    """
    from app import enable_banking
    client = client or enable_banking

    stored = json.loads(conn.accounts_json or "[]")
    info = next((a for a in stored if a.get("uid") == account_uid), None)
    account_iban = normalize_iban(info["iban"]) if info and info.get("iban") else None

    logger.info("Bank sync gestart: %s koppeling id=%s from=%s to=%s", conn.bank_name, conn.id, date_from, date_to)
    try:
        raw = client.get_transactions(account_uid, date_from=date_from or None, date_to=date_to or None)
        logger.info("Bank sync: %d ruwe transacties opgehaald", len(raw))
    except Exception as exc:
        message = enable_banking.safe_error_message(exc)
        logger.error("Bank sync fout voor %s (koppeling id=%s): %s", conn.bank_name, conn.id, message)
        conn.last_sync_status = "error"
        conn.last_sync_error = message[:500]
        return SyncResult(status="fetch_error", error=message)

    parsed = map_eb_transactions(raw)
    # The API sometimes returns more than requested.
    if date_from:
        parsed = [p for p in parsed if str(p.date) >= date_from]
    if date_to:
        parsed = [p for p in parsed if str(p.date) <= date_to]
    logger.info("Bank sync: %d transacties na datumfilter", len(parsed))
    if not parsed:
        return SyncResult(status="no_transactions")

    account = resolve_account(db, conn, account_uid, account_iban)
    rules = db.query(Rule).filter(Rule.user_id == conn.user_id, Rule.is_active == 1).all()
    batch = ImportBatch(user_id=conn.user_id, account_id=account.id, source="enable_banking", total_count=len(parsed))
    db.add(batch)
    db.flush()
    stored_result = store_parsed_transactions(db, account, parsed, rules, batch.id)
    batch.imported_count = stored_result.imported
    batch.skipped_count = stored_result.skipped
    conn.last_synced_at = clock.now_utc()
    conn.last_sync_status = "success"
    conn.last_sync_error = None
    db.flush()
    return SyncResult(
        status="ok", account=account, batch=batch, total=len(parsed),
        imported=stored_result.imported, skipped=stored_result.skipped,
        auto_categorized=stored_result.auto_categorized,
    )


def sync_connection(db: Session, conn: BankConnection, *, client=None) -> list[SyncResult]:
    """Sync every account of a connection; each account in its own savepoint.

    One account failing (fetch error or an unexpected exception) leaves the other accounts' imports intact.
    The connection ends with status "success", or "error" plus the collected messages when any failed.
    """
    from app.enable_banking import safe_error_message

    results: list[SyncResult] = []
    errors: list[str] = []
    for info in json.loads(conn.accounts_json or "[]"):
        uid = info.get("uid")
        if not uid:
            continue
        try:
            with db.begin_nested():
                result = sync_account(db, conn, uid, client=client)
        except Exception as exc:
            message = safe_error_message(exc)
            logger.exception("Bank sync mislukt voor koppeling id=%s", conn.id)
            result = SyncResult(status="fetch_error", error=message)
        if result.status == "fetch_error":
            errors.append(result.error or "onbekende fout")
        results.append(result)

    conn.last_synced_at = clock.now_utc()
    if errors:
        conn.last_sync_status = "error"
        conn.last_sync_error = "; ".join(errors)[:500]
    else:
        conn.last_sync_status = "success"
        conn.last_sync_error = None
    db.flush()
    return results


def post_import(db: Session, user_id: int) -> int:
    """Follow-up after an import: re-run rules, link recurring items, refresh projections.

    Returns how many existing transactions the rules re-run categorised (kept apart from the
    "auto-categorised on import" count).
    """
    from app.recurring_service import (
        auto_link_recurring_after_import, cleanup_matched_projected, sync_projected_transactions,
    )
    from app.rules_engine import apply_rules_to_all

    extra = apply_rules_to_all(db, user_id)
    if extra:
        logger.info("Bank sync: %d extra existing transactions categorised via apply_rules_to_all", extra)
    auto_link_recurring_after_import(db, user_id)
    cleanup_matched_projected(user_id, db)
    today = clock.today_nl()
    sync_projected_transactions(user_id, today.year, today.month, db)
    return extra


# ── Transaction mapping ─────────────────────────────────────────────────────

def map_eb_transactions(raw: list[dict]) -> list[ParsedTransaction]:
    """Map Enable Banking API transaction objects to ParsedTransaction."""
    result = []
    for tx in raw:
        try:
            # Date: booking_date or value_date
            date_str = tx.get("booking_date") or tx.get("value_date") or tx.get("transaction_date")
            if not date_str:
                continue
            tx_date = date_type.fromisoformat(date_str[:10])

            # Amount
            amount_obj = tx.get("transaction_amount") or {}
            amount_str = amount_obj.get("amount", "0")
            currency = amount_obj.get("currency", "EUR")
            amount = Decimal(amount_str)

            # Credit/debit indicator
            if tx.get("credit_debit_indicator") == "DBIT" and amount > 0:
                amount = -amount

            # Description
            desc_parts = []
            if tx.get("remittance_information"):
                info = tx["remittance_information"]
                if isinstance(info, list):
                    desc_parts.extend(info)
                elif isinstance(info, dict):
                    desc_parts.extend(info.get("unstructured", []))
                else:
                    desc_parts.append(str(info))
            if tx.get("additional_information"):
                desc_parts.append(tx["additional_information"])
            description = " ".join(desc_parts).strip() or "Geen omschrijving"

            # Counterparty
            counterparty = None
            counterparty_iban = None
            creditor = tx.get("creditor") or {}
            debtor = tx.get("debtor") or {}
            party = creditor or debtor
            if party:
                counterparty = party.get("name")
            creditor_acc = tx.get("creditor_account") or {}
            debtor_acc = tx.get("debtor_account") or {}
            party_acc = creditor_acc or debtor_acc
            if party_acc:
                counterparty_iban = party_acc.get("iban")

            # Balance after (if available)
            balance_after = None
            if tx.get("balance_after_transaction"):
                bal = tx["balance_after_transaction"]
                bal_amount = bal.get("balance_amount", {})
                if bal_amount.get("amount"):
                    try:
                        balance_after = Decimal(bal_amount["amount"])
                    except (InvalidOperation, ValueError):
                        pass

            result.append(ParsedTransaction(
                date=tx_date,
                amount=amount,
                currency=currency,
                description=description,
                counterparty=counterparty,
                counterparty_iban=counterparty_iban,
                balance_after=balance_after,
            ))
        except (ValueError, InvalidOperation, KeyError):
            continue

    return result
