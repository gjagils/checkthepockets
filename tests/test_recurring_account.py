"""Tests for account_id op RecurringTransaction (GJA-23)."""
import hashlib
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, Category, RecurringTransaction, Transaction, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(Transaction).delete()
        db.query(RecurringTransaction).delete()
        db.query(Category).delete()
        db.query(Account).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice"):
    u = User(username=username, email=f"{username}@x.nl", password_hash=hash_password("pw"))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user, name="Main"):
    a = Account(user_id=user.id, name=name, bank="custom", iban=f"NL{user.id:02d}{name[:4]:_<4}0000")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_category(db, user, name="Abonnementen"):
    c = Category(user_id=user.id, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_create_without_account_rejected(db_session):
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    _make_account(db_session, alice)

    client = _login_client(alice.id)
    resp = client.post(
        "/recurring",
        data={
            "name": "Spotify",
            "amount_expected": "-9.99",
            "frequency": "monthly",
            "category_id": str(cat.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "account_required" in resp.headers["location"]
    assert db_session.query(RecurringTransaction).count() == 0


def test_create_with_account_persists(db_session):
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    acc = _make_account(db_session, alice, "ABN")

    client = _login_client(alice.id)
    resp = client.post(
        "/recurring",
        data={
            "name": "Spotify",
            "amount_expected": "-9.99",
            "frequency": "monthly",
            "account_id": str(acc.id),
            "category_id": str(cat.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    item = db_session.query(RecurringTransaction).one()
    assert item.account_id == acc.id


def test_create_with_other_users_account_rejected(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    cat = _make_category(db_session, alice)
    acc_bob = _make_account(db_session, bob, "BobAcc")

    client = _login_client(alice.id)
    resp = client.post(
        "/recurring",
        data={
            "name": "Spotify",
            "amount_expected": "-9.99",
            "frequency": "monthly",
            "account_id": str(acc_bob.id),
            "category_id": str(cat.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "account_required" in resp.headers["location"]
    assert db_session.query(RecurringTransaction).count() == 0


def test_edit_can_clear_account_id(db_session):
    """Backward compat: leeg laten = NULL."""
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    acc = _make_account(db_session, alice)
    item = RecurringTransaction(
        user_id=alice.id, account_id=acc.id, name="X",
        amount_expected=Decimal("-10"), frequency="monthly", category_id=cat.id,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    client = _login_client(alice.id)
    resp = client.post(
        f"/recurring/{item.id}/edit",
        data={
            "name": "X",
            "amount_expected": "-10",
            "frequency": "monthly",
            "account_id": "",
            "category_id": str(cat.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.refresh(item)
    assert item.account_id is None


def test_edit_changes_account(db_session):
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    a1 = _make_account(db_session, alice, "A")
    a2 = _make_account(db_session, alice, "B")
    item = RecurringTransaction(
        user_id=alice.id, account_id=a1.id, name="X",
        amount_expected=Decimal("-10"), frequency="monthly", category_id=cat.id,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    client = _login_client(alice.id)
    resp = client.post(
        f"/recurring/{item.id}/edit",
        data={
            "name": "X",
            "amount_expected": "-10",
            "frequency": "monthly",
            "account_id": str(a2.id),
            "category_id": str(cat.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.refresh(item)
    assert item.account_id == a2.id


def test_projected_tx_filtered_by_account(db_session):
    """Op /transactions?account_id=X zie je alleen projecties van die rekening."""
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    a1 = _make_account(db_session, alice, "ABN")
    a2 = _make_account(db_session, alice, "BUNQ")

    # Seed een echte transactie voor beide accounts zodat sync_projected niet skipt
    for acc in (a1, a2):
        h = hashlib.sha256(f"seed-{acc.id}".encode()).hexdigest()
        db_session.add(Transaction(
            account_id=acc.id, date=date(2026, 1, 15),
            amount=Decimal("-100"), currency="EUR",
            description="seed", import_hash=h,
        ))
    db_session.commit()

    # Recurring voor a1
    r1 = RecurringTransaction(
        user_id=alice.id, account_id=a1.id, name="R1",
        amount_expected=Decimal("-10"), frequency="monthly", category_id=cat.id,
    )
    # Recurring voor a2
    r2 = RecurringTransaction(
        user_id=alice.id, account_id=a2.id, name="R2",
        amount_expected=Decimal("-20"), frequency="monthly", category_id=cat.id,
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    client = _login_client(alice.id)
    # Filter op account a1 → projectie voor R2 mag niet zichtbaar zijn
    resp = client.get(f"/transactions?month=2026-02&account_id={a1.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "R1" in body
    assert "R2" not in body


def test_projected_tx_null_account_visible_everywhere(db_session):
    """Recurring zonder rekening blijft zichtbaar op elk account-filter."""
    alice = _make_user(db_session)
    cat = _make_category(db_session, alice)
    a1 = _make_account(db_session, alice, "ABN")
    a2 = _make_account(db_session, alice, "BUNQ")

    for acc in (a1, a2):
        h = hashlib.sha256(f"seed2-{acc.id}".encode()).hexdigest()
        db_session.add(Transaction(
            account_id=acc.id, date=date(2026, 1, 15),
            amount=Decimal("-100"), currency="EUR",
            description="seed", import_hash=h,
        ))
    db_session.commit()

    # Recurring zonder account (legacy)
    r_legacy = RecurringTransaction(
        user_id=alice.id, account_id=None, name="LegacyRec",
        amount_expected=Decimal("-5"), frequency="monthly", category_id=cat.id,
    )
    db_session.add(r_legacy)
    db_session.commit()

    client = _login_client(alice.id)
    resp = client.get(f"/transactions?month=2026-02&account_id={a1.id}")
    assert resp.status_code == 200
    assert "LegacyRec" in resp.text
