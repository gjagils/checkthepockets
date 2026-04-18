"""Tests voor rente-tabel beheer (GJA-27)."""
import os
import tempfile
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
from app.models import MortgageRateTable, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(MortgageRateTable).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="admin", is_admin=1):
    u = User(
        username=username,
        email=f"{username}@x.nl",
        password_hash=hash_password("pw"),
        is_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_non_admin_gets_404(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    assert _client(user.id).get("/hypotheek/rentes").status_code == 404


def test_create_rate(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).post(
        "/hypotheek/rentes",
        data={"fixed_years": "10", "ltv_max_pct": "85", "interest_rate": "3,75"},
    )
    assert resp.status_code == 302
    assert "flash=added" in resp.headers["location"]

    db_session.expire_all()
    rates = db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).all()
    assert len(rates) == 1
    assert rates[0].fixed_years == 10
    assert rates[0].ltv_max_pct == Decimal("0.85")
    assert rates[0].interest_rate == Decimal("0.0375")


def test_duplicate_rate_rejected(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/rentes", data={"fixed_years": "10", "ltv_max_pct": "85", "interest_rate": "3,75"})
    resp = client.post("/hypotheek/rentes", data={"fixed_years": "10", "ltv_max_pct": "85", "interest_rate": "3,80"})
    assert resp.status_code == 302
    assert "error=duplicate" in resp.headers["location"]

    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).count() == 1


def test_update_rate(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/rentes", data={"fixed_years": "10", "ltv_max_pct": "85", "interest_rate": "3,75"})
    db_session.expire_all()
    row = db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).one()

    resp = client.post(f"/hypotheek/rentes/{row.id}/update", data={"interest_rate": "4,10"})
    assert resp.status_code == 302
    assert "flash=updated" in resp.headers["location"]

    db_session.expire_all()
    updated = db_session.query(MortgageRateTable).filter(MortgageRateTable.id == row.id).one()
    assert updated.interest_rate == Decimal("0.0410")


def test_delete_rate(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/rentes", data={"fixed_years": "5", "ltv_max_pct": "65", "interest_rate": "3,39"})
    row = db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).one()

    resp = client.post(f"/hypotheek/rentes/{row.id}/delete")
    assert resp.status_code == 302

    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).count() == 0


def test_cannot_update_other_users_rate(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    bob_rate = MortgageRateTable(
        user_id=bob.id, fixed_years=10, ltv_max_pct=Decimal("0.85"), interest_rate=Decimal("0.0375"),
    )
    db_session.add(bob_rate)
    db_session.commit()
    db_session.refresh(bob_rate)

    resp = _client(alice.id).post(f"/hypotheek/rentes/{bob_rate.id}/update", data={"interest_rate": "9,99"})
    assert resp.status_code == 404

    db_session.expire_all()
    unchanged = db_session.query(MortgageRateTable).filter(MortgageRateTable.id == bob_rate.id).one()
    assert unchanged.interest_rate == Decimal("0.0375")


def test_seed_fills_empty_table(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).post("/hypotheek/rentes/seed")
    assert resp.status_code == 302
    assert "flash=seeded" in resp.headers["location"]

    db_session.expire_all()
    rows = db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).all()
    assert len(rows) == 12  # 4 rentevast × 3 LTV


def test_seed_refuses_non_empty_table(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/rentes", data={"fixed_years": "10", "ltv_max_pct": "85", "interest_rate": "3,75"})

    resp = client.post("/hypotheek/rentes/seed")
    assert resp.status_code == 302
    assert "error=not_empty" in resp.headers["location"]

    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).count() == 1


def test_invalid_input_rejected(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).post(
        "/hypotheek/rentes",
        data={"fixed_years": "abc", "ltv_max_pct": "85", "interest_rate": "3,75"},
    )
    assert resp.status_code == 302
    assert "error=invalid" in resp.headers["location"]

    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(MortgageRateTable.user_id == admin.id).count() == 0


def test_submenu_rates_visible_for_admin(db_session):
    admin = _make_user(db_session)
    body = _client(admin.id).get("/hypotheek").text
    assert "/hypotheek/rentes" in body
