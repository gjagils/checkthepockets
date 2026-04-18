"""Tests voor scenario CRUD + detailpagina (GJA-28)."""
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
    HouseholdFinance,
    MortgageRateTable,
    MortgageScenario,
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
        db.query(MortgageVariant).delete()
        db.query(MortgageScenario).delete()
        db.query(MortgageRateTable).delete()
        db.query(HouseholdFinance).delete()
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
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def _seed_rates(db, user_id):
    rates = [
        (5, Decimal("0.85"), Decimal("0.0344")),
        (5, Decimal("1.00"), Decimal("0.0360")),
        (10, Decimal("0.85"), Decimal("0.0375")),
        (10, Decimal("1.00"), Decimal("0.0395")),
        (15, Decimal("0.85"), Decimal("0.0400")),
        (20, Decimal("0.85"), Decimal("0.0425")),
    ]
    for years, ltv, rate in rates:
        db.add(MortgageRateTable(
            user_id=user_id, fixed_years=years, ltv_max_pct=ltv, interest_rate=rate,
        ))
    db.commit()


def test_list_non_admin_404(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    assert _client(user.id).get("/hypotheek/scenarios").status_code == 404


def test_new_form_renders(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).get("/hypotheek/scenarios/nieuw")
    assert resp.status_code == 200
    assert "Nieuw scenario" in resp.text


def test_create_scenario(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).post(
        "/hypotheek/scenarios",
        data={
            "name": "Kerkstraat 12",
            "valuation": "500000",
            "offer": "485000",
            "renovation_cost": "15000",
            "own_contribution": "50000",
            "sale_old_home": "350000",
            "energy_label": "B",
            "notes": "Hoekhuis, tuin op zuid.",
        },
    )
    assert resp.status_code == 302
    assert "/hypotheek/scenarios/" in resp.headers["location"]

    db_session.expire_all()
    scenarios = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).all()
    assert len(scenarios) == 1
    s = scenarios[0]
    assert s.name == "Kerkstraat 12"
    assert s.valuation == Decimal("500000")
    assert s.offer == Decimal("485000")
    assert s.energy_label == "B"
    assert s.is_archived == 0


def test_edit_scenario(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/scenarios", data={
        "name": "Oud",
        "valuation": "400000", "offer": "400000", "renovation_cost": "0",
        "own_contribution": "0", "sale_old_home": "0", "energy_label": "A",
    })
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.post(f"/hypotheek/scenarios/{s.id}/edit", data={
        "name": "Nieuw",
        "valuation": "450000", "offer": "445000", "renovation_cost": "5000",
        "own_contribution": "25000", "sale_old_home": "300000",
        "energy_label": "C", "notes": "Verbouwd",
    })
    assert resp.status_code == 302
    assert f"/hypotheek/scenarios/{s.id}" in resp.headers["location"]

    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(MortgageScenario.id == s.id).one()
    assert s.name == "Nieuw"
    assert s.valuation == Decimal("450000")
    assert s.energy_label == "C"


def test_archive_and_unarchive(db_session):
    admin = _make_user(db_session)
    client = _client(admin.id)
    client.post("/hypotheek/scenarios", data={
        "name": "Beukenlaan 7", "valuation": "400000", "offer": "400000",
        "renovation_cost": "0", "own_contribution": "0",
        "sale_old_home": "0", "energy_label": "A",
    })
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    client.post(f"/hypotheek/scenarios/{s.id}/delete")
    db_session.expire_all()
    assert db_session.query(MortgageScenario).filter(
        MortgageScenario.id == s.id,
    ).one().is_archived == 1

    # List zonder archived: naam niet zichtbaar.
    resp = client.get("/hypotheek/scenarios")
    assert "Beukenlaan 7" not in resp.text
    # Met archived=1 weer wel.
    resp = client.get("/hypotheek/scenarios?show_archived=1")
    assert "Beukenlaan 7" in resp.text

    client.post(f"/hypotheek/scenarios/{s.id}/unarchive")
    db_session.expire_all()
    assert db_session.query(MortgageScenario).filter(
        MortgageScenario.id == s.id,
    ).one().is_archived == 0


def test_cannot_edit_other_users_scenario(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    bob_scenario = MortgageScenario(user_id=bob.id, name="Bob's", valuation=Decimal("1"))
    db_session.add(bob_scenario)
    db_session.commit()
    db_session.refresh(bob_scenario)

    resp = _client(alice.id).post(
        f"/hypotheek/scenarios/{bob_scenario.id}/edit",
        data={
            "name": "Gehacked", "valuation": "1", "offer": "1",
            "renovation_cost": "0", "own_contribution": "0",
            "sale_old_home": "0", "energy_label": "A",
        },
    )
    assert resp.status_code == 404


def test_detail_shows_calculations(db_session):
    admin = _make_user(db_session)
    _seed_rates(db_session, admin.id)
    # Household met realistische defaults (seed bij eerste GET).
    _client(admin.id).get("/hypotheek/huishouden")

    client = _client(admin.id)
    client.post("/hypotheek/scenarios", data={
        "name": "Testhuis", "valuation": "500000", "offer": "485000",
        "renovation_cost": "15000", "own_contribution": "50000",
        "sale_old_home": "0", "energy_label": "B",
    })
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    # Te financieren = 485 + 15 + 2.5%*485 = 500 + 12.125 − 50 = 462.125
    assert "462.125" in resp.text
    # LTV 462.125 / 500 = 92.4% → valt in 100%-bucket @ 3.60% voor 5j.
    assert "5j rentevast" in resp.text
    assert "3,60" in resp.text or "3.60" in resp.text


def test_detail_shows_missing_rate_warning(db_session):
    admin = _make_user(db_session)
    # Geen rates gezet → melding moet tonen.
    _client(admin.id).get("/hypotheek/huishouden")
    client = _client(admin.id)
    client.post("/hypotheek/scenarios", data={
        "name": "Testhuis", "valuation": "500000", "offer": "485000",
        "renovation_cost": "0", "own_contribution": "0",
        "sale_old_home": "0", "energy_label": "B",
    })
    db_session.expire_all()
    s = db_session.query(MortgageScenario).filter(
        MortgageScenario.user_id == admin.id,
    ).one()

    resp = client.get(f"/hypotheek/scenarios/{s.id}")
    assert resp.status_code == 200
    assert "Geen rente gevonden" in resp.text
    assert "/hypotheek/rentes" in resp.text


def test_submenu_scenarios_link_visible_for_admin(db_session):
    admin = _make_user(db_session)
    body = _client(admin.id).get("/hypotheek").text
    assert "/hypotheek/scenarios" in body
