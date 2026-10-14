"""ACT-41: schema-regels die altijd getest worden (SQLite, met foreign keys aan)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Account, Category, Transaction, User


def _user(db, name="schema-user"):
    user = User(username=name, password_hash="x")
    db.add(user)
    db.flush()
    return user


def test_global_category_names_are_unique_per_user(db):
    user = _user(db)
    db.add(Category(user_id=user.id, name="Boodschappen"))
    db.commit()
    db.add(Category(user_id=user.id, name="Boodschappen"))        # tweede globale met dezelfde naam
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_same_name_is_fine_on_different_accounts_and_for_other_users(db):
    user, other = _user(db), _user(db, "andere")
    a = Account(user_id=user.id, name="A", bank="x")
    b = Account(user_id=user.id, name="B", bank="x")
    db.add_all([a, b])
    db.flush()
    db.add_all([
        Category(user_id=user.id, account_id=a.id, name="Boodschappen"),
        Category(user_id=user.id, account_id=b.id, name="Boodschappen"),
        Category(user_id=user.id, name="Boodschappen"),
        Category(user_id=other.id, name="Boodschappen"),
    ])
    db.commit()                                                    # geen fout


def test_deleting_a_split_parent_deletes_its_parts(db):
    user = _user(db)
    account = Account(user_id=user.id, name="A", bank="x")
    db.add(account)
    db.flush()
    parent = Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal("-100"), import_hash="p")
    db.add(parent)
    db.flush()
    db.add_all([
        Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal("-60"), import_hash="c1", parent_id=parent.id),
        Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal("-40"), import_hash="c2", parent_id=parent.id),
    ])
    db.commit()
    db.expire_all()
    db.delete(db.get(Transaction, parent.id))
    db.commit()
    assert db.query(Transaction).count() == 0                      # geen wezen met parent_id NULL


def test_model_declares_the_indexes_queries_rely_on():
    indexed = lambda table, column: any(  # noqa: E731
        [c.name for c in ix.columns] == [column] for ix in Transaction.__table__.metadata.tables[table].indexes
    )
    for table, column in (("transactions", "recurring_id"), ("transactions", "transfer_id"),
                          ("transactions", "date"), ("transactions", "account_id"),
                          ("accounts", "user_id"), ("categories", "user_id"), ("persons", "user_id")):
        assert indexed(table, column), (table, column)
