"""Merge one account into another (e.g. a CSV account and a bank-sync account of the same IBAN).

The import_hash of a CSV row and a bank-sync row for the same booking often
differ, so duplicates are recognised on date + amount + counterparty or
description instead. Matching is one-to-one: two identical payments on one day
only pair up with two identical payments on the other account.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import (
    Account, Budget, BudgetPresetLine, Category, ImportBatch, MortgageScenarioBudget,
    RecurringSuggestion, RecurringTransaction, Rule, RuleSuggestion, SavingsLine, SavingsPlan,
    Transaction,
)


@dataclass
class MergePair:
    source: Transaction
    target: Transaction


@dataclass
class MergePlan:
    move: list[Transaction] = field(default_factory=list)
    duplicates: list[MergePair] = field(default_factory=list)
    # Categories of the source account whose name already exists on the target account.
    category_merges: list[tuple[Category, Category]] = field(default_factory=list)


@dataclass
class MergeResult:
    moved: int = 0
    merged_duplicates: int = 0
    merged_categories: int = 0


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _same_booking(source: Transaction, target: Transaction) -> bool:
    if source.import_hash == target.import_hash:
        return True
    counterparty = _norm(source.counterparty)
    if counterparty and counterparty == _norm(target.counterparty):
        return True
    description = _norm(source.description)
    return bool(description) and description == _norm(target.description)


def plan_merge(db: Session, source: Account, target: Account) -> MergePlan:
    """Decide per source transaction whether it moves or duplicates a target one."""
    plan = MergePlan()
    target_txs = db.query(Transaction).filter(Transaction.account_id == target.id).order_by(Transaction.id).all()
    by_hash = {t.import_hash: t for t in target_txs}  # unique per account
    candidates: dict[tuple, list[Transaction]] = {}
    for tx in target_txs:
        candidates.setdefault((tx.date, tx.amount), []).append(tx)

    source_txs = (
        db.query(Transaction).filter(Transaction.account_id == source.id)
        .order_by(Transaction.date, Transaction.id).all()
    )
    matches: dict[int, Transaction] = {}
    claimed: set[int] = set()

    # Pass 1: an identical import_hash is always the same booking, whatever the visible
    # date is now (linking to a recurring item can shift it). It must claim its target
    # first: otherwise a fuzzy match could take it and the exact twin would be moved,
    # violating the unique (account, import_hash) index.
    for tx in source_txs:
        match = by_hash.get(tx.import_hash)
        if match is not None:
            matches[tx.id] = match
            claimed.add(match.id)

    # Pass 2: same booking by counterparty or description among what is left.
    for tx in source_txs:
        if tx.id in matches:
            continue
        pool = candidates.get((tx.date, tx.amount), [])
        match = next((t for t in pool if t.id not in claimed and _same_booking(tx, t)), None)
        if match is not None:
            claimed.add(match.id)
            matches[tx.id] = match

    for tx in source_txs:
        if tx.id in matches:
            plan.duplicates.append(MergePair(source=tx, target=matches[tx.id]))
        else:
            plan.move.append(tx)

    # uq_user_account_category: a category name is unique per account, so a source category
    # with the name of a target category cannot just move along; it is folded into it.
    target_categories = {c.name: c for c in db.query(Category).filter(Category.account_id == target.id)}
    for category in db.query(Category).filter(Category.account_id == source.id).order_by(Category.id):
        if category.name in target_categories:
            plan.category_merges.append((category, target_categories[category.name]))
    return plan


def _fold_category(db: Session, source_id: int, target_id: int) -> None:
    """Point everything that uses category `source_id` at `target_id`, then delete the source."""
    # Rows with a unique key that includes the category: keep the target's row on a clash.
    for model, key_columns in (
        (Budget, ("user_id", "year", "month")),
        (MortgageScenarioBudget, ("scenario_id",)),
    ):
        kept = {tuple(getattr(r, c) for c in key_columns)
                for r in db.query(model).filter(model.category_id == target_id)}
        for row in db.query(model).filter(model.category_id == source_id).all():
            if tuple(getattr(row, c) for c in key_columns) in kept:
                db.delete(row)
    db.flush()
    for model, column in (
        (Budget, "category_id"), (MortgageScenarioBudget, "category_id"),
        (BudgetPresetLine, "category_id"), (Transaction, "category_id"),
        (SavingsLine, "category_id"), (RecurringTransaction, "category_id"),
        (RuleSuggestion, "category_id"), (RecurringSuggestion, "category_id"),
        (Rule, "assign_category_id"), (Category, "parent_id"),
    ):
        db.query(model).filter(getattr(model, column) == source_id).update(
            {column: target_id}, synchronize_session=False)
    db.query(Category).filter(Category.id == source_id).delete(synchronize_session=False)


def _absorb(source: Transaction, target: Transaction, db: Session) -> None:
    """Keep the user's work from the source copy on the target copy, then drop the source."""
    if target.category_id is None and source.category_id is not None:
        target.category_id = source.category_id
        target.assigned_by_rule_id = source.assigned_by_rule_id
    if not target.is_reviewed and source.is_reviewed:
        target.is_reviewed = source.is_reviewed
    if not target.is_excluded and source.is_excluded:
        target.is_excluded = source.is_excluded
    if target.recurring_id is None and source.recurring_id is not None:
        target.recurring_id = source.recurring_id
    if target.transfer_id is None and source.transfer_id is not None:
        target.transfer_id = source.transfer_id
    if target.original_date is None and source.original_date is not None:
        target.original_date = source.original_date

    db.query(Transaction).filter(Transaction.parent_id == source.id).update(
        {"parent_id": target.id}, synchronize_session=False)
    db.query(Transaction).filter(Transaction.transfer_id == source.id).update(
        {"transfer_id": target.id}, synchronize_session=False)
    # The source's own links must not point at itself or at the target.
    if target.transfer_id in (source.id, target.id):
        target.transfer_id = None
    source.transfer_id = None
    db.flush()
    db.delete(source)
    db.flush()


def merge_accounts(db: Session, source: Account, target: Account) -> MergeResult:
    """Move source's data into target and delete source. Caller commits."""
    if source.id == target.id or source.user_id != target.user_id:
        raise ValueError("Rekeningen moeten verschillend zijn en van dezelfde gebruiker.")

    plan = plan_merge(db, source, target)
    result = MergeResult()

    for pair in plan.duplicates:
        _absorb(pair.source, pair.target, db)
        result.merged_duplicates += 1

    moved_ids = [tx.id for tx in plan.move]
    for start in range(0, len(moved_ids), 500):
        db.query(Transaction).filter(Transaction.id.in_(moved_ids[start:start + 500])).update(
            {"account_id": target.id}, synchronize_session=False)
    result.moved = len(moved_ids)

    db.query(ImportBatch).filter(ImportBatch.account_id == source.id).update(
        {"account_id": target.id}, synchronize_session=False)
    db.query(RecurringTransaction).filter(RecurringTransaction.account_id == source.id).update(
        {"account_id": target.id}, synchronize_session=False)
    for source_category, target_category in plan.category_merges:
        _fold_category(db, source_category.id, target_category.id)
        result.merged_categories += 1
    db.query(Category).filter(Category.account_id == source.id).update(
        {"account_id": target.id}, synchronize_session=False)
    db.flush()
    db.expire_all()  # bulk updates above bypassed the session; reload before deleting the source
    db.query(Rule).filter(Rule.condition_account_id == source.id).update(
        {"condition_account_id": target.id}, synchronize_session=False)

    # A savings plan is unique per account and year in practice; keep the target's
    # plan when both have one for the same year.
    target_years = {y for (y,) in db.query(SavingsPlan.year).filter(SavingsPlan.account_id == target.id)}
    for plan_row in db.query(SavingsPlan).filter(SavingsPlan.account_id == source.id).all():
        if plan_row.year in target_years:
            continue
        plan_row.account_id = target.id

    if not target.owners and source.owners:
        target.owners = list(source.owners)
    source_iban, source_uid = source.iban, source.external_uid
    db.flush()
    db.expire(source)

    # Remaining savings plans (same year on both) go with the source account.
    db.query(SavingsPlan).filter(SavingsPlan.account_id == source.id).delete(synchronize_session=False)
    db.expire(source, ["transactions"])
    db.delete(source)
    db.flush()

    if not target.iban and source_iban:
        target.iban = source_iban
    if not target.external_uid and source_uid:
        target.external_uid = source_uid
    db.flush()
    return result
