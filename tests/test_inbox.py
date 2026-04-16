"""Tests for the /inbox page (GJA-6)."""
import hashlib
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

# Use an on-disk sqlite DB so the app + test share the same store.
_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, Category, Transaction, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        # Clean tables that tests touch
        db.query(Transaction).delete()
        db.query(Category).delete()
        db.query(Account).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice", email="alice@example.com"):
    u = User(username=username, email=email, password_hash=hash_password("pw"))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user, name="Main"):
    a = Account(user_id=user.id, name=name, bank="custom", iban=f"NL{user.id:02d}TEST0000000000")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_category(db, user, name, parent_id=None):
    c = Category(user_id=user.id, name=name, parent_id=parent_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_tx(db, account, *, category_id=None, amount="-12.50", counterparty="Shop", tag="t"):
    h = hashlib.sha256(f"{account.id}-{tag}-{counterparty}-{amount}".encode()).hexdigest()
    tx = Transaction(
        account_id=account.id,
        date=date(2026, 1, 1),
        amount=Decimal(amount),
        currency="EUR",
        description=f"desc-{tag}",
        counterparty=counterparty,
        category_id=category_id,
        import_hash=h,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


# ── Filter-query tests ──────────────────────────────────────────────────────

def test_inbox_shows_only_uncategorized_of_current_user(db_session):
    alice = _make_user(db_session, "alice", "a@x.nl")
    bob = _make_user(db_session, "bob", "b@x.nl")

    acc_a = _make_account(db_session, alice, "Alice Main")
    acc_b = _make_account(db_session, bob, "Bob Main")
    cat = _make_category(db_session, alice, "Boodschappen")

    tx_uncat = _make_tx(db_session, acc_a, category_id=None, counterparty="AH", tag="u1")
    _make_tx(db_session, acc_a, category_id=cat.id, counterparty="Jumbo", tag="c1")
    _make_tx(db_session, acc_b, category_id=None, counterparty="Other", tag="other")

    client = _login_client(alice.id)
    resp = client.get("/inbox")
    assert resp.status_code == 200
    body = resp.text
    # Alice ziet haar ongecategoriseerde tx
    assert "AH" in body
    # Niet haar gecategoriseerde tx
    assert "Jumbo" not in body
    # Niet andermans tx
    assert "Other" not in body
    # Teller klopt
    assert "1 te categoriseren" in body
    # Inbox-link in nav heeft badge
    assert "nav-inbox-badge" in body


def test_inbox_redirects_to_login_when_unauthenticated(db_session):
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/inbox")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


# ── POST endpoint tests ─────────────────────────────────────────────────────

def test_post_category_assigns_and_removes_from_inbox(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)
    parent = _make_category(db_session, alice, "Huis")
    sub = _make_category(db_session, alice, "Energie", parent_id=parent.id)
    tx = _make_tx(db_session, acc, counterparty="Eneco", tag="e")

    client = _login_client(alice.id)
    resp = client.post(
        f"/inbox/{tx.id}/category",
        data={"category_id": sub.id},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/inbox"

    db_session.expire_all()
    refreshed = db_session.query(Transaction).filter(Transaction.id == tx.id).one()
    assert refreshed.category_id == sub.id
    assert refreshed.is_reviewed == 1

    body = client.get("/inbox").text
    assert "Eneco" not in body
    assert "0 te categoriseren" in body


# ── Cross-user (unauthorized) tests ─────────────────────────────────────────

def test_post_category_for_other_users_transaction_is_rejected(db_session):
    alice = _make_user(db_session, "alice", "a@x.nl")
    bob = _make_user(db_session, "bob", "b@x.nl")
    acc_bob = _make_account(db_session, bob, "Bob")
    cat_alice = _make_category(db_session, alice, "Boodschappen")
    tx_bob = _make_tx(db_session, acc_bob, counterparty="BobShop", tag="b")

    # Alice probeert Bob's tx te categoriseren
    client = _login_client(alice.id)
    resp = client.post(
        f"/inbox/{tx_bob.id}/category",
        data={"category_id": cat_alice.id},
        follow_redirects=False,
    )
    # Endpoint weigert stilzwijgend (redirect naar /inbox)
    assert resp.status_code == 303

    db_session.expire_all()
    tx = db_session.query(Transaction).filter(Transaction.id == tx_bob.id).one()
    assert tx.category_id is None
    assert tx.is_reviewed == 0


