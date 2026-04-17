"""Tests voor de weekly digest stats-berekening (scheduler.compute_digest_stats)."""
import hashlib
import os
import tempfile
from datetime import datetime, date, timedelta
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DB_FILE.name}")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Account, Transaction, User
from app.scheduler import compute_digest_stats


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        s.query(Transaction).delete()
        s.query(Account).delete()
        s.query(User).delete()
        s.commit()
        yield s
    finally:
        s.close()


def _user(db, name="gj"):
    u = User(username=name, email=f"{name}@example.com", password_hash=hash_password("pw"))
    db.add(u); db.commit(); db.refresh(u)
    return u


def _acc(db, user, name, bank="abn_amro"):
    a = Account(user_id=user.id, name=name, bank=bank)
    db.add(a); db.commit(); db.refresh(a)
    return a


def _tx(db, account, d, amount="-1.00", category_id=None, is_excluded=0, is_projected=0, suffix=""):
    h = hashlib.sha256(f"{account.id}-{d}-{amount}-{suffix}".encode()).hexdigest()
    t = Transaction(
        account_id=account.id, date=d, amount=Decimal(amount), currency="EUR",
        import_hash=h, category_id=category_id, is_excluded=is_excluded, is_projected=is_projected,
    )
    db.add(t); db.commit()
    return t


def test_digest_stats_counts_per_account_and_inbox(db):
    user = _user(db)
    a1 = _acc(db, user, "Samen")
    a2 = _acc(db, user, "Privé")

    today = date.today()
    # Binnen 7 dagen, tellen mee
    _tx(db, a1, today, suffix="a")
    _tx(db, a1, today - timedelta(days=3), suffix="b")
    _tx(db, a2, today - timedelta(days=1), suffix="c")
    # Ouder dan 7 dagen, tellen niet
    _tx(db, a1, today - timedelta(days=10), suffix="d")
    # Excluded/projected tellen niet
    _tx(db, a1, today, is_excluded=1, suffix="e")
    _tx(db, a2, today, is_projected=1, suffix="f")

    per_account, uncat_total, new_total = compute_digest_stats(db, user.id)

    per_account_dict = dict(per_account)
    assert per_account_dict.get("Samen") == 2
    assert per_account_dict.get("Privé") == 1
    assert new_total == 3
    # Alle 3 counted transacties zijn zonder categorie, dus inbox = 3
    assert uncat_total == 3


def test_digest_stats_empty_when_no_activity(db):
    user = _user(db, name="bob")
    _acc(db, user, "Bunq")
    per_account, uncat_total, new_total = compute_digest_stats(db, user.id)
    assert per_account == []
    assert uncat_total == 0
    assert new_total == 0
