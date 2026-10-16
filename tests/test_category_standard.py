"""ACT-56: bestaande categorieën afbeelden op de standaardset, met splitsing van 'Gerd-Jan/Nelleke'."""
import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.category_standard import STANDARD_SET, apply_standard, plan_standard
from app.main import app
from app.models import Account, Budget, Category, Transaction, User

D = Decimal


def _world(db):
    user = User(username="std", email="s@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    accounts = {n: Account(user_id=user.id, name=n, bank="bunq") for n in
                ("Samen Betaal", "Samen Spaar Bunq", "Abn samen spaar", "GJ - Spaar")}
    db.add_all(accounts.values())
    db.flush()
    cats = {}

    def cat(account, name, parent=None):
        c = Category(user_id=user.id, account_id=accounts[account].id, name=name,
                     parent_id=parent.id if parent else None)
        db.add(c)
        db.flush()
        cats[(account, name)] = c
        return c

    inkomen = cat("Samen Betaal", "Inkomen")
    cat("Samen Betaal", "Gerd-Jan/Nelleke", inkomen)
    cat("Samen Betaal", "Overboek", inkomen)
    huishoud = cat("Samen Betaal", "Huishoud")
    cat("Samen Betaal", "Boodschappen", huishoud)
    cat("Samen Betaal", "Transport", huishoud)
    vast = cat("Samen Betaal", "Vaste lasten")
    cat("Samen Betaal", "Sparen", vast)
    spaar_inkomsten = cat("Samen Spaar Bunq", "Inkomsten")
    cat("Samen Spaar Bunq", "Rente", spaar_inkomsten)
    cat("Samen Spaar Bunq", "Ziektekosten", spaar_inkomsten)
    abn = cat("Abn samen spaar", "Inkomen")
    cat("Abn samen spaar", "Maandelijks sparen", abn)
    cat("Abn samen spaar", "Rente", abn)
    overig = cat("GJ - Spaar", "Overig")
    cat("GJ - Spaar", "Onbekende categorie", overig)                          # niet in de mapping
    gjn = cats[("Samen Betaal", "Gerd-Jan/Nelleke")]

    def tx(account, n, amount, counterparty, category, desc=None):
        db.add(Transaction(account_id=accounts[account].id, date=datetime.date(2026, 1, 1) + datetime.timedelta(n),
                           amount=D(amount), counterparty=counterparty, description=desc,
                           import_hash=f"h{n}", category_id=category.id))

    tx("Samen Betaal", 1, "2400", "GJA VAN GILS", gjn)
    tx("Samen Betaal", 2, "2400", "GJA VAN GILS", gjn)
    tx("Samen Betaal", 3, "2475", "N STEENDAM", gjn)
    tx("Samen Betaal", 4, "-200", "N STEENDAM CJ", gjn, "SEPA Periodieke overb. Naam: Samen spaar")
    tx("Samen Spaar Bunq", 5, "700", "N STEENDAM CJ", gjn)
    tx("Abn samen spaar", 6, "200", None, gjn, "SEPA Periodieke overb. Naam: N STEENDAM CJ")
    tx("GJ - Spaar", 7, "72.50", "N STEENDAM CJ", gjn, "Marktplaats")
    tx("Samen Betaal", 8, "-45", "AH", cats[("Samen Betaal", "Boodschappen")])
    tx("Samen Betaal", 9, "-300", "SPAAR", cats[("Samen Betaal", "Sparen")])
    tx("Samen Spaar Bunq", 10, "12", "Bank", cats[("Samen Spaar Bunq", "Rente")])
    tx("Abn samen spaar", 11, "1", "Bank", cats[("Abn samen spaar", "Rente")])
    tx("Samen Spaar Bunq", 12, "55", None, cats[("Samen Spaar Bunq", "Ziektekosten")])
    tx("GJ - Spaar", 13, "5", "Iemand", cats[("GJ - Spaar", "Onbekende categorie")])
    db.add(Budget(user_id=user.id, category_id=cats[("Samen Betaal", "Boodschappen")].id,
                  year=2026, month=1, amount=D("450")))
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, accounts, cats, client


def _by_name(db, user):
    shared = db.query(Category).filter(Category.user_id == user.id, Category.account_id.is_(None)).all()
    names = {c.id: c.name for c in shared}
    return {c.name: c for c in shared}, names


def test_plan_shows_split_moves_untouched_and_creations(db):
    user, accounts, cats, _ = _world(db)
    plan = plan_standard(db, user.id)
    split = next(r for r in plan.rows if r.category.name == "Gerd-Jan/Nelleke")
    assert split.split == {("Inkomen", "Bijdrage Gerd-Jan"): 2, ("Inkomen", "Bijdrage Nelleke"): 1,
                           ("Sparen", "Storting samen"): 2, ("Sparen", "Storting Nelleke"): 1,
                           ("Inkomen", "Overig inkomen"): 1}
    assert [r.category.name for r in plan.untouched] == ["Onbekende categorie"]
    assert ("Sparen", None) in plan.to_create and ("Sparen", "Storting zorgpremie") in plan.to_create
    db.expire_all()
    assert db.query(Category).filter(Category.account_id.is_(None)).count() == 0     # preview wijzigt niets


def test_apply_moves_everything_and_keeps_data(db):
    user, accounts, cats, _ = _world(db)
    ids = {key: c.id for key, c in cats.items()}
    apply_standard(db, user.id)
    db.commit()
    db.expire_all()
    shared, _names = _by_name(db, user)

    def total(name):
        return db.query(Transaction).filter_by(category_id=shared[name].id).count()

    assert total("Bijdrage Gerd-Jan") == 2 and total("Bijdrage Nelleke") == 1
    assert total("Storting samen") == 3            # 2 uit de split + 1 uit 'Vaste lasten › Sparen'
    assert total("Storting Nelleke") == 1 and total("Overig inkomen") == 1
    assert total("Rente") == 2 and total("Storting zorgpremie") == 1 and total("Boodschappen") == 1
    assert db.query(Transaction).count() == 13                                      # niets kwijt
    assert db.get(Category, ids[("Samen Betaal", "Gerd-Jan/Nelleke")]) is None
    assert db.get(Category, ids[("GJ - Spaar", "Onbekende categorie")]) is not None
    budget = db.query(Budget).one()
    assert budget.category_id == shared["Boodschappen"].id and budget.amount == D("450")
    # lege oude hoofdcategorieën zijn gearchiveerd; de nieuwe zitten onder gedeelde hoofdcategorieën
    assert db.get(Category, ids[("Samen Betaal", "Huishoud")]).is_archived == 1
    assert shared["Boodschappen"].parent_id == shared["Dagelijks"].id and shared["Dagelijks"].parent_id is None
    assert shared["Eigen rekeningen"].exclude_from_totals == 1
    assert shared["Inkomen"].is_income == 1 and shared["Bijdrage Nelleke"].is_income == 1
    # opnieuw uitvoeren verandert niets meer
    again = plan_standard(db, user.id)
    assert [r.category.name for r in again.moves] == [] and again.to_create == []


def test_override_and_web_flow(db):
    user, accounts, cats, client = _world(db)
    unknown = cats[("GJ - Spaar", "Onbekende categorie")].id
    page = client.get("/categories/standaard")
    assert page.status_code == 200 and "Gesplitst" in page.text and "Blijft staan" in page.text
    res = client.post("/categories/standaard", data={f"map_{unknown}": "Vrije tijd|Sport"})
    assert res.status_code == 200
    db.expire_all()
    assert db.query(Category).filter_by(id=unknown).first() is None
    assert db.query(Category).filter_by(name="Sport").one().account_id is None
    # ongeldig doel wordt genegeerd: de categorie blijft staan
    other = db.query(Category).filter_by(name="Ziektekosten").first()
    assert other is None                                                             # al verplaatst door de standaardmapping


def test_standard_set_has_no_duplicate_names():
    names = [n for h, subs in STANDARD_SET for n in [h, *subs]]
    assert len(names) == len(set(names))
