"""Tests voor scripts/seed_demo_user.py (LIN-46)."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

# Vóór de app-imports: tijdelijke sqlite-DB en dummy-secret.
_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from app.auth import verify_password
from app.database import Base, SessionLocal, engine
from app.models import (
    Account,
    Budget,
    Category,
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageVariant,
    Person,
    ScenarioExistingMortgage,
    ScenarioPersonContribution,
    Transaction,
    User,
)
from scripts.seed_demo_user import (
    CATEGORIES,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    INBOX_TX,
    MONTHLY_TX,
    RATE_TABLE,
    seed_demo_user,
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
        # Volledige reset van alle tabellen die de seed kan raken.
        db.query(ScenarioPersonContribution).delete()
        db.query(ScenarioExistingMortgage).delete()
        db.query(MortgageVariant).delete()
        db.query(MortgageScenario).delete()
        db.query(MortgageRateTable).delete()
        db.query(HouseholdFinance).delete()
        db.query(Budget).delete()
        db.query(Transaction).delete()
        db.query(Category).delete()
        for acc in db.query(Account).all():
            acc.owners = []
        db.commit()
        db.query(Account).delete()
        db.query(Person).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


# ── Smoke-test: één run produceert het verwachte volume ──────────────────


def test_seed_creates_demo_user_with_expected_volume(db_session):
    today = date(2026, 6, 15)  # vaste "vandaag" voor deterministische tellingen

    user = seed_demo_user(today=today, db=db_session)

    # User-basics
    assert user.username == DEFAULT_USERNAME
    assert user.is_admin == 1
    assert user.is_verified == 1
    assert verify_password(DEFAULT_PASSWORD, user.password_hash)

    # Profile + persons
    persons = db_session.query(Person).filter_by(user_id=user.id).order_by(Person.sort_order).all()
    assert [p.name for p in persons] == ["Demo Alex", "Demo Sam"]

    hf = db_session.query(HouseholdFinance).filter_by(user_id=user.id).one()
    assert hf.salary_primary == Decimal("3520.00")
    assert hf.salary_primary_name == "Demo Alex"
    assert hf.tax_rate == Decimal("0.3697")

    # Accounts + owners
    accounts = db_session.query(Account).filter_by(user_id=user.id).all()
    assert len(accounts) == 3
    by_name = {a.name: a for a in accounts}
    assert set(by_name) == {
        "Betaalrekening Alex", "Spaarrekening", "Gezamenlijke rekening",
    }
    assert {p.name for p in by_name["Gezamenlijke rekening"].owners} == {"Demo Alex", "Demo Sam"}
    assert {p.name for p in by_name["Betaalrekening Alex"].owners} == {"Demo Alex"}

    # Categories incl. cost_scale_type markering
    cats = db_session.query(Category).filter_by(user_id=user.id).all()
    assert len(cats) == len(CATEGORIES)
    by_cat = {c.name: c for c in cats}
    assert by_cat["Wonen"].cost_scale_type == "mortgage"
    assert by_cat["Verzekeringen"].cost_scale_type == "insurance"
    assert by_cat["Gemeente & heffingen"].cost_scale_type == "municipal"
    assert by_cat["Salaris"].is_income == 1

    # Transactions: 12 maanden × MONTHLY_TX, beperkt tot ≤ today; + INBOX_TX
    txs = db_session.query(Transaction).join(Account).filter(Account.user_id == user.id).all()
    inbox_count = sum(1 for t in txs if t.category_id is None)
    assert inbox_count == len(INBOX_TX)

    # Voor today=2026-06-15 horen alle MONTHLY_TX in mei + eerdere maanden mee;
    # in juni vallen items met day > 15 weg. We tellen flexibel: minstens
    # 11 volle maanden + 1 partial. Exact: count_full * MONTHLY + count_partial.
    categorised = [t for t in txs if t.category_id is not None]
    # Minstens 11 volle maanden:
    assert len(categorised) >= 11 * len(MONTHLY_TX)
    # En zeker minder dan 12 volle (juni is niet compleet):
    assert len(categorised) < 12 * len(MONTHLY_TX)

    # Budgetten: 12 maanden × elke categorie met monthly_budget
    budget_specs = [s for s in CATEGORIES if s.monthly_budget is not None]
    budgets = db_session.query(Budget).filter_by(user_id=user.id).all()
    assert len(budgets) == 12 * len(budget_specs)

    # Mortgage scenario + child-rijen
    scenario = db_session.query(MortgageScenario).filter_by(user_id=user.id).one()
    assert scenario.name == "Droomhuis Vechtstraat"
    assert scenario.monthly_refund_usage == Decimal("250.00")
    assert scenario.woz_value == Decimal("452000.00")

    variants = db_session.query(MortgageVariant).filter_by(scenario_id=scenario.id).all()
    assert sorted(v.fixed_years for v in variants) == [5, 10, 20]

    existing = (
        db_session.query(ScenarioExistingMortgage)
        .filter_by(scenario_id=scenario.id).order_by(ScenarioExistingMortgage.sort_order).all()
    )
    assert [e.mortgage_type for e in existing] == ["annuity", "interest_only"]
    assert existing[1].hra_end_date == date(2031, 12, 31)

    contribs = db_session.query(ScenarioPersonContribution).filter_by(scenario_id=scenario.id).all()
    assert len(contribs) == 2
    assert sum(c.monthly_contribution_eur for c in contribs) == Decimal("3300.00")

    # Rente-tabel
    rates = db_session.query(MortgageRateTable).filter_by(user_id=user.id).all()
    assert len(rates) == len(RATE_TABLE)


# ── Idempotentie: tweede run wist + heraanmaakt zonder fouten ────────────


def test_seed_is_idempotent(db_session):
    today = date(2026, 6, 15)

    first = seed_demo_user(today=today, db=db_session)
    first_volume = (
        db_session.query(Transaction).count(),
        db_session.query(Budget).count(),
        db_session.query(MortgageRateTable).count(),
    )

    second = seed_demo_user(today=today, db=db_session)
    assert second.username == DEFAULT_USERNAME

    # Exact één user met die naam (oude is gewist, niet bewaard).
    assert db_session.query(User).filter_by(username=DEFAULT_USERNAME).count() == 1
    # Exact één scenario en één household — geen dubbele records.
    assert db_session.query(MortgageScenario).filter_by(user_id=second.id).count() == 1
    assert db_session.query(HouseholdFinance).filter_by(user_id=second.id).count() == 1
    # Totale volumes identiek aan eerste run (geen accumulatie).
    second_volume = (
        db_session.query(Transaction).count(),
        db_session.query(Budget).count(),
        db_session.query(MortgageRateTable).count(),
    )
    assert first_volume == second_volume


# ── Naast-elkaar bestaan met andere users mag niet kapot gaan ────────────


def test_seed_does_not_touch_other_users(db_session):
    from app.auth import hash_password

    other = User(
        username="alice", email="alice@x.nl",
        password_hash=hash_password("pw"), is_verified=1,
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    other_id = other.id  # vasthouden — seed kan instance detachen

    other_acc = Account(user_id=other_id, name="Alice main", bank="custom", iban="NL99TEST0000000001")
    db_session.add(other_acc)
    db_session.commit()
    other_acc_id = other_acc.id

    seed_demo_user(today=date(2026, 6, 15), db=db_session)

    # Alice + haar account zijn ongemoeid
    assert db_session.query(User).filter_by(id=other_id).count() == 1
    assert db_session.query(Account).filter_by(id=other_acc_id).count() == 1


# ── Custom credentials via parameter ─────────────────────────────────────


def test_seed_accepts_custom_credentials(db_session):
    user = seed_demo_user(
        username="acme-demo",
        password="hunter2hunter2",
        email="acme@example.org",
        today=date(2026, 6, 15),
        db=db_session,
    )
    assert user.username == "acme-demo"
    assert user.email == "acme@example.org"
    assert verify_password("hunter2hunter2", user.password_hash)
