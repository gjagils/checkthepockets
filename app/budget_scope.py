"""Budgetten per rekeninggroep (ACT-55b): één plek voor zoeken en schrijven."""
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Account, Budget, Category


def category_group_id(db: Session, category: Category) -> int | None:
    """Groep van de rekening waar de categorie bij hoort; ``None`` voor categorieën zonder rekening."""
    if category.account_id is None:
        return None
    return db.query(Account.group_id).filter(Account.id == category.account_id).scalar()


def group_account_ids(db: Session, user_id: int, group_id: int) -> list[int]:
    rows = db.query(Account.id).filter(Account.user_id == user_id, Account.group_id == group_id).all()
    return [r[0] for r in rows]


def find_budget(db: Session, user_id: int, category_id: int, group_id: int | None,
                year: int, month: int) -> Budget | None:
    query = db.query(Budget).filter(
        Budget.user_id == user_id, Budget.category_id == category_id,
        Budget.year == year, Budget.month == month,
    )
    query = query.filter(Budget.group_id.is_(None) if group_id is None else Budget.group_id == group_id)
    return query.first()


def put_budget(db: Session, user_id: int, category_id: int, group_id: int | None,
               year: int, month: int, amount: Decimal) -> Budget:
    """Maak of werk het budget van (categorie, groep, maand) bij."""
    budget = find_budget(db, user_id, category_id, group_id, year, month)
    if budget:
        budget.amount = amount
    else:
        budget = Budget(user_id=user_id, category_id=category_id, group_id=group_id,
                        year=year, month=month, amount=amount)
        db.add(budget)
    return budget


def budgets_in_scope(db: Session, user_id: int, year: int, month: int, group_id: int | None):
    """Budgetten van een maand: van de gekozen groep (plus niet-gebonden), of alle."""
    query = db.query(Budget).filter(Budget.user_id == user_id, Budget.year == year, Budget.month == month)
    if group_id:
        query = query.filter(or_(Budget.group_id == group_id, Budget.group_id.is_(None)))
    return query.all()


def budget_amounts(budgets: list[Budget], group_id: int | None) -> dict[int, Decimal]:
    """Bedrag per categorie. Bij één groep wint het groepsbudget van een niet-gebonden budget;
    zonder groepskeuze worden de budgetten van alle groepen opgeteld."""
    amounts: dict[int, Decimal] = {}
    if group_id:
        for b in sorted(budgets, key=lambda b: b.group_id is not None):  # NULL eerst, groep overschrijft
            amounts[b.category_id] = b.amount
    else:
        for b in budgets:
            amounts[b.category_id] = amounts.get(b.category_id, Decimal("0")) + b.amount
    return amounts
