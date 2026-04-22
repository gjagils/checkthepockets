"""Tests voor factor-engine, hypotheek-som en person contributions (LIN-45)."""
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
from app.mortgage_calc import (
    build_scenario_budget_rows,
    compute_scenario_coverage,
)
from app.models import (
    Budget,
    Category,
    MortgageScenario,
    MortgageScenarioBudget,
    Person,
    ScenarioPersonContribution,
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
        db.query(ScenarioPersonContribution).delete()
        db.query(MortgageScenarioBudget).delete()
        db.query(MortgageScenario).delete()
        db.query(Budget).delete()
        db.query(Category).delete()
        db.query(Person).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _admin(db, username="admin"):
    u = User(username=username, email=f"{username}@x.nl",
            password_hash=hash_password("pw"), is_admin=1)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ──────────────────────────────────────────────────────────────────────────────
# build_scenario_budget_rows
# ──────────────────────────────────────────────────────────────────────────────

class _Scenario:
    municipal_cost_factor = Decimal("1.5")
    insurance_cost_factor = Decimal("1.5")


def _cat(id, name, cost_scale_type=None):
    c = type("C", (), {})()
    c.id = id; c.name = name; c.cost_scale_type = cost_scale_type
    return c


def _budget(cat, amount):
    b = type("B", (), {})()
    b.category = cat; b.category_id = cat.id; b.amount = Decimal(str(amount))
    return b


def _override(cat_id, amount, source="manual"):
    o = type("O", (), {})()
    o.category_id = cat_id; o.amount = Decimal(str(amount)); o.source = source
    return o


def test_factor_applied_to_municipal_category():
    cats = [_cat(1, "Gemeentelijke heffingen", "municipal")]
    budgets = [_budget(cats[0], 200)]
    rows, total = build_scenario_budget_rows(
        scenario=_Scenario(), budgets=budgets, overrides_by_cat={},
        existing_monthly_total=Decimal("0"),
        new_annuity_monthly=Decimal("0"),
    )
    assert len(rows) == 1
    assert rows[0].effective_amount == Decimal("300.00")  # 200 * 1.5
    assert rows[0].source == "auto"


def test_factor_applied_to_insurance_category():
    cats = [_cat(1, "Opstalverzekering", "insurance")]
    budgets = [_budget(cats[0], 100)]
    rows, _ = build_scenario_budget_rows(
        scenario=_Scenario(), budgets=budgets, overrides_by_cat={},
        existing_monthly_total=Decimal("0"),
        new_annuity_monthly=Decimal("0"),
    )
    assert rows[0].effective_amount == Decimal("150.00")


def test_manual_override_wins_over_auto_factor():
    cats = [_cat(5, "Gemeentelijk", "municipal")]
    budgets = [_budget(cats[0], 200)]
    overrides = {5: _override(5, 250, source="manual")}

    rows, _ = build_scenario_budget_rows(
        scenario=_Scenario(), budgets=budgets, overrides_by_cat=overrides,
        existing_monthly_total=Decimal("0"),
        new_annuity_monthly=Decimal("0"),
    )
    assert rows[0].effective_amount == Decimal("250.00")
    assert rows[0].source == "manual"


def test_mortgage_category_sum_is_existing_plus_new():
    cats = [_cat(7, "Hypotheek", "mortgage")]
    budgets = [_budget(cats[0], 1500)]

    rows, total = build_scenario_budget_rows(
        scenario=_Scenario(), budgets=budgets, overrides_by_cat={},
        existing_monthly_total=Decimal("1132.58"),
        new_annuity_monthly=Decimal("3200"),
    )
    assert rows[0].effective_amount == Decimal("4332.58")
    assert rows[0].source == "auto"
    # Huidige waarde blijft naast ter vergelijking
    assert rows[0].current_amount == Decimal("1500.00")


def test_neutral_category_unchanged_without_override():
    cats = [_cat(3, "Boodschappen")]
    budgets = [_budget(cats[0], 800)]

    rows, _ = build_scenario_budget_rows(
        scenario=_Scenario(), budgets=budgets, overrides_by_cat={},
        existing_monthly_total=Decimal("0"),
        new_annuity_monthly=Decimal("0"),
    )
    assert rows[0].effective_amount == Decimal("800.00")
    assert rows[0].scenario_amount is None
    assert rows[0].source == "none"


# ──────────────────────────────────────────────────────────────────────────────
# Coverage
# ──────────────────────────────────────────────────────────────────────────────

def test_coverage_positive_when_contributions_exceed_load():
    cov = compute_scenario_coverage(Decimal("4000"), [Decimal("2500"), Decimal("2000")])
    assert cov.covered is True
    assert cov.difference == Decimal("500.00")


def test_coverage_negative_when_contributions_below_load():
    cov = compute_scenario_coverage(Decimal("5000"), [Decimal("2500"), Decimal("2000")])
    assert cov.covered is False
    assert cov.difference == Decimal("-500.00")


def test_coverage_handles_empty_contributions():
    cov = compute_scenario_coverage(Decimal("1000"), [])
    assert cov.contributions_total == Decimal("0.00")
    assert cov.covered is False


# ──────────────────────────────────────────────────────────────────────────────
# Contribution-route
# ──────────────────────────────────────────────────────────────────────────────

def _make_scenario(db, admin):
    s = MortgageScenario(
        user_id=admin.id, name="Test",
        valuation=Decimal("1275000"), offer=Decimal("1275000"),
        sale_old_home=Decimal("680000"),
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_contribution_upsert_creates_new(db_session):
    admin = _admin(db_session)
    scenario = _make_scenario(db_session, admin)
    nelleke = Person(user_id=admin.id, name="Nelleke")
    db_session.add(nelleke); db_session.commit(); db_session.refresh(nelleke)

    resp = _client(admin.id).post(
        f"/hypotheek/scenarios/{scenario.id}/contributions",
        data={"person_id": str(nelleke.id), "amount": "2500"},
    )
    assert resp.status_code == 302

    row = db_session.query(ScenarioPersonContribution).one()
    assert row.person_id == nelleke.id
    assert row.monthly_contribution_eur == Decimal("2500")


def test_contribution_upsert_updates_existing(db_session):
    admin = _admin(db_session)
    scenario = _make_scenario(db_session, admin)
    p = Person(user_id=admin.id, name="GJ")
    db_session.add(p); db_session.commit(); db_session.refresh(p)

    db_session.add(ScenarioPersonContribution(
        scenario_id=scenario.id, person_id=p.id,
        monthly_contribution_eur=Decimal("1000"),
    ))
    db_session.commit()

    resp = _client(admin.id).post(
        f"/hypotheek/scenarios/{scenario.id}/contributions",
        data={"person_id": str(p.id), "amount": "2750"},
    )
    assert resp.status_code == 302
    row = db_session.query(ScenarioPersonContribution).one()
    assert row.monthly_contribution_eur == Decimal("2750")


def test_contribution_requires_admin(db_session):
    admin = _admin(db_session, "admin")
    scenario = _make_scenario(db_session, admin)
    viewer = User(
        username="viewer", email="v@x.nl",
        password_hash=hash_password("pw"), is_admin=0,
    )
    db_session.add(viewer); db_session.commit(); db_session.refresh(viewer)

    resp = _client(viewer.id).post(
        f"/hypotheek/scenarios/{scenario.id}/contributions",
        data={"person_id": "1", "amount": "1"},
    )
    assert resp.status_code == 404


def test_contribution_rejects_other_users_person(db_session):
    admin1 = _admin(db_session, "admin1")
    admin2 = _admin(db_session, "admin2")
    scenario = _make_scenario(db_session, admin1)
    p2 = Person(user_id=admin2.id, name="Vreemd")
    db_session.add(p2); db_session.commit(); db_session.refresh(p2)

    resp = _client(admin1.id).post(
        f"/hypotheek/scenarios/{scenario.id}/contributions",
        data={"person_id": str(p2.id), "amount": "1"},
    )
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Category cost_scale_type dropdown
# ──────────────────────────────────────────────────────────────────────────────

def test_category_edit_sets_cost_scale_type(db_session):
    admin = _admin(db_session)
    cat = Category(user_id=admin.id, name="Hypotheek")
    db_session.add(cat); db_session.commit(); db_session.refresh(cat)

    resp = _client(admin.id).post(
        f"/categories/{cat.id}/edit",
        data={"name": "Hypotheek", "cost_scale_type": "mortgage"},
    )
    assert resp.status_code == 302

    db_session.refresh(cat)
    assert cat.cost_scale_type == "mortgage"


def test_category_edit_ignores_invalid_cost_scale_type(db_session):
    admin = _admin(db_session)
    cat = Category(user_id=admin.id, name="Eten", cost_scale_type="mortgage")
    db_session.add(cat); db_session.commit(); db_session.refresh(cat)

    resp = _client(admin.id).post(
        f"/categories/{cat.id}/edit",
        data={"name": "Eten", "cost_scale_type": "nonsense"},
    )
    assert resp.status_code == 302
    db_session.refresh(cat)
    # Ongeldige waarde → terug naar NULL
    assert cat.cost_scale_type is None
