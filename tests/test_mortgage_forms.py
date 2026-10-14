"""ACT-46: scenarioformulier als dependency en één renderfunctie voor de rentepagina."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import MortgageScenario, User
from app.routers.mortgage import ScenarioForm, scenario_form


def _client(db):
    user = User(username="hyp-user", password_hash=hash_password("x" * 10), can_access_mortgage=1)
    db.add(user)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client, user


def test_scenario_form_dependency_collects_all_nineteen_fields():
    form = scenario_form(
        name="Huis", valuation="500.000", offer="475000", renovation_cost="10000", own_contribution="25000",
        sale_old_home="300000", energy_label="b", notes="n", funda_url="u", photo_url="p", purchase_fee_pct="2,5",
        sale_fee_pct="1,5", municipal_cost_factor="1,5", insurance_cost_factor="1,5", monthly_refund_usage="",
        woz_value="480000", transfer_date_new="2026-06-01", sale_date_old="2026-07-01", bridge_amount_override="",
    )
    assert isinstance(form, ScenarioForm) and form.name == "Huis" and form.energy_label == "b"
    assert len(form.__dataclass_fields__) == 19
    assert ScenarioForm().energy_label == "A"


def test_create_and_edit_a_scenario_through_the_shared_form(db):
    client, user = _client(db)
    created = client.post("/hypotheek/scenarios", data={
        "name": "Nieuw huis", "valuation": "450000", "offer": "440000", "energy_label": "c",
        "woz_value": "430000", "purchase_fee_pct": "3",
    })
    assert created.status_code == 302 and "flash=created" in created.headers["location"]
    scenario = db.query(MortgageScenario).one()
    assert (scenario.name, scenario.offer, scenario.energy_label) == ("Nieuw huis", Decimal("440000"), "C")
    assert scenario.woz_value == Decimal("430000") and scenario.purchase_fee_pct == Decimal("3")
    assert scenario.sale_fee_pct == Decimal("1.5")                    # leeg veld: standaardwaarde

    edited = client.post(f"/hypotheek/scenarios/{scenario.id}/edit", data={
        "name": "Hernoemd", "offer": "420000", "woz_value": "", "energy_label": "a",
    })
    assert edited.status_code == 302 and "flash=updated" in edited.headers["location"]
    db.expire_all()
    scenario = db.get(MortgageScenario, scenario.id)
    assert (scenario.name, scenario.offer, scenario.woz_value) == ("Hernoemd", Decimal("420000"), None)


def test_rates_page_default_context_and_bulk_error_status(db):
    client, user = _client(db)
    page = client.get("/hypotheek/rentes?new=3&upd=2")
    assert page.status_code == 200
    bad = client.post("/hypotheek/rentes/bulk/import", data={"raw_text": ""})
    assert bad.status_code == 400 and ("Niets te importeren" in bad.text or "Import geannuleerd" in bad.text)
    preview = client.post("/hypotheek/rentes/bulk/preview", data={"raw_text": "geen bruikbare regels"})
    assert preview.status_code == 200
