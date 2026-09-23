"""Shared persistence for parsed bank transactions."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.rules_engine import apply_rules_to_transaction


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    auto_categorized: int = 0


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
        exists = db.query(Transaction.id).filter(
            Transaction.account_id == account.id,
            Transaction.import_hash == parsed.import_hash,
        ).first()
        if exists:
            result.skipped += 1
            continue
        transaction = Transaction(
            account_id=account.id,
            date=parsed.date,
            amount=parsed.amount,
            currency=parsed.currency,
            description=parsed.description,
            counterparty=parsed.counterparty,
            counterparty_iban=parsed.counterparty_iban,
            balance_after=parsed.balance_after,
            import_hash=parsed.import_hash,
            import_batch_id=import_batch_id,
        )
        db.add(transaction)
        db.flush()
        if active_rules:
            apply_rules_to_transaction(active_rules, transaction, db)
            if transaction.category_id is not None:
                result.auto_categorized += 1
        result.imported += 1
    return result
