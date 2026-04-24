"""Tests voor hypotheek-fundering (GJA-25).

Dekt: modellen importeren + dummy-scenario aanmaken, /hypotheek admin-gated,
menu-link alleen zichtbaar voor admins.
"""
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
from app.models import (
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageVariant,
    User,
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
        db.query(MortgageVariant).delete()
        db.query(MortgageScenario).delete()
        db.query(MortgageRateTable).delete()
        db.query(HouseholdFinance).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice", is_admin=0):
    u = User(
        username=username,
        email=f"{username}@x.nl",
        password_hash=hash_password("pw"),
        is_admin=is_admin,
        can_access_mortgage=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_models_import_and_dummy_scenario(db_session):
    admin = _make_user(db_session, "admin", is_admin=1)

    household = HouseholdFinance(user_id=admin.id, salary_primary=Decimal("3200.00"))
    rate = MortgageRateTable(
        user_id=admin.id,
        fixed_years=10,
        ltv_max_pct=Decimal("0.85"),
        interest_rate=Decimal("0.0375"),
    )
    scenario = MortgageScenario(
        user_id=admin.id,
        name="Bloementuinlaan 12",
        valuation=Decimal("450000"),
        offer=Decimal("435000"),
    )
    db_session.add_all([household, rate, scenario])
    db_session.commit()
    db_session.refresh(scenario)

    variant = MortgageVariant(
        scenario_id=scenario.id,
        fixed_years=10,
        interest_rate_override=None,
    )
    db_session.add(variant)
    db_session.commit()

    assert scenario.id is not None
    assert len(scenario.variants) == 1
    assert scenario.variants[0].fixed_years == 10


def test_hypotheek_requires_admin(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    resp = _client(user.id).get("/hypotheek")
    assert resp.status_code == 404


def test_hypotheek_accessible_for_admin(db_session):
    admin = _make_user(db_session, "adminuser", is_admin=1)
    resp = _client(admin.id).get("/hypotheek")
    assert resp.status_code == 200
    assert "Hypotheek" in resp.text


def test_hypotheek_redirects_when_logged_out():
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/hypotheek")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_menu_link_only_visible_for_admin(db_session):
    regular = _make_user(db_session, "regular", is_admin=0)
    admin = _make_user(db_session, "admin", is_admin=1)

    # Niet-admin: /dashboard rendert maar toont geen Hypotheek-link.
    body_regular = _client(regular.id).get("/dashboard").text
    assert 'href="/hypotheek"' not in body_regular

    # Admin: /dashboard toont wel de Hypotheek-link.
    body_admin = _client(admin.id).get("/dashboard").text
    assert 'href="/hypotheek"' in body_admin
