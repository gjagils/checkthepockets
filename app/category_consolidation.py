"""Categorieën van alle rekeningen samenvoegen tot één gedeelde set (ACT-55c).

Categorieën met dezelfde naam (hoofd- of subcategorie onder dezelfde hoofdcategorie) worden één
gedeelde categorie zonder rekening. Bij bijna-gelijke namen kiest de gebruiker in de preview zelf.
Categorieën zonder enig gebruik worden gearchiveerd. Eerst ``plan_consolidation`` (puur lezen),
daarna ``apply_consolidation``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.account_merge import fold_category
from app.models import (
    Budget, BudgetPresetLine, Category, RecurringTransaction, Rule, SavingsLine, Transaction,
)


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


@dataclass
class Step:
    category: Category
    action: str                      # "merge" | "share"
    target: Category | None = None   # bij "merge": waar de categorie in opgaat
    new_parent: Category | None = None
    transactions: int = 0
    manual: bool = False


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    blocked: list[tuple[Category, str]] = field(default_factory=list)
    archive: list[Category] = field(default_factory=list)
    suggestions: dict[int, list[Category]] = field(default_factory=dict)   # categorie-id -> mogelijke doelen
    shared_after: int = 0

    @property
    def merges(self) -> int:
        return sum(1 for s in self.steps if s.action == "merge")


def _usage(db: Session, user_id: int) -> dict[int, int]:
    rows = (
        db.query(Transaction.category_id, func.count(Transaction.id))
        .filter(Transaction.category_id.isnot(None)).group_by(Transaction.category_id).all()
    )
    return {cid: n for cid, n in rows}


def _referenced_ids(db: Session, user_id: int) -> set[int]:
    ids: set[int] = set()
    for model, col in ((Budget, Budget.category_id), (BudgetPresetLine, BudgetPresetLine.category_id),
                       (RecurringTransaction, RecurringTransaction.category_id),
                       (Rule, Rule.assign_category_id), (SavingsLine, SavingsLine.category_id)):
        ids.update(r[0] for r in db.query(col).filter(col.isnot(None)).distinct())
    return ids


def plan_consolidation(db: Session, user_id: int, manual: dict[int, int] | None = None) -> Plan:
    """Bereken wat er gebeurt. ``manual`` = {categorie-id: doel-id} uit de preview-keuzes."""
    manual = manual or {}
    cats = db.query(Category).filter(Category.user_id == user_id, Category.is_archived == 0).all()
    by_id = {c.id: c for c in cats}
    usage = _usage(db, user_id)
    plan = Plan()

    shared_names = {c.name for c in cats if c.account_id is None}
    # target_of[id] = categorie waarin deze (na de stappen) is opgegaan of die zichzelf blijft.
    target_of: dict[int, Category] = {c.id: c for c in cats if c.account_id is None}

    def key(c: Category) -> tuple:
        parent = target_of.get(c.parent_id) if c.parent_id else None
        return (parent.id if parent else None, _norm(c.name), bool(c.is_income))

    def handle(level: list[Category]) -> None:
        shared_by_key: dict[tuple, Category] = {}
        for c in level:
            if c.account_id is None:
                shared_by_key.setdefault(key(c), c)
        for c in sorted((c for c in level if c.account_id is not None), key=lambda c: c.id):
            if c.id in manual and manual[c.id] in by_id and manual[c.id] != c.id:
                tgt = target_of.get(manual[c.id], by_id[manual[c.id]])
                plan.steps.append(Step(c, "merge", tgt, transactions=usage.get(c.id, 0), manual=True))
                target_of[c.id] = tgt
                continue
            k = key(c)
            if k in shared_by_key:
                tgt = shared_by_key[k]
                plan.steps.append(Step(c, "merge", tgt, transactions=usage.get(c.id, 0)))
                target_of[c.id] = tgt
            elif c.name in shared_names:
                plan.blocked.append((c, f"De naam '{c.name}' wordt al gebruikt door een andere gedeelde categorie."))
            else:
                parent = target_of.get(c.parent_id) if c.parent_id else None
                plan.steps.append(Step(c, "share", new_parent=parent, transactions=usage.get(c.id, 0)))
                shared_by_key[k] = c
                shared_names.add(c.name)
                target_of[c.id] = c

    top = [c for c in cats if c.parent_id is None]
    children = [c for c in cats if c.parent_id is not None]
    handle(top)
    handle(children)

    # Suggesties voor bijna-gelijke namen (alleen voor wat gedeeld blijft of geblokkeerd is).
    remaining = [s.category for s in plan.steps if s.action == "share"] + [c for c, _ in plan.blocked]
    shared_now = [s.category for s in plan.steps if s.action == "share"] + [c for c in cats if c.account_id is None]
    for c in remaining:
        close = [o for o in shared_now if o.id != c.id and bool(o.is_income) == bool(c.is_income)
                 and (o.parent_id is None) == (c.parent_id is None)
                 and (SequenceMatcher(None, _norm(c.name), _norm(o.name)).ratio() >= 0.8
                      or _norm(c.name) in _norm(o.name) or _norm(o.name) in _norm(c.name))]
        if close:
            plan.suggestions[c.id] = close

    gone = {s.category.id for s in plan.steps if s.action == "merge"}
    referenced = _referenced_ids(db, user_id)
    children_of: dict[int, list[Category]] = {}
    for c in cats:
        if c.parent_id:
            children_of.setdefault(c.parent_id, []).append(c)
    for c in cats:
        if c.id in gone or c.id in referenced or usage.get(c.id):
            continue
        kids = [k for k in children_of.get(c.id, []) if k.id not in gone]
        if kids and any(usage.get(k.id) or k.id in referenced for k in kids):
            continue
        plan.archive.append(c)
    plan.shared_after = len({s.category.id for s in plan.steps if s.action == "share"} |
                            {c.id for c in cats if c.account_id is None})
    return plan


def apply_consolidation(db: Session, user_id: int, manual: dict[int, int] | None = None) -> Plan:
    """Voer het plan uit (zonder commit). Opnieuw plannen op actuele data, dus alleen wat de preview toonde."""
    plan = plan_consolidation(db, user_id, manual)
    for step in plan.steps:
        if step.action == "share":
            step.category.account_id = None
            if step.new_parent is not None:
                step.category.parent_id = step.new_parent.id
    db.flush()
    for step in plan.steps:
        if step.action == "merge" and step.target is not None:
            fold_category(db, step.category.id, step.target.id, sum_budgets=True)
    db.flush()
    for category in plan.archive:
        if db.get(Category, category.id) is not None:
            category.is_archived = 1
    return plan
