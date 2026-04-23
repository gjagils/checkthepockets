"""Tests voor variant-vergelijker + budget-impact (GJA-29)."""
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
    Budget,
    Category,
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
    MortgageScenarioBudget,
    MortgageVariant,
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
        db.query(MortgageScenarioBudget).delete()
        db.query(MortgageVariant).delete()
        db.query(MortgageScenario).delete()
        db.query(MortgageRateTable).delete()
        db.query(HouseholdFinance).delete()
        db.query(Budget).delete()
        db.query(Category).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="admin", is_admin=1):
    u = User(
        username=username,
        email=f"{username}@x.nl",
        password_hash=hash_password("pw"),
        is_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


def _seed_rates(db, user_id, years=(5, 10, 20)):
    for fy in years:
        db.add(MortgageRateTable(
            user_id=user_id, fixed_years=fy,
            ltv_max_pct=Decimal("1.00"),
            interest_rate=Decimal("0.04"),
        ))
    db.commit()


def _create_scenario(client, name="H") -> int:
    client.post("/hypotheek/scenarios", data={
        "name": name, "valuation": "500000", "offer": "485000",
        "renovation_cost": "0", "own_contribution": "100000",
        "sale_old_home": "0", "energy_label": "A",
    })


def test_auto_create_default_variants(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5, 10, 20))
    _client(admin.id).get("/hypotheek/huishouden")  # seed household

    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()
    variants = db_session.query(MortgageVariant).filter(
        MortgageVariant.scenario_id == s.id,
    ).all()
    fixed = sorted(v.fixed_years for v in variants)
    assert fixed == [5, 10, 20]


def test_default_variants_created_without_rate_table(db_session):
    admin = _make_user(db_session)
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()
    fixed = sorted(
        v.fixed_years for v in db_session.query(MortgageVariant).filter(
            MortgageVariant.scenario_id == s.id,
        ).all()
    )
    assert fixed == [5, 10, 20]


def test_add_variant_with_override(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5,))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    # fixed_years=15 is niet in de defaults (5/10/20), dus dit is een nieuwe variant.
    resp = client.post(f"/hypotheek/scenarios/{s.id}/variants", data={
        "fixed_years": "15", "interest_rate_override": "3,99",
    })
    assert resp.status_code == 302
    assert "flash=variant_added" in resp.headers["location"]

    db_session.expire_all()
    v15 = db_session.query(MortgageVariant).filter(
        MortgageVariant.scenario_id == s.id, MortgageVariant.fixed_years == 15,
    ).one()
    assert v15.interest_rate_override == Decimal("0.0399")


def test_add_duplicate_variant_rejected(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5,))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.post(f"/hypotheek/scenarios/{s.id}/variants", data={"fixed_years": "5"})
    assert "flash=variant_duplicate" in resp.headers["location"]


def test_delete_variant(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5, 10))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()
    v = db_session.query(MortgageVariant).filter(
        MortgageVariant.scenario_id == s.id, MortgageVariant.fixed_years == 10,
    ).one()
    variant_id = v.id

    resp = client.post(f"/hypotheek/scenarios/{s.id}/variants/{variant_id}/delete")
    assert resp.status_code == 302
    db_session.expire_all()
    assert db_session.query(MortgageVariant).filter(
        MortgageVariant.id == variant_id,
    ).count() == 0


def test_comparison_table_renders_for_all_variants(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5, 10, 20))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Vergelijking" in body
    for label in ("5j", "10j", "20j"):
        assert label in body
    # Kosten / Inkomsten / Resultaat structuur
    assert "Nieuwe hypotheek" in body
    assert "Bestaande hypotheeklasten die meegaan" in body
    assert "Totaal kosten" in body
    assert "Teruggaaf per maand" in body
    assert "Totaal inkomsten" in body
    assert "Resultaat" in body
    assert "Restant voor spaarrekening" in body


def test_refund_usage_splits_into_savings(db_session):
    """Als monthly_refund_usage wordt gezet, valt het restant van de jaarlijkse
    belastingteruggaaf vrij als spaarbedrag en daalt de netto maandlast niet
    verder dan dat bedrag."""
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5,))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    # Zonder setting: annual_savings = 0 (oude gedrag, alles naar maandlast).
    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    assert "Spaarbedrag / jaar" in resp.text

    # Zet een laag gebruik (€50/mnd = €600/jaar). Dat is minder dan de
    # daadwerkelijke refund dus er ontstaat positief spaarbedrag.
    resp = client.post(f"/hypotheek/scenarios/{s.id}/edit", data={
        "name": s.name, "valuation": "500000", "offer": "485000",
        "renovation_cost": "0", "own_contribution": "100000",
        "sale_old_home": "0", "energy_label": "A",
        "monthly_refund_usage": "50",
    })
    assert resp.status_code == 302
    db_session.expire_all()
    updated = db_session.query(MortgageScenario).filter(
        MortgageScenario.id == s.id,
    ).one()
    assert updated.monthly_refund_usage == Decimal("50.00")

    # Leeg terugzetten → NULL (oude gedrag).
    resp = client.post(f"/hypotheek/scenarios/{s.id}/edit", data={
        "name": s.name, "valuation": "500000", "offer": "485000",
        "renovation_cost": "0", "own_contribution": "100000",
        "sale_old_home": "0", "energy_label": "A",
        "monthly_refund_usage": "",
    })
    db_session.expire_all()
    reset = db_session.query(MortgageScenario).filter(
        MortgageScenario.id == s.id,
    ).one()
    assert reset.monthly_refund_usage is None


def test_budget_impact_uses_most_recent_month(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5,))
    _client(admin.id).get("/hypotheek/huishouden")

    # 2 categorieën + budget voor 2026-04.
    cat1 = Category(user_id=admin.id, name="Boodschappen")
    cat2 = Category(user_id=admin.id, name="Zorg")
    db_session.add_all([cat1, cat2])
    db_session.commit()
    db_session.refresh(cat1); db_session.refresh(cat2)
    db_session.add_all([
        Budget(user_id=admin.id, category_id=cat1.id, year=2026, month=4, amount=Decimal("500")),
        Budget(user_id=admin.id, category_id=cat2.id, year=2026, month=4, amount=Decimal("150")),
    ])
    db_session.commit()

    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Maandbudget bij dit scenario" in body
    assert "Boodschappen" in body
    assert "Zorg" in body
    assert "2026-04" in body


def test_scenario_budget_override_replaces_current(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(5,))
    _client(admin.id).get("/hypotheek/huishouden")
    cat = Category(user_id=admin.id, name="Energie")
    db_session.add(cat); db_session.commit(); db_session.refresh(cat)
    db_session.add(Budget(
        user_id=admin.id, category_id=cat.id, year=2026, month=4, amount=Decimal("200"),
    ))
    db_session.commit()

    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    # Override: 250 ipv 200.
    resp = client.post(f"/hypotheek/scenarios/{s.id}/budgets", data={
        "category_id": str(cat.id), "amount": "250,00",
    })
    assert resp.status_code == 302
    assert "flash=budget_saved" in resp.headers["location"]

    db_session.expire_all()
    ov = db_session.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == s.id,
    ).one()
    assert ov.amount == Decimal("250.00")

    # Update override zelfde categorie → upsert ipv duplicate.
    client.post(f"/hypotheek/scenarios/{s.id}/budgets", data={
        "category_id": str(cat.id), "amount": "275,00",
    })
    db_session.expire_all()
    assert db_session.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == s.id,
    ).count() == 1
    ov = db_session.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == s.id,
    ).one()
    assert ov.amount == Decimal("275.00")

    # Reset → override weg.
    resp = client.post(f"/hypotheek/scenarios/{s.id}/budgets/reset", data={
        "category_id": str(cat.id),
    })
    assert resp.status_code == 302
    db_session.expire_all()
    assert db_session.query(MortgageScenarioBudget).filter(
        MortgageScenarioBudget.scenario_id == s.id,
    ).count() == 0


def test_cannot_override_other_users_category(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    bob_cat = Category(user_id=bob.id, name="Bob's categorie")
    db_session.add(bob_cat); db_session.commit(); db_session.refresh(bob_cat)

    alice_scenario = MortgageScenario(
        user_id=alice.id, name="X", valuation=Decimal("1"),
    )
    db_session.add(alice_scenario)
    db_session.commit()
    db_session.refresh(alice_scenario)

    resp = _client(alice.id).post(
        f"/hypotheek/scenarios/{alice_scenario.id}/budgets",
        data={"category_id": str(bob_cat.id), "amount": "100"},
    )
    assert resp.status_code == 404


def test_chart_data_present_in_response(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id, years=(10,))
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    _create_scenario(client)
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    # Chart.js CDN geladen + 10j reeks in JSON.
    assert "chart.js" in resp.text.lower()
    assert "10j rentevast" in resp.text


def test_variant_with_missing_rate_shown_as_dash(db_session):
    admin = _make_user(db_session)
    # LTV 95% maar alleen 85%-bucket → geen rate match voor 10j.
    db_session.add(MortgageRateTable(
        user_id=admin.id, fixed_years=10,
        ltv_max_pct=Decimal("0.85"), interest_rate=Decimal("0.0375"),
    ))
    db_session.commit()
    _client(admin.id).get("/hypotheek/huishouden")

    client = _client(admin.id)
    # Scenario met hoge LTV: offer 485k op valuation 500k + zonder eigen inbreng.
    client.post("/hypotheek/scenarios", data={
        "name": "HighLTV", "valuation": "500000", "offer": "485000",
        "renovation_cost": "0", "own_contribution": "0",
        "sale_old_home": "0", "energy_label": "A",
    })
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    # 10j-variant is er maar rate is None → em-dash in de Varianten tabel.
    assert "10j" in resp.text
