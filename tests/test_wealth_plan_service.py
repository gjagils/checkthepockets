"""Acceptance tests for frozen yearly wealth plans (ACT-28b)."""
import datetime
import os
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Person, PortfolioAsset, PortfolioHolding, User, WealthPlan, WealthPlanEntry
from app.wealth_plan_service import (
    WealthPlanConfirmationRequired,
    capture_january_wealth_plans,
    capture_wealth_plan,
    get_wealth_plan_entries,
)


@pytest.fixture(scope="module", autouse=True)
def schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        for model in (WealthPlanEntry, WealthPlan, PortfolioHolding, PortfolioAsset, Person, User):
            session.query(model).delete()
        session.commit()
        yield session
    finally:
        session.close()


def setup_user_with_holding(db, username="alice"):
    user = User(username=username, email=f"{username}@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    person = Person(user_id=user.id, name=username.title())
    db.add(person)
    db.flush()
    asset = PortfolioAsset(user_id=user.id, name="Goud", symbol="XAU", asset_class="metal",
                           unit="oz", current_price_eur=Decimal("100"))
    db.add(asset)
    db.flush()
    db.add(PortfolioHolding(user_id=user.id, asset_id=asset.id, person_id=person.id,
                            quantity=Decimal("1")))
    db.commit()
    return user, person, asset


def test_frozen_plan_does_not_move_and_replacement_requires_confirmation(db):
    user, person, asset = setup_user_with_holding(db)
    day = datetime.date(2026, 1, 1)
    plan = capture_wealth_plan(db, user.id, 2026, today=day, automatic=True)
    db.commit()

    saved = get_wealth_plan_entries(db, user.id, 2026)
    assert len(saved) == 12
    assert saved[(person.id, 1)].portfolio_amount == Decimal("98.20")
    asset.current_price_eur = Decimal("200")
    db.commit()
    assert get_wealth_plan_entries(db, user.id, 2026)[(person.id, 1)].portfolio_amount == Decimal("98.20")

    with pytest.raises(WealthPlanConfirmationRequired):
        capture_wealth_plan(db, user.id, 2026, today=day)
    replaced = capture_wealth_plan(db, user.id, 2026, today=day, replace=True)
    db.commit()
    assert replaced.id == plan.id
    assert get_wealth_plan_entries(db, user.id, 2026)[(person.id, 1)].portfolio_amount == Decimal("196.40")


def test_january_capture_is_idempotent_and_only_runs_on_january_first(db):
    user, _, _ = setup_user_with_holding(db)
    assert capture_january_wealth_plans(db, today=datetime.date(2026, 2, 1)) == 0
    assert capture_january_wealth_plans(db, today=datetime.date(2026, 1, 1)) == 1
    assert capture_january_wealth_plans(db, today=datetime.date(2026, 1, 1)) == 0
    assert db.query(WealthPlan).filter(WealthPlan.user_id == user.id).count() == 1
