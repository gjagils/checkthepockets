"""Tests voor scripts/seed_demo_user.py + POST /admin/demo/seed (GJA-46)."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

# Vóór de app-imports: tijdelijke sqlite-DB en dummy-secret.
_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password, verify_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    Account,
    Budget,
    Category,
    Person,
    Transaction,
    User,
)
from scripts.seed_demo_user import (
    CATEGORIES,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    INBOX_TX,
    MONTHLY_TX,
    seed_demo_user,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(Budget).delete()
        db.query(Transaction).delete()
        db.query(Category).delete()
        for acc in db.query(Account).all():
            acc.owners = []
        db.commit()
        db.query(Account).delete()
        db.query(Person).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


# ── Smoke-test: één run produceert het verwachte volume ──────────────────


def test_seed_creates_demo_user_with_expected_volume(db_session):
    today = date(2026, 6, 15)  # vaste "vandaag" voor deterministische tellingen

    result = seed_demo_user(today=today, db=db_session)

    user = db_session.query(User).filter_by(username=DEFAULT_USERNAME).one()

    # User-basics — géén admin (hypotheek-toegang komt via GJA-47)
    assert user.is_admin == 0
    assert user.is_verified == 1
    assert user.is_active == 1
    assert verify_password(DEFAULT_PASSWORD, user.password_hash)

    # Personen
    persons = db_session.query(Person).filter_by(user_id=user.id).order_by(Person.sort_order).all()
    assert [p.name for p in persons] == ["Demo Alex", "Demo Sam"]

    # Accounts + owners
    accounts = db_session.query(Account).filter_by(user_id=user.id).all()
    assert len(accounts) == 3
    by_name = {a.name: a for a in accounts}
    assert set(by_name) == {
        "Betaalrekening Alex", "Spaarrekening", "Gezamenlijke rekening",
    }
    assert {p.name for p in by_name["Gezamenlijke rekening"].owners} == {"Demo Alex", "Demo Sam"}
    assert {p.name for p in by_name["Betaalrekening Alex"].owners} == {"Demo Alex"}

    # Categories incl. cost_scale_type markering
    cats = db_session.query(Category).filter_by(user_id=user.id).all()
    assert len(cats) == len(CATEGORIES)
    by_cat = {c.name: c for c in cats}
    assert by_cat["Wonen"].cost_scale_type == "mortgage"
    assert by_cat["Verzekeringen"].cost_scale_type == "insurance"
    assert by_cat["Gemeente & heffingen"].cost_scale_type == "municipal"
    assert by_cat["Salaris"].is_income == 1

    # Transactions: 12 maanden × MONTHLY_TX (beperkt tot ≤ today) + INBOX_TX
    txs = db_session.query(Transaction).join(Account).filter(Account.user_id == user.id).all()
    inbox_count = sum(1 for t in txs if t.category_id is None)
    assert inbox_count == len(INBOX_TX)

    categorised = [t for t in txs if t.category_id is not None]
    # Minstens 11 volle maanden, maximaal 12 (juni 2026 is partial op day=15):
    assert 11 * len(MONTHLY_TX) <= len(categorised) < 12 * len(MONTHLY_TX)

    # Budgetten: 12 maanden × elke categorie met monthly_budget
    budget_specs = [s for s in CATEGORIES if s.monthly_budget is not None]
    budgets = db_session.query(Budget).filter_by(user_id=user.id).all()
    assert len(budgets) == 12 * len(budget_specs)

    # Resultaat-object klopt met DB-state
    assert result.tx_count == len(txs)
    assert result.budget_count == len(budgets)
    assert result.category_count == len(cats)
    assert result.account_count == len(accounts)
    assert result.person_count == len(persons)


# ── Idempotentie: tweede run wist + heraanmaakt zonder fouten ────────────


def test_seed_is_idempotent(db_session):
    today = date(2026, 6, 15)

    first = seed_demo_user(today=today, db=db_session)
    first_volume = (
        db_session.query(Transaction).count(),
        db_session.query(Budget).count(),
        db_session.query(Category).count(),
    )

    second = seed_demo_user(today=today, db=db_session)
    assert second.username == DEFAULT_USERNAME

    # Exact één user met die naam (oude is gewist, niet bewaard).
    assert db_session.query(User).filter_by(username=DEFAULT_USERNAME).count() == 1

    # Totale volumes identiek aan eerste run (geen accumulatie).
    second_volume = (
        db_session.query(Transaction).count(),
        db_session.query(Budget).count(),
        db_session.query(Category).count(),
    )
    assert first_volume == second_volume


# ── Naast-elkaar bestaan met andere users mag niet kapot gaan ────────────


def test_seed_does_not_touch_other_users(db_session):
    other = User(
        username="alice", email="alice@x.nl",
        password_hash=hash_password("pw"), is_verified=1,
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    other_id = other.id  # vasthouden — seed kan instance detachen

    other_acc = Account(user_id=other_id, name="Alice main", bank="custom", iban="NL99TEST0000000001")
    db_session.add(other_acc)
    db_session.commit()
    other_acc_id = other_acc.id

    seed_demo_user(today=date(2026, 6, 15), db=db_session)

    assert db_session.query(User).filter_by(id=other_id).count() == 1
    assert db_session.query(Account).filter_by(id=other_acc_id).count() == 1


# ── Custom credentials via parameter ─────────────────────────────────────


def test_seed_accepts_custom_credentials(db_session):
    seed_demo_user(
        username="acme-demo",
        password="hunter2hunter2",
        email="acme@example.org",
        today=date(2026, 6, 15),
        db=db_session,
    )
    user = db_session.query(User).filter_by(username="acme-demo").one()
    assert user.email == "acme@example.org"
    assert verify_password("hunter2hunter2", user.password_hash)


# ── Admin-UI endpoint: POST /admin/demo/seed ─────────────────────────────


def _make_admin(db, username="admin"):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"), is_verified=1, is_admin=1,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_regular(db, username="bob"):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"), is_verified=1, is_admin=0,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_admin_demo_seed_endpoint_creates_demo_user(db_session):
    admin = _make_admin(db_session)
    admin_id = admin.id

    client = _login_client(admin_id)
    resp = client.post("/admin/demo/seed")

    assert resp.status_code == 200
    body = resp.text
    assert "Demo-user" in body
    assert "demo" in body  # username in flash

    # Demo-user bestaat nu in de DB
    demo = db_session.query(User).filter_by(username=DEFAULT_USERNAME).one()
    assert demo.is_admin == 0
    assert db_session.query(Account).filter_by(user_id=demo.id).count() == 3


def test_admin_demo_seed_is_idempotent_via_endpoint(db_session):
    admin = _make_admin(db_session)
    client = _login_client(admin.id)

    client.post("/admin/demo/seed")
    first_tx = db_session.query(Transaction).count()

    client.post("/admin/demo/seed")
    second_tx = db_session.query(Transaction).count()

    # Identiek volume — de tweede call heeft niet opgestapeld.
    assert first_tx == second_tx
    assert db_session.query(User).filter_by(username=DEFAULT_USERNAME).count() == 1


def test_admin_demo_seed_rejects_non_admin(db_session):
    bob = _make_regular(db_session)
    client = _login_client(bob.id)

    resp = client.post("/admin/demo/seed")
    assert resp.status_code == 403

    # Geen demo-user aangemaakt
    assert db_session.query(User).filter_by(username=DEFAULT_USERNAME).count() == 0


def test_admin_demo_seed_rejects_anonymous():
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/admin/demo/seed")
    # Niet ingelogd → login-redirect (302) of 401/403; alle drie wijzen de
    # aanroep af. We accepteren alle drie zolang er geen data is gewijzigd.
    assert resp.status_code in (302, 401, 403)
