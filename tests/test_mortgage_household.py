"""Tests voor huishoud-instellingen pagina (GJA-26)."""
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
from app.models import HouseholdFinance, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(HouseholdFinance).delete()
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


def test_first_visit_seeds_defaults(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).get("/hypotheek/huishouden")
    assert resp.status_code == 200
    assert "Huishoud-instellingen" in resp.text

    db_session.expire_all()
    hf = db_session.query(HouseholdFinance).filter(HouseholdFinance.user_id == admin.id).one()
    assert hf.tax_rate == Decimal("0.3697")
    assert hf.notional_rent_value == Decimal("3600")
    assert hf.purchase_costs_pct == Decimal("0.025")
    assert hf.selling_costs_pct == Decimal("0.015")


def test_non_admin_gets_404(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    resp = _client(user.id).get("/hypotheek/huishouden")
    assert resp.status_code == 404


def test_save_and_update_household(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)

    resp = client.post(
        "/hypotheek/huishouden",
        data={
            "salary_primary_name": "Nelleke",
            "salary_primary": "3200,00",
            "salary_secondary_name": "Gerd-Jan",
            "salary_secondary": "2800,50",
            "existing_mortgage_pim": "150000",
            "existing_mortgage_pim_rate": "3,75",
            "existing_mortgage_pim_refund_rate": "36,97",
            "existing_mortgage_interest_only": "50000",
            "existing_mortgage_interest_only_monthly": "150,00",
            "current_home_debt": "280000",
            "tax_rate": "36,97",
            "notional_rent_value": "3600",
            "purchase_costs_pct": "2,5",
            "selling_costs_pct": "1,5",
        },
    )
    assert resp.status_code == 302
    assert "/hypotheek/huishouden?saved=1" in resp.headers["location"]

    db_session.expire_all()
    hf = db_session.query(HouseholdFinance).filter(HouseholdFinance.user_id == admin.id).one()
    assert hf.salary_primary_name == "Nelleke"
    assert hf.salary_primary == Decimal("3200.00")
    assert hf.salary_secondary == Decimal("2800.50")
    assert hf.existing_mortgage_pim == Decimal("150000")
    assert hf.existing_mortgage_pim_rate == Decimal("0.0375")
    assert hf.current_home_debt == Decimal("280000")
    assert hf.tax_rate == Decimal("0.3697")

    # Update: wijzig 1 veld, verifieer dat overige behouden blijven.
    resp = client.post(
        "/hypotheek/huishouden",
        data={
            "salary_primary_name": "Nelleke",
            "salary_primary": "3500,00",
            "salary_secondary_name": "Gerd-Jan",
            "salary_secondary": "2800,50",
            "existing_mortgage_pim": "150000",
            "existing_mortgage_pim_rate": "3,75",
            "existing_mortgage_pim_refund_rate": "36,97",
            "existing_mortgage_interest_only": "50000",
            "existing_mortgage_interest_only_monthly": "150,00",
            "current_home_debt": "280000",
            "tax_rate": "36,97",
            "notional_rent_value": "3600",
            "purchase_costs_pct": "2,5",
            "selling_costs_pct": "1,5",
        },
    )
    assert resp.status_code == 302

    db_session.expire_all()
    hf = db_session.query(HouseholdFinance).filter(HouseholdFinance.user_id == admin.id).one()
    assert hf.salary_primary == Decimal("3500.00")
    # Geen dubbele rijen:
    assert db_session.query(HouseholdFinance).filter(HouseholdFinance.user_id == admin.id).count() == 1


def test_saved_flash_visible(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).get("/hypotheek/huishouden?saved=1")
    assert resp.status_code == 200
    assert "Opgeslagen" in resp.text


def test_submenu_household_visible_for_admin(db_session):
    admin = _make_user(db_session)
    body = _client(admin.id).get("/hypotheek").text
    assert "/hypotheek/huishouden" in body
