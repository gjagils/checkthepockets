"""ACT-55c: categorieën van alle rekeningen samenvoegen tot één gedeelde set."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.category_consolidation import apply_consolidation, plan_consolidation
from app.main import app
from app.models import Account, Budget, Category, Rule, Transaction, User

D = Decimal


def _world(db):
    user = User(username="cc", email="c@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ", bank="abn_amro", iban="NL91ABNA0417164300")
    otg = Account(user_id=user.id, name="On the go", bank="bunq", iban="NL81BUNQ2088619097")
    db.add_all([gj, otg])
    db.flush()
    gj.group_id = otg.group_id            # één groep
    cats = {}

    def cat(account, name, parent=None, **kw):
        c = Category(user_id=user.id, account_id=account.id, name=name,
                     parent_id=parent.id if parent else None, **kw)
        db.add(c)
        db.flush()
        return c

    cats["eten_gj"] = cat(gj, "Boodschappen")
    cats["eten_otg"] = cat(otg, "Boodschappen")
    cats["wonen_gj"] = cat(gj, "Wonen")
    cats["wonen_otg"] = cat(otg, "wonen")                          # andere hoofdletters
    cats["energie_gj"] = cat(gj, "Energie", cats["wonen_gj"])
    cats["energie_otg"] = cat(otg, "Energie", cats["wonen_otg"])
    cats["kleding"] = cat(otg, "Kleding")
    cats["uit_eten"] = cat(otg, "Uit eten")
    cats["leeg"] = cat(otg, "Oud en ongebruikt")
    for n, (account, key) in enumerate([(gj, "eten_gj"), (otg, "eten_otg"), (otg, "energie_otg"), (gj, "energie_gj")]):
        db.add(Transaction(account_id=account.id, date=__import__("datetime").date(2026, 10, 1 + n),
                           amount=D("-10"), category_id=cats[key].id, import_hash=f"h{n}"))
    db.add(Transaction(account_id=otg.id, date=__import__("datetime").date(2026, 10, 9), amount=D("-5"),
                       category_id=cats["kleding"].id, import_hash="k"))
    db.add(Transaction(account_id=otg.id, date=__import__("datetime").date(2026, 10, 10), amount=D("-5"),
                       category_id=cats["uit_eten"].id, import_hash="u"))
    db.add_all([
        Budget(user_id=user.id, category_id=cats["eten_gj"].id, group_id=gj.group_id, year=2026, month=10, amount=D("450")),
        Budget(user_id=user.id, category_id=cats["eten_otg"].id, group_id=gj.group_id, year=2026, month=10, amount=D("100")),
        Rule(user_id=user.id, name="AH", match_field="counterparty", match_type="contains", match_value="AH",
             assign_category_id=cats["eten_otg"].id),
    ])
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, {key: c.id for key, c in cats.items()}, client


def test_plan_merges_equal_names_per_level_and_archives_unused(db):
    user, cats, _ = _world(db)
    plan = plan_consolidation(db, user.id)
    merged = {s.category.id: s.target.id for s in plan.steps if s.action == "merge"}
    assert merged[cats["eten_otg"]] == cats["eten_gj"]
    assert merged[cats["wonen_otg"]] == cats["wonen_gj"]          # hoofdletterongevoelig
    assert merged[cats["energie_otg"]] == cats["energie_gj"]
    shared = {s.category.id for s in plan.steps if s.action == "share"}
    assert {cats["eten_gj"], cats["wonen_gj"], cats["energie_gj"], cats["kleding"]} <= shared
    assert [c.id for c in plan.archive] == [cats["leeg"]]
    assert cats["kleding"] in plan.suggestions or cats["uit_eten"] not in plan.suggestions   # geen valse match
    # preview verandert niets
    db.expire_all()
    assert db.get(Category, cats["eten_otg"]) is not None


def test_apply_moves_everything_sums_group_budgets_and_archives(db):
    user, cats, _ = _world(db)
    apply_consolidation(db, user.id)
    db.commit()
    db.expire_all()
    eten = db.get(Category, cats["eten_gj"])
    assert eten.account_id is None and db.get(Category, cats["eten_otg"]) is None
    assert db.query(Transaction).filter_by(category_id=eten.id).count() == 2        # beide rekeningen
    assert db.query(Rule).one().assign_category_id == eten.id
    budget = db.query(Budget).filter_by(category_id=eten.id).one()
    assert budget.amount == D("550")                                                 # 450 + 100 in dezelfde groep
    energie = db.get(Category, cats["energie_gj"])
    assert energie.account_id is None and energie.parent_id == cats["wonen_gj"]
    assert db.query(Transaction).filter_by(category_id=energie.id).count() == 2
    assert db.get(Category, cats["leeg"]).is_archived == 1
    assert db.get(Category, cats["kleding"]).account_id is None                  # eigen categorie wordt gedeeld


def test_manual_choice_merges_similar_names_and_page_flow(db):
    user, cats, client = _world(db)
    page = client.get("/categories/consolidate")
    assert page.status_code == 200 and "Wordt gedeeld" in page.text
    # eigen keuze: 'Uit eten' hoort bij 'Boodschappen'
    res = client.post("/categories/consolidate", data={f"merge_{cats['uit_eten']}": str(cats["eten_gj"])})
    assert res.status_code == 200
    db.expire_all()
    assert db.get(Category, cats["uit_eten"]) is None
    assert db.query(Transaction).filter_by(import_hash="u").one().category_id == cats["eten_gj"]
    # opnieuw draaien kan niets meer kapotmaken
    again = client.get("/categories/consolidate")
    assert again.status_code == 200


def test_cannot_touch_other_users_categories(db):
    user, cats, client = _world(db)
    other = User(username="x", email="x@example.test", password_hash=hash_password("pw"))
    db.add(other)
    db.flush()
    foreign = Category(user_id=other.id, name="Boodschappen")
    db.add(foreign)
    db.commit()
    client.post("/categories/consolidate", data={f"merge_{cats['kleding']}": str(foreign.id)})
    db.expire_all()
    assert db.get(Category, foreign.id) is not None
    assert db.get(Category, cats["kleding"]) is not None
