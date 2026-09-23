"""Tests for ACT-28d one-off wealth bookings."""
import datetime
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
from app.models import Person, PortfolioAsset, PortfolioHolding, User, WealthAdjustment
from app.wealth_forecast import build_wealth_forecast


@pytest.fixture(scope="module", autouse=True)
def schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def setup():
    db = SessionLocal()
    try:
        for model in (WealthAdjustment, PortfolioHolding, PortfolioAsset, Person, User):
            db.query(model).delete()
        user = User(username="alice", email="alice@example.test", password_hash=hash_password("pw"))
        other = User(username="bob", email="bob@example.test", password_hash=hash_password("pw"))
        db.add_all([user, other])
        db.flush()
        person = Person(user_id=user.id, name="Alice")
        other_person = Person(user_id=other.id, name="Bob")
        db.add_all([person, other_person])
        db.flush()
        asset = PortfolioAsset(user_id=user.id, name="Goud", symbol="XAU", asset_class="metal", unit="oz", current_price_eur=Decimal("100"))
        other_asset = PortfolioAsset(user_id=other.id, name="Zilver", symbol="XAG", asset_class="metal", unit="oz", current_price_eur=Decimal("100"))
        db.add_all([asset, other_asset])
        db.flush()
        db.add(PortfolioHolding(user_id=user.id, asset_id=asset.id, person_id=person.id, quantity=Decimal("1")))
        db.add(PortfolioHolding(user_id=other.id, asset_id=other_asset.id, person_id=other_person.id, quantity=Decimal("1")))
        db.commit()
        client = TestClient(app)
        client.cookies.set("session", create_session_cookie(user.id))
        yield db, client, user, person, asset, other_asset, other_person
    finally:
        db.close()


def test_adjustment_recalculates_forecast_and_can_be_cleared(setup):
    db, client, user, person, asset, _, _ = setup
    response = client.post("/portfolio/wealth-adjustments", data={
        "asset_id": asset.id, "person_id": person.id, "year": 2026, "month": 2, "amount": "-50,00",
    })
    assert response.status_code == 200
    forecast = build_wealth_forecast(db, user.id, 2026, today=datetime.date(2026, 1, 1))
    assert forecast["per_person"][person.id][2]["portfolio"] == Decimal("48.20")
    response = client.post("/portfolio/wealth-adjustments", data={
        "asset_id": asset.id, "person_id": person.id, "year": 2026, "month": 2, "amount": "",
    })
    assert response.status_code == 200
    assert db.query(WealthAdjustment).count() == 0


def test_adjustment_rejects_another_users_asset_or_person(setup):
    _, client, _, _, _, other_asset, other_person = setup
    response = client.post("/portfolio/wealth-adjustments", data={
        "asset_id": other_asset.id, "person_id": other_person.id, "year": 2026, "month": 2, "amount": "50",
    })
    assert response.status_code == 404
