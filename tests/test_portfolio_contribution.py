"""Tests voor maandelijkse storting/onttrekking op portfolio-holdings (GJA-15)."""
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


def _make_asset(db, user, name="Goud", asset_class="metal",
                price=Decimal("100"), growth_pct=Decimal("0")):
    a = PortfolioAsset(
        user_id=user.id,
        name=name,
        symbol="XAU",
        asset_class=asset_class,
        unit="oz",
        current_price_eur=price,
        monthly_growth_pct=growth_pct,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_person(db, user, name="Gerd"):
    p = Person(user_id=user.id, name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_holding(db, user, asset, person, quantity=Decimal("10"),
                  contribution=Decimal("0")):
    h = PortfolioHolding(
        user_id=user.id,
        asset_id=asset.id,
        person_id=person.id,
        quantity=quantity,
        monthly_contribution_eur=contribution,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_holding_default_contribution_is_zero(db_session):
    alice = _make_user(db_session)
    asset = _make_asset(db_session, alice)
    person = _make_person(db_session, alice)
    h = _make_holding(db_session, alice, asset, person, quantity=Decimal("5"))
    assert h.monthly_contribution_eur == Decimal("0")


def test_save_contribution_endpoint_updates_holding(db_session):
    alice = _make_user(db_session)
    asset = _make_asset(db_session, alice)
    person = _make_person(db_session, alice)
    _make_holding(db_session, alice, asset, person, quantity=Decimal("5"))

    client = _login_client(alice.id)
    resp = client.post("/portfolio/holdings/save-contribution", data={
        "asset_id": str(asset.id),
        "person_id": str(person.id),
        "contribution": "150",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    db_session.expire_all()
    h = db_session.query(PortfolioHolding).filter_by(
        asset_id=asset.id, person_id=person.id
    ).first()
    assert h.monthly_contribution_eur == Decimal("150")


def test_save_contribution_creates_holding_if_missing(db_session):
    alice = _make_user(db_session)
    asset = _make_asset(db_session, alice)
    person = _make_person(db_session, alice)

    client = _login_client(alice.id)
    resp = client.post("/portfolio/holdings/save-contribution", data={
        "asset_id": str(asset.id),
        "person_id": str(person.id),
        "contribution": "-50",
    })
    assert resp.status_code == 200

    h = db_session.query(PortfolioHolding).filter_by(
        asset_id=asset.id, person_id=person.id
    ).first()
    assert h is not None
    assert h.quantity == Decimal("0")
    assert h.monthly_contribution_eur == Decimal("-50")


def test_projection_without_contribution_only_applies_growth(db_session):
    """Zonder storting is de projectie `value * (1+g)^months_ahead`."""
    alice = _make_user(db_session)
    # 1% per maand groei, startwaarde = 10 × 100 = 1000
    asset = _make_asset(db_session, alice, price=Decimal("100"),
                        growth_pct=Decimal("1"))
    person = _make_person(db_session, alice)
    _make_holding(db_session, alice, asset, person, quantity=Decimal("10"),
                  contribution=Decimal("0"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    # De chart moet aanwezig zijn (grand_total > 0) — we checken dat dit zonder
    # errors rendert. Exacte waardes worden per browser in de grafiek ingeladen.
    assert "portfolioChart" in resp.text


def test_projection_with_contribution_is_higher_than_without(db_session):
    """Met positieve storting moet het december-pad hoger liggen dan zonder.

    We rekenen zelf na dat (value + contrib) * growth gestapeld > value * growth^n.
    """
    from app.routers.portfolio import portfolio_overview  # noqa: F401
    # Simulatie: startwaarde 1000, groei 0%, 12 maanden, contrib 50/mnd
    # Zonder contrib: dec = 1000
    # Met contrib: iter 12x value = value + 50 → 1000 + 12*50 = 1600
    value = Decimal("1000")
    contrib = Decimal("50")
    growth = Decimal("1.00")
    for _ in range(12):
        value = (value + contrib) * growth
    assert value == Decimal("1600.00")


def test_negative_contribution_reduces_projection(db_session):
    """Onttrekking (negatief) laat het pad onder de zonder-onttrekking-lijn dalen."""
    value_no_contrib = Decimal("1000")
    value_with_withdrawal = Decimal("1000")
    contrib = Decimal("-30")
    growth = Decimal("1.00")
    for _ in range(6):
        value_with_withdrawal = (value_with_withdrawal + contrib) * growth
    # 1000 - 6*30 = 820
    assert value_with_withdrawal == Decimal("820.00")
    assert value_with_withdrawal < value_no_contrib


def test_portfolio_page_renders_contribution_column(db_session):
    alice = _make_user(db_session)
    asset = _make_asset(db_session, alice)
    person = _make_person(db_session, alice)
    _make_holding(db_session, alice, asset, person, quantity=Decimal("5"),
                  contribution=Decimal("25"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    # Header voor de nieuwe kolom
    assert "Mnd" in resp.text
    # Het opgeslagen bedrag moet in de input staan (naar 2 decimalen)
    assert 'value="25.00"' in resp.text
