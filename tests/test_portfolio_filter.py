"""Tests for the /portfolio?type=... filter (GJA-19)."""
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
from app.models import Person, PortfolioAsset, PortfolioHolding, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(PortfolioHolding).delete()
        db.query(PortfolioAsset).delete()
        db.query(Person).delete()
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


def _make_asset(db, user, name, asset_class, symbol="SYM"):
    a = PortfolioAsset(
        user_id=user.id,
        name=name,
        symbol=symbol,
        asset_class=asset_class,
        unit="stuk",
        current_price_eur=Decimal("100"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_person(db, user, name="P1"):
    p = Person(user_id=user.id, name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_portfolio_no_filter_shows_all_assets(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice, "Gerd")
    _make_asset(db_session, alice, "Goud", "metal")
    _make_asset(db_session, alice, "Bitcoin", "crypto")

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    assert "<strong>Goud</strong>" in body
    assert "<strong>Bitcoin</strong>" in body


def test_portfolio_filter_metal_shows_only_metal(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice, "Gerd")
    _make_asset(db_session, alice, "Goud", "metal")
    _make_asset(db_session, alice, "Bitcoin", "crypto")

    client = _login_client(alice.id)
    resp = client.get("/portfolio?type=metal")
    assert resp.status_code == 200
    body = resp.text
    assert "<strong>Goud</strong>" in body
    assert "<strong>Bitcoin</strong>" not in body


def test_portfolio_filter_crypto_shows_only_crypto(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice, "Gerd")
    _make_asset(db_session, alice, "Goud", "metal")
    _make_asset(db_session, alice, "Bitcoin", "crypto")

    client = _login_client(alice.id)
    resp = client.get("/portfolio?type=crypto")
    assert resp.status_code == 200
    body = resp.text
    assert "<strong>Bitcoin</strong>" in body
    assert "<strong>Goud</strong>" not in body


def test_portfolio_filter_stock_shows_empty_state_and_notice(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice, "Gerd")
    _make_asset(db_session, alice, "Goud", "metal")
    _make_asset(db_session, alice, "Bitcoin", "crypto")

    client = _login_client(alice.id)
    resp = client.get("/portfolio?type=stock")
    assert resp.status_code == 200
    body = resp.text
    # Uitleg-banner voor Beleggingen
    assert "Beleggingen" in body
    assert "aandelen" in body.lower()
    # Geen metal/crypto assets zichtbaar in de tabel
    assert "<strong>Goud</strong>" not in body
    assert "<strong>Bitcoin</strong>" not in body


def test_portfolio_invalid_filter_falls_back_to_all(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice, "Gerd")
    _make_asset(db_session, alice, "Goud", "metal")
    _make_asset(db_session, alice, "Bitcoin", "crypto")

    client = _login_client(alice.id)
    resp = client.get("/portfolio?type=bogus")
    assert resp.status_code == 200
    body = resp.text
    assert "<strong>Goud</strong>" in body
    assert "<strong>Bitcoin</strong>" in body


def test_networth_route_still_works(db_session):
    """Vermogen is uit het menu, maar de route moet blijven werken."""
    alice = _make_user(db_session)

    client = _login_client(alice.id)
    resp = client.get("/networth")
    assert resp.status_code == 200


def test_portfolio_menu_shows_subs(db_session):
    """Op /portfolio moet het submenu de juiste subs tonen."""
    alice = _make_user(db_session)

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    # Hoofdmenu-label
    assert ">Portfolio<" in body
    # Subs
    assert "/portfolio?type=stock" in body
    assert "/portfolio?type=crypto" in body
    assert "/portfolio?type=metal" in body
    # Vermogen-link mag niet meer in het hoofd-/submenu staan als zodanig
    assert ">Vermogen<" not in body
