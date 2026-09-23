"""Compact savings planner: one line per row and a movement row (ACT-27)."""
import html as html_lib
import os
import re
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, SavingsEntry, SavingsLine, SavingsPlan, User


@pytest.fixture
def planner():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    user = User(username="planner", password_hash="x")
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Samen spaar", bank="abn_amro")
    db.add(account)
    db.flush()
    plan = SavingsPlan(user_id=user.id, account_id=account.id, year=2030, starting_balance=Decimal("1000"))
    db.add(plan)
    db.flush()
    income = SavingsLine(plan_id=plan.id, name="Maandelijks sparen", frequency="monthly",
                         default_amount=Decimal("200"), is_income=1, sort_order=0)
    holiday = SavingsLine(plan_id=plan.id, name="Vakantie", frequency="one-off",
                          default_amount=Decimal("1500"), is_income=0, sort_order=1)
    db.add_all([income, holiday])
    db.flush()
    for m in range(1, 13):
        db.add(SavingsEntry(line_id=income.id, month=m, amount=Decimal("200"), status="forecast"))
        db.add(SavingsEntry(line_id=holiday.id, month=m, amount=Decimal("1500") if m == 7 else None, status="forecast"))
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    try:
        yield client, plan.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _row_cells(html, row_class, cell_class):
    row = re.search(rf'<tr class="{row_class}">(.*?)</tr>', html, re.S).group(1)
    return [re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(rf'<td class="[^"]*{cell_class}[^"]*"[^>]*>(.*?)</td>', row, re.S)]


def test_movement_row_shows_net_change_per_month(planner):
    client, plan_id = planner

    html = client.get(f"/savings/{plan_id}").text

    movement = _row_cells(html, "movement-row", "movement-cell")
    assert len(movement) == 12
    assert movement[0] == "€ 200,00"
    assert movement[6] == "€ -1.300,00"
    assert movement[11] == "€ 200,00"


def test_each_line_renders_on_one_row_with_hover_actions(planner):
    client, plan_id = planner

    html = client.get(f"/savings/{plan_id}").text

    assert html.count('class="line-cell') == 2
    assert "line-head-row" not in html
    cell = re.search(r'<div class="line-cell[^"]*">(.*?)</div>\s*</div>', html, re.S).group(1)
    assert "Maandelijks sparen" in cell and 'title="Bewerken"' in cell


def _entry_id(plan_id, line_name, month):
    db = SessionLocal()
    try:
        return (
            db.query(SavingsEntry.id)
            .join(SavingsLine)
            .filter(SavingsLine.plan_id == plan_id, SavingsLine.name == line_name, SavingsEntry.month == month)
            .scalar()
        )
    finally:
        db.close()


def test_future_cell_update_recalculates_and_makes_line_irregular(planner):
    client, plan_id = planner
    entry_id = _entry_id(plan_id, "Vakantie", 3)

    response = client.post("/savings/entries/update", data={"entry_id": entry_id, "amount": "1.250,50"})

    data = response.json()
    assert response.status_code == 200 and data["ok"]
    assert data["amount"] == 1250.5
    assert data["frequency"] == "custom"
    assert data["running_balances"]["3"] == 1000 + 3 * 200 - 1250.5
    assert data["movements"]["3"] == 200 - 1250.5
    assert data["movements"]["7"] == 200 - 1500
    assert data["line_total"] == 1500 + 1250.5

    cleared = client.post("/savings/entries/update", data={"entry_id": entry_id, "amount": ""}).json()
    assert cleared["amount"] is None and cleared["line_total"] == 1500

    html = client.get(f"/savings/{plan_id}").text
    assert html.count(' cell-editable"') == 24  # every month is in the future for plan year 2030


def test_cell_update_rejects_invalid_amount_and_other_users(planner):
    client, plan_id = planner
    entry_id = _entry_id(plan_id, "Vakantie", 3)

    assert client.post("/savings/entries/update", data={"entry_id": entry_id, "amount": "abc"}).status_code == 400

    db = SessionLocal()
    other = User(username="planner-other", password_hash="x")
    db.add(other)
    db.commit()
    other_client = TestClient(app, follow_redirects=False)
    other_client.cookies.set("session", create_session_cookie(other.id))
    db.close()
    assert other_client.post("/savings/entries/update", data={"entry_id": entry_id, "amount": "1"}).status_code == 404


def test_past_months_are_not_editable(planner):
    client, plan_id = planner
    db = SessionLocal()
    plan = db.get(SavingsPlan, plan_id)
    plan.year = 2020
    db.commit()
    db.close()
    entry_id = _entry_id(plan_id, "Vakantie", 7)

    response = client.post("/savings/entries/update", data={"entry_id": entry_id, "amount": "10"})

    assert response.status_code == 409
    assert ' cell-editable"' not in client.get(f"/savings/{plan_id}").text
