"""Acceptance tests for ACT-28a yearly wealth calculations."""
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
from app.models import (
    Account, Person, PortfolioAsset, PortfolioHolding, PortfolioPriceSnapshot,
    SavingsEntry, SavingsLine, SavingsPlan, Transaction, User,
)
from app.wealth_forecast import SELL_FACTOR, build_wealth_forecast


@pytest.fixture(scope="module", autouse=True)
def schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        for model in (Transaction, SavingsEntry, SavingsLine, SavingsPlan,
                      PortfolioPriceSnapshot, PortfolioHolding, PortfolioAsset,
                      Account, Person, User):
            session.query(model).delete()
        session.commit()
        yield session
    finally:
        session.close()


def make_user(session):
    user = User(username="alice", email="alice@example.test", password_hash=hash_password("pw"))
    session.add(user)
    session.commit()
    return user


def test_yearly_forecast_uses_snapshots_growth_sale_factor_and_owners(db):
    user = make_user(db)
    gerd = Person(user_id=user.id, name="Gerd")
    roos = Person(user_id=user.id, name="Roos")
    db.add_all([gerd, roos])
    db.flush()
    gold = PortfolioAsset(
        user_id=user.id, name="Goud", symbol="XAU", asset_class="metal", unit="oz",
        current_price_eur=Decimal("999"), monthly_growth_pct=Decimal("1"),
    )
    db.add(gold)
    db.flush()
    db.add_all([
        PortfolioHolding(user_id=user.id, asset_id=gold.id, person_id=gerd.id,
                         quantity=Decimal("2"), monthly_contribution_eur=Decimal("150")),
        PortfolioHolding(user_id=user.id, asset_id=gold.id, person_id=roos.id,
                         quantity=Decimal("1"), monthly_contribution_eur=Decimal("0")),
        PortfolioPriceSnapshot(asset_id=gold.id, year=2026, month=1, price_eur=Decimal("100")),
        PortfolioPriceSnapshot(asset_id=gold.id, year=2026, month=2, price_eur=Decimal("110")),
        PortfolioPriceSnapshot(asset_id=gold.id, year=2026, month=7, price_eur=Decimal("120")),
    ])
    account = Account(user_id=user.id, name="Kinderspaar", bank="bunq")
    account.owners = [gerd, roos]
    db.add(account)
    db.flush()
    plan = SavingsPlan(user_id=user.id, account_id=account.id, year=2026,
                       starting_balance=Decimal("1000"))
    db.add(plan)
    db.flush()
    line = SavingsLine(plan_id=plan.id, name="Inleg", frequency="monthly",
                       is_income=1, default_amount=Decimal("60"))
    db.add(line)
    db.flush()
    for month in range(1, 13):
        db.add(SavingsEntry(line_id=line.id, month=month, amount=Decimal("60")))
    # An actual imported balance overrides the plan for February's opening.
    db.add(Transaction(account_id=account.id, date=datetime.date(2026, 1, 20),
                       amount=Decimal("400"), balance_after=Decimal("1400"),
                       import_hash="opening-balance"))
    db.commit()

    result = build_wealth_forecast(db, user.id, 2026, today=datetime.date(2026, 7, 15))

    assert result["per_person"][gerd.id][1]["portfolio"] == Decimal("200") * SELL_FACTOR
    assert result["per_person"][gerd.id][2]["portfolio"] == Decimal("220") * SELL_FACTOR
    assert result["per_person"][gerd.id][2]["savings"] == Decimal("700")
    july = Decimal("240") * SELL_FACTOR
    assert result["per_person"][gerd.id][7]["portfolio"] == july
    assert result["per_person"][gerd.id][8]["portfolio"] == (july + Decimal("150")) * Decimal("1.01")
    assert result["per_person"][roos.id][1]["savings"] == Decimal("500")
    assert result["together"][1]["total"] == (
        result["per_person"][gerd.id][1]["total"] + result["per_person"][roos.id][1]["total"]
    )


def test_yearly_forecast_keeps_users_separate(db):
    first = make_user(db)
    second = User(username="bob", email="bob@example.test", password_hash=hash_password("pw"))
    db.add(second)
    db.flush()
    first_person = Person(user_id=first.id, name="Alice")
    second_person = Person(user_id=second.id, name="Bob")
    db.add_all([first_person, second_person])
    db.flush()
    asset = PortfolioAsset(user_id=second.id, name="Verborgen", symbol="X", asset_class="stock",
                           unit="stuk", current_price_eur=Decimal("100"))
    db.add(asset)
    db.flush()
    db.add(PortfolioHolding(user_id=second.id, asset_id=asset.id, person_id=second_person.id,
                            quantity=Decimal("10")))
    db.commit()

    result = build_wealth_forecast(db, first.id, 2026, today=datetime.date(2026, 1, 1))
    assert [person.name for person in result["persons"]] == ["Alice"]
    assert result["together"][1]["total"] == Decimal("0")
