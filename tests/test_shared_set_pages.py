"""ACT-55d: budget-, spaar- en categoriepagina's werken met een gedeelde categorieënset."""
import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Budget, Category, SavingsPlan, Transaction, User

D = Decimal


def _world(db):
    user = User(username="sp", email="s@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ", bank="abn_amro", iban="NL91ABNA0417164300")
    otg = Account(user_id=user.id, name="On the go", bank="bunq", iban="NL81BUNQ2088619097")
    db.add_all([gj, otg])
    db.flush()
    gj.group_id = otg.group_id
    shared = Category(user_id=user.id, name="Boodschappen")
    own = Category(user_id=user.id, account_id=gj.id, name="Alleen GJ")
    ghost = Category(user_id=user.id, name="Oud", is_archived=1)
    used_archived = Category(user_id=user.id, name="Oud met budget", is_archived=1)
    db.add_all([shared, own, ghost, used_archived])
    db.flush()
    today = datetime.date.today()
    db.add(Budget(user_id=user.id, category_id=used_archived.id, group_id=gj.group_id,
                  year=today.year, month=today.month, amount=D("77")))
    db.add(Transaction(account_id=otg.id, date=today, amount=D("-12"), category_id=shared.id, import_hash="x"))
    plan = SavingsPlan(user_id=user.id, account_id=gj.id, year=today.year)
    db.add(plan)
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, gj, otg, plan, client


def test_budget_page_group_view_shows_shared_and_hides_unused_archived(db):
    user, gj, otg, plan, client = _world(db)
    page = client.get(f"/budgets?group_id={gj.group_id}").text
    assert "Boodschappen" in page and "Alleen GJ" in page
    assert "Oud met budget" in page                 # archief maar nog een budget: zichtbaar
    assert ">Oud<" not in page and "Oud</" not in page.replace("Oud met budget</", "")


def test_savings_dropdown_offers_shared_categories_but_not_archived(db):
    user, gj, otg, plan, client = _world(db)
    page = client.get(f"/savings/{plan.id}").text
    assert "Boodschappen" in page and "Alleen GJ" in page
    assert ">Oud<" not in page


def test_category_list_for_an_account_includes_shared_categories(db):
    user, gj, otg, plan, client = _world(db)
    page = client.get(f"/categories?account_id={otg.id}").text
    assert "Boodschappen" in page                    # gedeeld
