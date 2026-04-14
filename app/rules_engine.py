"""Rules engine: matching and applying rules to transactions."""

import logging
from sqlalchemy.orm import Session

from app.models import Rule, Transaction, Tag, Category

logger = logging.getLogger(__name__)


def _get_field_value(transaction: Transaction, field: str) -> str:
    """Get the value of a transaction field for matching."""
    if field == "counterparty":
        return transaction.counterparty or ""
    elif field == "description":
        return transaction.description or ""
    elif field == "counterparty_iban":
        return transaction.counterparty_iban or ""
    return ""


def _matches(value: str, match_type: str, match_value: str) -> bool:
    """Check if a value matches a rule condition (case-insensitive)."""
    value_lower = value.lower()
    match_lower = match_value.lower()

    if match_type == "contains":
        return match_lower in value_lower
    elif match_type == "exact":
        return value_lower == match_lower
    elif match_type == "starts_with":
        return value_lower.startswith(match_lower)
    return False


def rule_matches_transaction(rule: Rule, transaction: Transaction) -> bool:
    """Check if a rule matches a transaction."""
    field_value = _get_field_value(transaction, rule.match_field)
    if not _matches(field_value, rule.match_type, rule.match_value):
        return False

    # Check optional amount range
    if rule.amount_min is not None and transaction.amount < rule.amount_min:
        return False
    if rule.amount_max is not None and transaction.amount > rule.amount_max:
        return False

    # Check optional account condition
    if rule.condition_account_id is not None and transaction.account_id != rule.condition_account_id:
        return False

    return True


def apply_rule_to_transaction(rule: Rule, transaction: Transaction, db: Session) -> bool:
    """Apply a rule's actions to a transaction. Returns True if something changed."""
    changed = False

    if rule.assign_category_id and transaction.category_id != rule.assign_category_id:
        transaction.category_id = rule.assign_category_id
        transaction.is_reviewed = 1
        changed = True

    if rule.assign_tag_id:
        tag = db.query(Tag).filter(Tag.id == rule.assign_tag_id).first()
        if tag and tag not in transaction.tags:
            transaction.tags.append(tag)
            changed = True

    if rule.action_rename_counterparty:
        new_name = rule.action_rename_counterparty.strip()
        if new_name and transaction.counterparty != new_name:
            transaction.counterparty = new_name
            changed = True

    if rule.action_set_reviewed and not transaction.is_reviewed and not rule.assign_category_id:
        transaction.is_reviewed = 1
        changed = True

    return changed


def apply_rules_to_transaction(rules: list[Rule], transaction: Transaction, db: Session) -> bool:
    """Apply all matching rules to a single transaction."""
    changed = False
    for rule in rules:
        if rule.is_active and rule_matches_transaction(rule, transaction):
            if apply_rule_to_transaction(rule, transaction, db):
                changed = True
    return changed


def apply_rules_to_all(db: Session, user_id: int, only_uncategorized: bool = False) -> int:
    """Apply all active rules to existing transactions. Returns count of affected transactions."""
    from app.models import Account

    rules = (
        db.query(Rule)
        .filter(Rule.user_id == user_id, Rule.is_active == 1)
        .all()
    )
    if not rules:
        return 0

    query = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id)
    )
    if only_uncategorized:
        query = query.filter(Transaction.category_id.is_(None))

    transactions = query.all()
    affected = 0

    # Debug: log uncategorized transactions and rule matching
    uncategorized = [tx for tx in transactions if tx.category_id is None]
    if uncategorized:
        logger.info("apply_rules_to_all: %d/%d transacties zonder categorie", len(uncategorized), len(transactions))
        for tx in uncategorized[:5]:
            desc_val = tx.description or ""
            cp_val = tx.counterparty or ""
            logger.info("  TX id=%s date=%s desc=[%s] cp=[%s] desc_type=%s cp_type=%s",
                        tx.id, tx.date, desc_val[:80], cp_val[:50], type(tx.description).__name__, type(tx.counterparty).__name__)
            for rule in rules:
                field_val = _get_field_value(tx, rule.match_field)
                matches = _matches(field_val, rule.match_type, rule.match_value)
                if rule.match_value.lower() in (desc_val + cp_val).lower():
                    logger.info("    REGEL '%s': field=%s val=[%s] match_val='%s' → match=%s",
                                rule.match_value, rule.match_field, field_val[:60], rule.match_value, matches)

    for tx in transactions:
        if apply_rules_to_transaction(rules, tx, db):
            affected += 1

    db.commit()
    return affected


def preview_single_rule(db: Session, user_id: int, rule_id: int) -> list[dict]:
    """Return transactions that match a rule, without applying it."""
    from app.models import Account

    rule = (
        db.query(Rule)
        .filter(Rule.id == rule_id, Rule.user_id == user_id)
        .first()
    )
    if not rule:
        return []

    transactions = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id)
        .order_by(Transaction.date.desc())
        .all()
    )

    matching = []
    for tx in transactions:
        if rule_matches_transaction(rule, tx):
            matching.append({
                "id": tx.id,
                "date": str(tx.date),
                "counterparty": tx.counterparty or "",
                "description": tx.description or "",
                "amount": float(tx.amount),
                "category": tx.category.name if tx.category else None,
            })

    return matching


def apply_single_rule(
    db: Session,
    user_id: int,
    rule_id: int,
    only_uncategorized: bool = False,
    transaction_ids: list[int] | None = None,
) -> int:
    """Apply a single rule to existing transactions. Returns count of affected transactions.

    If transaction_ids is provided, only those transactions are targeted.
    Otherwise all matching transactions are targeted (optionally filtered by only_uncategorized).
    """
    from app.models import Account

    rule = (
        db.query(Rule)
        .filter(Rule.id == rule_id, Rule.user_id == user_id)
        .first()
    )
    if not rule:
        return 0

    query = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id)
    )

    if transaction_ids is not None:
        query = query.filter(Transaction.id.in_(transaction_ids))
    elif only_uncategorized:
        query = query.filter(Transaction.category_id.is_(None))

    transactions = query.all()
    affected = 0

    for tx in transactions:
        if rule_matches_transaction(rule, tx):
            if apply_rule_to_transaction(rule, tx, db):
                affected += 1

    db.commit()
    return affected


def suggest_rules(db: Session, user_id: int) -> list[dict]:
    """Suggest rules based on categorized transactions with recurring counterparties."""
    from app.models import Account
    from sqlalchemy import func

    # Find counterparties that are consistently categorized the same way
    results = (
        db.query(
            Transaction.counterparty,
            Transaction.category_id,
            func.count(Transaction.id).label("count"),
        )
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.counterparty.isnot(None),
            Transaction.counterparty != "",
            Transaction.category_id.isnot(None),
        )
        .group_by(Transaction.counterparty, Transaction.category_id)
        .having(func.count(Transaction.id) >= 2)
        .order_by(func.count(Transaction.id).desc())
        .limit(20)
        .all()
    )

    # Filter out counterparties that already have a rule
    existing_rules = (
        db.query(Rule.match_value)
        .filter(
            Rule.user_id == user_id,
            Rule.match_field == "counterparty",
            Rule.match_type == "contains",
        )
        .all()
    )
    existing_values = {r.match_value.lower() for r in existing_rules}

    suggestions = []
    seen_counterparties = set()

    for counterparty, category_id, count in results:
        cp_lower = counterparty.lower()
        if cp_lower in seen_counterparties:
            continue
        if cp_lower in existing_values:
            continue

        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            continue

        seen_counterparties.add(cp_lower)
        suggestions.append({
            "counterparty": counterparty,
            "category_id": category_id,
            "category_name": category.name,
            "category_color": category.color,
            "count": count,
        })

    return suggestions[:10]
