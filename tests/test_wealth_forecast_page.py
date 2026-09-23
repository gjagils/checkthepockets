"""HTTP coverage for the ACT-28c wealth-forecast page."""
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
from app.models import Person, PortfolioAsset, PortfolioHolding, User, WealthPlan, WealthPlanEntry
from app.wealth_plan_service import capture_wealth_plan


@pytest.fixture(scope="module", autouse=True)
def schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    db = SessionLocal()
    try:
        for model in (WealthPlanEntry, WealthPlan, PortfolioHolding, PortfolioAsset, Person, User):
            db.query(model).delete()
        user = User(username="alice", email="alice@example.test", password_hash=hash_password("pw"))
        db.add(user)
        db.flush()
        person = Person(user_id=user.id, name="Alice")
        db.add(person)
        db.flush()
        asset = PortfolioAsset(user_id=user.id, name="Goud", symbol="XAU", asset_class="metal",
                               unit="oz", current_price_eur=Decimal("100"))
        db.add(asset)
        db.flush()
        db.add(PortfolioHolding(user_id=user.id, asset_id=asset.id, person_id=person.id,
                                quantity=Decimal("2")))
        db.commit()
        capture_wealth_plan(db, user.id, 2026, today=__import__("datetime").date(2026, 1, 1))
        db.commit()
        http = TestClient(app)
        http.cookies.set("session", create_session_cookie(user.id))
        yield http, person.id
    finally:
        db.close()


def test_wealth_forecast_page_renders_plan_and_person_filter(client):
    http, person_id = client
    response = http.get(f"/portfolio/wealth-forecast?year=2026&person={person_id}")
    assert response.status_code == 200
    assert "Vermogensprognose" in response.text
    assert "Plan per 1/1" in response.text
    assert "Alice" in response.text


def test_wealth_forecast_page_requires_login():
    response = TestClient(app).get("/portfolio/wealth-forecast", follow_redirects=False)
    assert response.status_code in (302, 303, 401)
