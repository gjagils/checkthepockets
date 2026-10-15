"""ACT-55b: budget per rekeninggroep."""
import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Budget, Category, Transaction, User

D = Decimal


def _world(db):
    user = User(username="bg", email="b@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ", bank="abn_amro", iban="NL91ABNA0417164300")
    otg = Account(user_id=user.id, name="On the go", bank="bunq", iban="NL81BUNQ2088619097")
    spaar = Account(user_id=user.id, name="Anders", bank="ing")
    db.add_all([gj, otg, spaar])
    db.flush()
    shared = Category(user_id=user.id, name="Boodschappen")          # gedeeld: geen rekening
    db.add(shared)
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, gj, otg, spaar, shared, client


def test_same_category_can_have_a_budget_per_group(db):
    user, gj, otg, other, cat, client = _world(db)
    gj.group_id = otg.group_id            # GJ + On the go vormen één groep
    db.commit()
    assert gj.group_id == otg.group_id != other.group_id
    for group, amount in ((gj.group_id, "450"), (other.group_id, "120")):
        res = client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 10,
                                                 "amount": amount, "group_id": group})
        assert res.json()["ok"] is True
    rows = db.query(Budget).filter_by(category_id=cat.id).all()
    assert {(r.group_id, r.amount) for r in rows} == {(gj.group_id, D("450")), (other.group_id, D("120"))}
    # opnieuw opslaan overschrijft binnen dezelfde groep
    client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 10,
                                       "amount": "500", "group_id": gj.group_id})
    db.expire_all()
    assert db.query(Budget).filter_by(category_id=cat.id).count() == 2
    assert db.query(Budget).filter_by(category_id=cat.id, group_id=gj.group_id).one().amount == D("500")


def test_budget_page_shows_group_budget_and_group_spending_only(db):
    user, gj, otg, other, cat, client = _world(db)
    gj.group_id = otg.group_id
    today = datetime.date.today()
    db.add_all([
        Budget(user_id=user.id, category_id=cat.id, group_id=gj.group_id, year=today.year, month=today.month, amount=D("450")),
        Budget(user_id=user.id, category_id=cat.id, group_id=other.group_id, year=today.year, month=today.month, amount=D("120")),
        Transaction(account_id=otg.id, date=today, amount=D("-40"), category_id=cat.id, import_hash="t1"),
        Transaction(account_id=other.id, date=today, amount=D("-99"), category_id=cat.id, import_hash="t2"),
    ])
    db.commit()
    page = client.get(f"/budgets?group_id={gj.group_id}").text
    assert "450" in page and "120" not in page.split("Boodschappen")[1][:600]
    other_page = client.get(f"/budgets?group_id={other.group_id}").text
    assert "120" in other_page
    all_page = client.get("/budgets")
    assert all_page.status_code == 200


def test_budget_without_group_for_shared_category_is_unique(db):
    user, gj, otg, other, cat, client = _world(db)
    client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 9, "amount": "10"})
    client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 9, "amount": "20"})
    rows = db.query(Budget).filter_by(category_id=cat.id, month=9).all()
    assert len(rows) == 1 and rows[0].group_id is None and rows[0].amount == D("20")
