"""Tests voor scenario existing mortgages + compute_scenario_financials (LIN-44)."""
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
from app.mortgage_calc import compute_scenario_financials, existing_mortgage_monthly
from app.models import (
    MortgageScenario,
    ScenarioExistingMortgage,
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
        db.query(ScenarioExistingMortgage).delete()
        db.query(MortgageScenario).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_admin(db, username="admin"):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"), is_admin=1,
        can_access_mortgage=1,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ──────────────────────────────────────────────────────────────────────────────
# Helper unit tests
# ──────────────────────────────────────────────────────────────────────────────

def _build_scenario(**overrides):
    """Minimal stub — helper hoeft geen echte ORM-instance te hebben."""

    class _Stub:
        pass

    s = _Stub()
    s.valuation = Decimal("1275000")
    s.offer = Decimal("1275000")
    s.renovation_cost = Decimal("0")
    s.own_contribution = Decimal("0")
    s.sale_old_home = Decimal("680000")
    s.purchase_fee_pct = Decimal("2.5")
    s.sale_fee_pct = Decimal("1.5")
    s.existing_mortgages = []
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _existing(**kw):
    class _E:
        id = 1
        sort_order = 0
        monthly_payment_eur = None
    e = _E()
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_helper_user_story_with_two_existing():
    """135k Pim + 144k ABN IO, 680k verkoop, 1,275M bod, 1,275M taxatie."""
    s = _build_scenario(existing_mortgages=[
        _existing(name="Pim", balance_eur=Decimal("135000"),
                  mortgage_type="annuity",
                  rate_pct=Decimal("4.0"), months_remaining=300),
        _existing(name="ABN", balance_eur=Decimal("144000"),
                  mortgage_type="interest_only",
                  rate_pct=Decimal("3.5"), months_remaining=None),
    ])
    fin = compute_scenario_financials(s)

    assert fin.existing_total == Decimal("279000.00")
    assert fin.purchase_fee == Decimal("31875.00")
    assert fin.sale_fee == Decimal("10200.00")
    assert fin.overwaarde == Decimal("390800.00")  # 680k - 279k - 10200
    assert fin.te_financieren == Decimal("1306875.00")  # 1275k + 31875
    assert fin.nieuwe_annuiteit == Decimal("637075.00")
    # LTV = (279k + 637075) / 1275k = 71,85%
    assert fin.ltv_fraction == Decimal("0.7185")


def test_helper_pim_excluded_from_ltv_but_counts_in_financing():
    """Pim (privé) telt WEL mee in overwaarde-aftrek en nieuwe-annuïteit-
    dekking, maar NIET in de LTV-berekening. ABN (bank) telt wel overal mee."""
    s = _build_scenario(existing_mortgages=[
        _existing(name="Pim", balance_eur=Decimal("135000"),
                  mortgage_type="annuity",
                  rate_pct=Decimal("6.0"), months_remaining=300,
                  counts_in_ltv=0),
        _existing(name="ABN", balance_eur=Decimal("144000"),
                  mortgage_type="interest_only",
                  rate_pct=Decimal("1.76"), months_remaining=None,
                  counts_in_ltv=1),
    ])
    fin = compute_scenario_financials(s)

    # Overwaarde + nieuwe annuiteit: ongewijzigd (Pim trekt nog mee in aftrek)
    assert fin.existing_total == Decimal("279000.00")
    assert fin.overwaarde == Decimal("390800.00")
    assert fin.nieuwe_annuiteit == Decimal("637075.00")
    # LTV gebruikt alleen bank-hypotheken: (144k + 637075) / 1275k = 61,26%
    # Zonder de exclude zou dit 71,85% zijn — de privé-lening drukt m'n LTV
    # niet op.
    assert fin.ltv_fraction == Decimal("0.6126")


def test_helper_legacy_scenario_without_existing():
    """Scenario zonder bestaande hypotheken → existing_total=0, rest werkt."""
    s = _build_scenario()
    fin = compute_scenario_financials(s)

    assert fin.existing_total == Decimal("0.00")
    # overwaarde = 680k - 0 - 10200 = 669800
    assert fin.overwaarde == Decimal("669800.00")
    # nieuwe_annuiteit = 1306875 - 0 - 669800 - 0 = 637075
    assert fin.nieuwe_annuiteit == Decimal("637075.00")


def test_helper_clamps_new_annuity_to_zero():
    """Grote overwaarde + eigen inbreng → nieuwe annuiteit niet negatief."""
    s = _build_scenario(
        offer=Decimal("300000"),
        own_contribution=Decimal("250000"),
        existing_mortgages=[],
    )
    fin = compute_scenario_financials(s)
    # te_financieren = 300k + 0 + 7500 = 307500
    # overwaarde = 680k - 0 - 10200 = 669800
    # nieuwe_annuiteit = 307500 - 250000 - 669800 - 0 = -612300 → 0
    assert fin.nieuwe_annuiteit == Decimal("0.00")


def test_helper_zero_valuation_returns_zero_ltv():
    s = _build_scenario(valuation=Decimal("0"))
    fin = compute_scenario_financials(s)
    assert fin.ltv_fraction == Decimal("0")


def test_existing_mortgage_monthly_annuity():
    monthly = existing_mortgage_monthly(
        balance=Decimal("135000"),
        mortgage_type="annuity",
        rate_pct=Decimal("4.0"),
        months_remaining=300,
    )
    # 135k over 300 maanden bij 4% = ongeveer €712 per maand
    assert Decimal("700") < monthly < Decimal("730")


def test_existing_mortgage_monthly_interest_only():
    monthly = existing_mortgage_monthly(
        balance=Decimal("144000"),
        mortgage_type="interest_only",
        rate_pct=Decimal("3.5"),
        months_remaining=None,
    )
    # 144000 * 0.035 / 12 = 420
    assert monthly == Decimal("420.00")


def test_existing_mortgage_monthly_override():
    monthly = existing_mortgage_monthly(
        balance=Decimal("1"),  # zou 0 geven
        mortgage_type="annuity",
        rate_pct=None,
        months_remaining=None,
        override=Decimal("555.55"),
    )
    assert monthly == Decimal("555.55")


# ──────────────────────────────────────────────────────────────────────────────
# CRUD-route tests
# ──────────────────────────────────────────────────────────────────────────────

def _scenario_for(db, user, **extra):
    s = MortgageScenario(
        user_id=user.id,
        name="Test scenario",
        valuation=Decimal("1275000"),
        offer=Decimal("1275000"),
        renovation_cost=Decimal("0"),
        own_contribution=Decimal("0"),
        sale_old_home=Decimal("680000"),
        purchase_fee_pct=Decimal("2.5"),
        sale_fee_pct=Decimal("1.5"),
    )
    for k, v in extra.items():
        setattr(s, k, v)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_create_existing_mortgage_via_route(db_session):
    admin = _make_admin(db_session)
    scenario = _scenario_for(db_session, admin)

    resp = _client(admin.id).post(
        f"/hypotheek/scenarios/{scenario.id}/existing-mortgages",
        data={
            "name": "Pim",
            "balance_eur": "135000",
            "mortgage_type": "annuity",
            "rate_pct": "4.0",
            "months_remaining": "300",
        },
    )
    assert resp.status_code == 302

    ems = db_session.query(ScenarioExistingMortgage).filter(
        ScenarioExistingMortgage.scenario_id == scenario.id,
    ).all()
    assert len(ems) == 1
    em = ems[0]
    assert em.name == "Pim"
    assert em.balance_eur == Decimal("135000")
    assert em.mortgage_type == "annuity"
    assert em.months_remaining == 300


def test_edit_existing_mortgage_via_route(db_session):
    admin = _make_admin(db_session)
    scenario = _scenario_for(db_session, admin)
    em = ScenarioExistingMortgage(
        scenario_id=scenario.id, name="Pim",
        balance_eur=Decimal("135000"), mortgage_type="annuity",
    )
    db_session.add(em); db_session.commit(); db_session.refresh(em)

    resp = _client(admin.id).post(
        f"/hypotheek/scenarios/{scenario.id}/existing-mortgages/{em.id}/edit",
        data={
            "name": "Pim (gewijzigd)",
            "balance_eur": "120000",
            "mortgage_type": "interest_only",
            "rate_pct": "3.5",
        },
    )
    assert resp.status_code == 302

    db_session.refresh(em)
    assert em.name == "Pim (gewijzigd)"
    assert em.balance_eur == Decimal("120000")
    assert em.mortgage_type == "interest_only"


def test_delete_existing_mortgage_via_route(db_session):
    admin = _make_admin(db_session)
    scenario = _scenario_for(db_session, admin)
    em = ScenarioExistingMortgage(
        scenario_id=scenario.id, name="Pim",
        balance_eur=Decimal("135000"), mortgage_type="annuity",
    )
    db_session.add(em); db_session.commit()

    resp = _client(admin.id).post(
        f"/hypotheek/scenarios/{scenario.id}/existing-mortgages/{em.id}/delete",
    )
    assert resp.status_code == 302
    assert db_session.query(ScenarioExistingMortgage).count() == 0


def test_non_admin_cannot_manage_existing_mortgages(db_session):
    admin = _make_admin(db_session, "admin")
    scenario = _scenario_for(db_session, admin)
    viewer = User(
        username="bob", email="bob@x.nl",
        password_hash=hash_password("pw"), is_admin=0,
    )
    db_session.add(viewer); db_session.commit(); db_session.refresh(viewer)

    resp = _client(viewer.id).post(
        f"/hypotheek/scenarios/{scenario.id}/existing-mortgages",
        data={"name": "Pim", "balance_eur": "1"},
    )
    # Mortgage-module geeft 404 aan non-admins (bestaan niet onthullen)
    assert resp.status_code == 404


def test_cannot_edit_other_users_existing_mortgage(db_session):
    admin1 = _make_admin(db_session, "admin1")
    admin2 = _make_admin(db_session, "admin2")
    scenario = _scenario_for(db_session, admin1)
    em = ScenarioExistingMortgage(
        scenario_id=scenario.id, name="Pim",
        balance_eur=Decimal("135000"), mortgage_type="annuity",
    )
    db_session.add(em); db_session.commit(); db_session.refresh(em)

    resp = _client(admin2.id).post(
        f"/hypotheek/scenarios/{scenario.id}/existing-mortgages/{em.id}/edit",
        data={"name": "hacked", "balance_eur": "1"},
    )
    assert resp.status_code == 404

    db_session.refresh(em)
    assert em.name == "Pim"


def test_scenario_detail_renders_derived_values(db_session):
    admin = _make_admin(db_session)
    scenario = _scenario_for(db_session, admin)
    db_session.add_all([
        ScenarioExistingMortgage(
            scenario_id=scenario.id, name="Pim",
            balance_eur=Decimal("135000"), mortgage_type="annuity",
            rate_pct=Decimal("4.0"), months_remaining=300,
        ),
        ScenarioExistingMortgage(
            scenario_id=scenario.id, name="ABN",
            balance_eur=Decimal("144000"), mortgage_type="interest_only",
            rate_pct=Decimal("3.5"),
        ),
    ])
    db_session.commit()

    resp = _client(admin.id).get(f"/hypotheek/scenarios/{scenario.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Bestaande hypotheken" in body
    # Derived values zichtbaar
    assert "279" in body  # 279k total
    assert "637" in body  # nieuwe annuiteit
    # LTV netjes onder 90%
    assert "71,85" in body or "71.85" in body