"""Tests voor app.budget_stats.category_spending_average."""
import datetime
import os
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from app.auth import hash_password
from app.budget_stats import _previous_months, category_spending_average
from app.database import Base, SessionLocal, engine
from app.models import Account, Category, Transaction, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        # Leeg alles tussen tests (FK-ordering).
        s.query(Transaction).delete()
        s.query(Category).delete()
        s.query(Account).delete()
        s.query(User).delete()
        s.commit()
        yield s
    finally:
        s.close()


def test_previous_months_basic():
    assert _previous_months(2026, 4, 3) == [(2026, 1), (2026, 2), (2026, 3)]


def test_previous_months_crosses_year_boundary():
    assert _previous_months(2026, 2, 3) == [(2025, 11), (2025, 12), (2026, 1)]


def test_previous_months_zero_count_returns_empty():
    assert _previous_months(2026, 4, 0) == []


def _make_user(db) -> User:
    u = User(username="avg", email="avg@x.nl",
             password_hash=hash_password("pw"), is_admin=1)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_account(db, user) -> Account:
    a = Account(user_id=user.id, name="Betaal", bank="test")
    db.add(a); db.commit(); db.refresh(a)
    return a


def _make_cat(db, user, name="Boodschappen") -> Category:
    c = Category(user_id=user.id, name=name)
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_average_computed_over_three_previous_months(db):
    user = _make_user(db)
    acc = _make_account(db, user)
    cat = _make_cat(db, user)
    # Ref = 2026-04 → 3 prev maanden = januari/februari/maart 2026.
    for month, amount in [(1, -300), (2, -600), (3, -900)]:
        db.add(Transaction(
            account_id=acc.id, category_id=cat.id,
            date=datetime.date(2026, month, 15),
            amount=Decimal(str(amount)),
            counterparty="Supermarkt",
            import_hash=f"h-{month}-{amount}",
            is_excluded=0,
        ))
    db.commit()

    result = category_spending_average(
        db, user_id=user.id, ref_year=2026, ref_month=4, months=3,
    )
    # (300 + 600 + 900) / 3 = 600
    assert result[cat.id] == Decimal("600.00")


def test_average_excludes_reference_month(db):
    user = _make_user(db)
    acc = _make_account(db, user)
    cat = _make_cat(db, user)
    # Maart (3 prev) + huidige april → april mag niet meetellen.
    db.add_all([
        Transaction(account_id=acc.id, category_id=cat.id,
                    date=datetime.date(2026, 3, 10),
                    amount=Decimal("-300"), counterparty="x",
                    import_hash="h-mrt-300",
                    is_excluded=0),
        Transaction(account_id=acc.id, category_id=cat.id,
                    date=datetime.date(2026, 4, 10),
                    amount=Decimal("-9999"), counterparty="x",
                    import_hash="h-apr-9999",
                    is_excluded=0),
    ])
    db.commit()

    result = category_spending_average(
        db, user_id=user.id, ref_year=2026, ref_month=4, months=3,
    )
    # Alleen maart telt: 300 / 3 = 100.
    assert result[cat.id] == Decimal("100.00")


def test_average_ignores_excluded_and_income(db):
    user = _make_user(db)
    acc = _make_account(db, user)
    cat = _make_cat(db, user)
    db.add_all([
        # Positief bedrag = inkomen, niet meetellen.
        Transaction(account_id=acc.id, category_id=cat.id,
                    date=datetime.date(2026, 2, 10),
                    amount=Decimal("5000"), counterparty="salaris",
                    import_hash="h-inc-1",
                    is_excluded=0),
        # Excluded = niet meetellen.
        Transaction(account_id=acc.id, category_id=cat.id,
                    date=datetime.date(2026, 2, 15),
                    amount=Decimal("-800"), counterparty="refund",
                    import_hash="h-exc-1",
                    is_excluded=1),
    ])
    db.commit()
    result = category_spending_average(
        db, user_id=user.id, ref_year=2026, ref_month=4, months=3,
    )
    assert cat.id not in result  # geen valide uitgaven → niet in dict
