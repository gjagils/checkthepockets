"""Categorie toevoegen: gedeeld voor alle rekeningen, of voor één rekening; dubbele namen geven een melding."""
from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Category, User


def _world(db):
    user = User(username="add", email="a@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ Betaal", bank="abn_amro")
    db.add(gj)
    db.flush()
    inkomen = Category(user_id=user.id, name="Inkomen", is_income=1)          # gedeeld
    own = Category(user_id=user.id, account_id=gj.id, name="Alleen GJ")
    db.add_all([inkomen, own])
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, gj, inkomen, own, client


def test_subcategory_under_a_shared_parent_is_shared_and_inherits_income(db):
    user, gj, inkomen, own, client = _world(db)
    res = client.post("/categories", data={"name": "Salaris", "parent_id": inkomen.id, "color": "#89b4fa"})
    assert res.status_code == 200
    salaris = db.query(Category).filter_by(name="Salaris").one()
    assert salaris.account_id is None and salaris.parent_id == inkomen.id and salaris.is_income is True


def test_main_category_for_all_accounts_or_one_account(db):
    user, gj, inkomen, own, client = _world(db)
    client.post("/categories", data={"name": "Gedeeld hoofd", "account_id": "0"})
    client.post("/categories", data={"name": "Eigen hoofd", "account_id": gj.id})
    assert db.query(Category).filter_by(name="Gedeeld hoofd").one().account_id is None
    assert db.query(Category).filter_by(name="Eigen hoofd").one().account_id == gj.id


def test_duplicate_name_shows_a_message_instead_of_failing(db):
    user, gj, inkomen, own, client = _world(db)
    client.post("/categories", data={"name": "Salaris", "parent_id": inkomen.id})
    res = client.post("/categories", data={"name": "salaris", "parent_id": inkomen.id})
    assert res.status_code == 200 and "Deze categorie bestaat al" in res.text
    assert db.query(Category).filter(Category.name.ilike("salaris")).count() == 1
    res = client.post("/categories", data={"name": "Inkomen", "account_id": "0"})
    assert "Deze categorie bestaat al" in res.text and db.query(Category).filter_by(name="Inkomen").count() == 1


def test_form_labels_show_which_rekeningen_a_parent_covers(db):
    user, gj, inkomen, own, client = _world(db)
    page = client.get("/categories").text
    assert "Inkomen — alle rekeningen" in page and "Alleen GJ — alleen GJ Betaal" in page
    assert "Categorie toevoegen" in page and "Hoofdcategorie toevoegen" not in page
