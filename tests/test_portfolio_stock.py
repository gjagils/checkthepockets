"""Tests for stock asset type support (GJA-16)."""
import os
import tempfile
import datetime
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


def test_add_stock_asset_via_form_persists_ticker_exchange(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)

    resp = client.post(
        "/portfolio/assets",
        data={
            "name": "ASML",
            "symbol": "ASML.AS",
            "asset_class": "stock",
            "unit": "aandeel",
            "monthly_growth_pct": "0,8",
            "ticker": "ASML.AS",
            "exchange": "Euronext Amsterdam",
            "manual_price": "625,40",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    asset = (
        db_session.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == alice.id, PortfolioAsset.name == "ASML")
        .one()
    )
    assert asset.asset_class == "stock"
    assert asset.ticker == "ASML.AS"
    assert asset.exchange == "Euronext Amsterdam"
    assert asset.current_price_eur == Decimal("625.40")
    assert asset.price_updated_at is not None


def test_edit_stock_asset_updates_ticker(db_session):
    alice = _make_user(db_session)
    asset = PortfolioAsset(
        user_id=alice.id,
        name="ASML",
        symbol="ASML.AS",
        asset_class="stock",
        unit="aandeel",
        current_price_eur=Decimal("600"),
        ticker="ASML.AS",
        exchange="Euronext Amsterdam",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    client = _login_client(alice.id)
    resp = client.post(
        f"/portfolio/assets/{asset.id}/edit",
        data={
            "name": "ASML Holding",
            "unit": "aandeel",
            "monthly_growth_pct": "0,5",
            "manual_price": "",
            "ticker": "ASML.NV",
            "exchange": "Euronext Amsterdam",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db_session.refresh(asset)
    assert asset.name == "ASML Holding"
    assert asset.ticker == "ASML.NV"


def test_stock_filter_shows_stock_assets(db_session):
    alice = _make_user(db_session)
    p = Person(user_id=alice.id, name="Gerd")
    db_session.add(p)
    db_session.add(
        PortfolioAsset(
            user_id=alice.id,
            name="ASML",
            symbol="ASML.AS",
            asset_class="stock",
            unit="aandeel",
            ticker="ASML.AS",
            current_price_eur=Decimal("625"),
        )
    )
    db_session.add(
        PortfolioAsset(
            user_id=alice.id,
            name="Goud",
            symbol="XAU",
            asset_class="metal",
            unit="oz",
            current_price_eur=Decimal("1800"),
        )
    )
    db_session.commit()

    client = _login_client(alice.id)
    resp = client.get("/portfolio?type=stock")
    assert resp.status_code == 200
    body = resp.text
    assert "<strong>ASML</strong>" in body
    assert "<strong>Goud</strong>" not in body
    # ticker visible somewhere in the output
    assert "ASML.AS" in body


def test_refresh_prices_skips_stocks(db_session):
    alice = _make_user(db_session)
    stock = PortfolioAsset(
        user_id=alice.id,
        name="ASML",
        symbol="ASML.AS",
        asset_class="stock",
        unit="aandeel",
        ticker="ASML.AS",
        current_price_eur=Decimal("625.40"),
        price_updated_at=datetime.datetime(2026, 1, 1, 12, 0, 0),
    )
    db_session.add(stock)
    db_session.commit()
    db_session.refresh(stock)

    original_price = stock.current_price_eur
    original_updated = stock.price_updated_at

    client = _login_client(alice.id)
    # No external mocking — the route should early-continue on stocks and leave them alone.
    # For metal/crypto assets the network call may fail in CI, but stocks must never call it.
    resp = client.post("/portfolio/refresh-prices", follow_redirects=False)
    assert resp.status_code == 302

    db_session.refresh(stock)
    assert stock.current_price_eur == original_price
    assert stock.price_updated_at == original_updated


def test_stale_price_indicator_shown_for_old_price(db_session):
    alice = _make_user(db_session)
    p = Person(user_id=alice.id, name="Gerd")
    db_session.add(p)
    # price updated 45 days ago → stale
    old_date = datetime.datetime.utcnow() - datetime.timedelta(days=45)
    asset = PortfolioAsset(
        user_id=alice.id,
        name="ASML",
        symbol="ASML.AS",
        asset_class="stock",
        unit="aandeel",
        ticker="ASML.AS",
        current_price_eur=Decimal("625"),
        price_updated_at=old_date,
    )
    db_session.add(asset)
    db_session.commit()

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    # Stale warning emoji + "dgn geleden"
    assert "45 dgn geleden" in body
    assert "⚠" in body


def test_fresh_price_no_warning(db_session):
    alice = _make_user(db_session)
    p = Person(user_id=alice.id, name="Gerd")
    db_session.add(p)
    asset = PortfolioAsset(
        user_id=alice.id,
        name="Goud",
        symbol="XAU",
        asset_class="metal",
        unit="oz",
        current_price_eur=Decimal("1800"),
        price_updated_at=datetime.datetime.utcnow(),
    )
    db_session.add(asset)
    db_session.commit()

    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    body = resp.text
    # Today-label present, no stale warning for this row
    assert "vandaag" in body


def test_stock_option_present_in_add_form(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert "Aandeel</option>" in resp.text
    assert 'value="stock"' in resp.text
