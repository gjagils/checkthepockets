"""Regression tests for projections and linking in the recurring service (ACT-22)."""
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"

from app.database import Base, SessionLocal, engine
from app.models import Account, Category, RecurringTransaction, Transaction, User
from app.recurring_schedule import add_skipped_month, projected_hash
from app.recurring_service import (
    auto_link_recurring_after_import, cleanup_matched_projected, sync_projected_transactions,
)


@pytest.fixture
def setup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    user = User(username="recurring-user", password_hash="x")
    other = User(username="recurring-other", password_hash="x")
    db.add_all([user, other])
    db.flush()
    account = Account(user_id=user.id, name="Betaal", bank="custom")
    other_account = Account(user_id=other.id, name="Ander", bank="custom")
    category = Category(user_id=user.id, name="Wonen")
    db.add_all([account, other_account, category])
    db.flush()
    rent = RecurringTransaction(
        user_id=user.id, name="Huur", amount_expected=Decimal("-900.00"), frequency="monthly",
        counterparty="Verhuurder", category_id=category.id, is_active=1,
    )
    db.add(rent)
    # First real data in August 2026, so September may get a projection.
    db.add(Transaction(account_id=account.id, date=date(2026, 8, 3), amount=Decimal("-12.00"),
                       description="Koffie", counterparty="Cafe", import_hash="aug-coffee"))
    db.commit()
    try:
        yield db, user, other, account, other_account, category, rent
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _projections(db, rent):
    return db.query(Transaction).filter(Transaction.recurring_id == rent.id, Transaction.is_projected == 1).all()


def test_sync_creates_one_projection_and_removes_it_after_real_payment(setup):
    db, user, other, account, other_account, category, rent = setup

    sync_projected_transactions(user.id, 2026, 9, db)
    sync_projected_transactions(user.id, 2026, 9, db)

    [projection] = _projections(db, rent)
    assert projection.import_hash == projected_hash(rent.id, 2026, 9)
    assert (projection.date, projection.amount, projection.account_id) == (date(2026, 9, 1), Decimal("-900.00"), account.id)
    assert projection.category_id == category.id

    db.add(Transaction(account_id=account.id, date=date(2026, 9, 1), amount=Decimal("-900.00"),
                       description="Huur september", counterparty="Verhuurder BV", import_hash="sep-rent"))
    db.commit()
    cleanup_matched_projected(user.id, db)
    assert _projections(db, rent) == []


def test_sync_skips_months_before_data_and_skipped_months(setup):
    db, user, other, account, other_account, category, rent = setup

    sync_projected_transactions(user.id, 2026, 7, db)  # before first real transaction
    add_skipped_month(rent, 2026, 10)
    db.commit()
    sync_projected_transactions(user.id, 2026, 10, db)

    assert _projections(db, rent) == []


def test_other_users_payment_does_not_satisfy_projection(setup):
    db, user, other, account, other_account, category, rent = setup
    db.add(Transaction(account_id=other_account.id, date=date(2026, 9, 1), amount=Decimal("-900.00"),
                       description="Huur", counterparty="Verhuurder", import_hash="other-rent"))
    db.commit()

    sync_projected_transactions(user.id, 2026, 9, db)

    assert len(_projections(db, rent)) == 1


def test_auto_link_links_once_per_period_and_applies_category(setup):
    db, user, other, account, other_account, category, rent = setup
    first = Transaction(account_id=account.id, date=date(2026, 9, 1), amount=Decimal("-900.00"),
                        description="Huur", counterparty="Verhuurder BV", import_hash="sep-1")
    second = Transaction(account_id=account.id, date=date(2026, 9, 20), amount=Decimal("-900.00"),
                         description="Huur", counterparty="Verhuurder BV", import_hash="sep-2")
    foreign = Transaction(account_id=other_account.id, date=date(2026, 9, 1), amount=Decimal("-900.00"),
                          description="Huur", counterparty="Verhuurder BV", import_hash="sep-foreign")
    db.add_all([first, second, foreign])
    db.commit()

    auto_link_recurring_after_import(db, user.id)
    db.commit()

    assert first.recurring_id == rent.id
    assert first.category_id == category.id
    assert second.recurring_id is None  # one link per period
    assert foreign.recurring_id is None  # other user's transactions are never linked
