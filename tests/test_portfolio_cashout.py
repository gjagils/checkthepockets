"""Tests for per-asset cashout fees (GJA-17)."""
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
    Person,
    PortfolioAsset,
    PortfolioHolding,
    PortfolioPriceSnapshot,
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
        db.query(PortfolioPriceSnapshot).delete()
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


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def _setup_asset(db, user, person, qty=Decimal("10"), price=Decimal("100"),
                 fee_fixed=Decimal("0"), fee_pct=Decimal("0")):
    asset = PortfolioAsset(
        user_id=user.id,
        name="Goud",
        symbol="XAU",
        asset_class="metal",
        unit="oz",
        current_price_eur=price,
        cashout_fee_fixed_eur=fee_fixed,
        cashout_fee_pct=fee_pct,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    holding = PortfolioHolding(user_id=user.id, asset_id=asset.id, person_id=person.id, quantity=qty)
    db.add(holding)
    db.commit()
    return asset


def test_no_fees_no_cashout_row(db_session):
    alice = _make_user(db_session)
    person = Person(user_id=alice.id, name="Gerd")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    _setup_asset(db_session, alice, person)

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert "Contant na aftrek" not in resp.text


def test_fixed_fee_only(db_session):
    alice = _make_user(db_session)
    person = Person(user_id=alice.id, name="Gerd")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    # gross = 10 * 100 = 1000, fee = 25 → cash = 975
    _setup_asset(db_session, alice, person, fee_fixed=Decimal("25"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    assert "Contant na aftrek" in body
    assert "975" in body


def test_pct_fee_only(db_session):
    alice = _make_user(db_session)
    person = Person(user_id=alice.id, name="Gerd")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    # gross = 1000, 2% = 20 → cash = 980
    _setup_asset(db_session, alice, person, fee_pct=Decimal("2"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    assert "Contant na aftrek" in body
    assert "980" in body


def test_combined_fees(db_session):
    alice = _make_user(db_session)
    person = Person(user_id=alice.id, name="Gerd")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    # gross = 1000, 1% = 10, vast = 50 → cash = 940
    _setup_asset(db_session, alice, person,
                 fee_fixed=Decimal("50"), fee_pct=Decimal("1"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    assert "Contant na aftrek" in body
    assert "940" in body


def test_fee_exceeds_value_clamped_to_zero(db_session):
    alice = _make_user(db_session)
    person = Person(user_id=alice.id, name="Gerd")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    # gross = 1000, fixed = 2000 → cash = 0 (clamped)
    _setup_asset(db_session, alice, person, fee_fixed=Decimal("2000"))

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    # Cash row should be present and show 0
    assert "Contant na aftrek" in resp.text


def test_add_asset_form_persists_fees(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)

    resp = client.post(
        "/portfolio/assets",
        data={
            "name": "Bitcoin",
            "symbol": "bitcoin",
            "asset_class": "crypto",
            "unit": "BTC",
            "monthly_growth_pct": "0",
            "cashout_fee_fixed_eur": "15,50",
            "cashout_fee_pct": "0,75",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    asset = (
        db_session.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == alice.id, PortfolioAsset.name == "Bitcoin")
        .one()
    )
    assert asset.cashout_fee_fixed_eur == Decimal("15.50")
    assert asset.cashout_fee_pct == Decimal("0.75")


def test_edit_asset_updates_fees(db_session):
    alice = _make_user(db_session)
    asset = PortfolioAsset(
        user_id=alice.id,
        name="Goud",
        symbol="XAU",
        asset_class="metal",
        unit="oz",
        current_price_eur=Decimal("1800"),
        cashout_fee_fixed_eur=Decimal("0"),
        cashout_fee_pct=Decimal("0"),
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    client = _login_client(alice.id)
    resp = client.post(
        f"/portfolio/assets/{asset.id}/edit",
        data={
            "name": "Goud",
            "unit": "oz",
            "monthly_growth_pct": "0",
            "manual_price": "",
            "cashout_fee_fixed_eur": "10",
            "cashout_fee_pct": "1,25",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db_session.refresh(asset)
    assert asset.cashout_fee_fixed_eur == Decimal("10")
    assert asset.cashout_fee_pct == Decimal("1.25")


def test_person_cash_sums_to_grand_cash(db_session):
    """Met twee personen die samen een asset bezitten, moet som(person_cash) == grand_cash."""
    alice = _make_user(db_session)
    gerd = Person(user_id=alice.id, name="Gerd")
    marie = Person(user_id=alice.id, name="Marie")
    db_session.add_all([gerd, marie])
    db_session.commit()
    db_session.refresh(gerd)
    db_session.refresh(marie)

    # Asset: 1000 EUR totaal, 60/40 verdeling, fixed fee 100 → cash 900
    # Gerd: 600 → cash 540, Marie: 400 → cash 360, som = 900
    asset = PortfolioAsset(
        user_id=alice.id,
        name="Goud",
        symbol="XAU",
        asset_class="metal",
        unit="oz",
        current_price_eur=Decimal("100"),
        cashout_fee_fixed_eur=Decimal("100"),
        cashout_fee_pct=Decimal("0"),
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    db_session.add(PortfolioHolding(user_id=alice.id, asset_id=asset.id, person_id=gerd.id, quantity=Decimal("6")))
    db_session.add(PortfolioHolding(user_id=alice.id, asset_id=asset.id, person_id=marie.id, quantity=Decimal("4")))
    db_session.commit()

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    # Totale opnamewaarde minus fee = 900 zichtbaar
    assert "Contant na aftrek" in body
    assert "900" in body
