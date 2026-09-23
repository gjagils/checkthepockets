"""Shared persistence for imported transactions (bank sync, scheduler and CSV)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.rules_engine import apply_rules_to_transaction


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    rejected: int = 0
    auto_categorized: int = 0


def _already_imported(db: Session, account: Account, import_hash: str) -> bool:
    return db.query(Transaction.id).filter(
        Transaction.account_id == account.id,
        Transaction.import_hash == import_hash,
    ).first() is not None


def _add_transaction(db: Session, account: Account, import_batch_id: int | None, **fields) -> Transaction:
    transaction = Transaction(account_id=account.id, import_batch_id=import_batch_id, **fields)
    db.add(transaction)
    db.flush()
    return transaction


def store_parsed_transactions(
    db: Session,
    account: Account,
    parsed_transactions,
    active_rules=(),
    import_batch_id: int | None = None,
) -> ImportResult:
    """Store parsed transactions once per account and apply active rules."""
    result = ImportResult()
    for parsed in parsed_transactions:
        if _already_imported(db, account, parsed.import_hash):
            result.skipped += 1
            continue
        transaction = _add_transaction(
            db, account, import_batch_id,
            date=parsed.date,
            amount=parsed.amount,
            currency=parsed.currency,
            description=parsed.description,
            counterparty=parsed.counterparty,
            counterparty_iban=parsed.counterparty_iban,
            balance_after=parsed.balance_after,
            import_hash=parsed.import_hash,
        )
        if active_rules:
            apply_rules_to_transaction(active_rules, transaction, db)
            if transaction.category_id is not None:
                result.auto_categorized += 1
        result.imported += 1
    return result


def store_confirmed_csv_rows(
    db: Session,
    account: Account,
    rows: list[dict],
    categories_by_name: dict,
    active_rules=(),
    import_batch_id: int | None = None,
) -> ImportResult:
    """Store CSV preview rows confirmed by the user.

    Rows already imported on this account are skipped before validation; rows
    with an invalid date or amount are rejected. A category name from the CSV
    (matched case-insensitively) takes precedence over the active rules.
    """
    result = ImportResult()
    for item in rows:
        if _already_imported(db, account, item["import_hash"]):
            result.skipped += 1
            continue

        try:
            tx_date = date.fromisoformat(item["date"])
            tx_amount = Decimal(item["amount"])
        except (ValueError, InvalidOperation):
            result.rejected += 1
            continue

        category_name = (item.get("category_name") or "").strip().lower()
        category = categories_by_name.get(category_name) if category_name else None
        transaction = _add_transaction(
            db, account, import_batch_id,
            date=tx_date,
            amount=tx_amount,
            currency=item.get("currency", "EUR"),
            description=item.get("description"),
            counterparty=item.get("counterparty"),
            counterparty_iban=item.get("counterparty_iban"),
            balance_after=Decimal(item["balance_after"]) if item.get("balance_after") else None,
            import_hash=item["import_hash"],
            category_id=category.id if category else None,
        )

        if category:
            result.auto_categorized += 1
        elif active_rules and apply_rules_to_transaction(active_rules, transaction, db):
            result.auto_categorized += 1

        result.imported += 1
    return result
