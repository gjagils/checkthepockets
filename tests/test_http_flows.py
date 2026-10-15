"""ACT-51: de belangrijkste schrijf-flows via HTTP, als vangnet voor het redesign van de formulieren."""
from decimal import Decimal

from app.models import Budget, Category, Rule, Transaction
from tests.test_http_smoke import world  # noqa: F401  (fixture: ingelogde gebruiker met realistische data)


def test_create_and_rename_a_category_and_it_shows_in_the_list(world, db):  # noqa: F811
    client, ids = world
    account_id = ids["account"]
    created = client.post("/categories", data={"name": "Vakantie", "account_id": account_id})
    assert created.status_code == 302
    assert "Vakantie" in client.get("/categories").text
    category = db.query(Category).filter_by(name="Vakantie").one()
    assert category.account_id == account_id


def test_set_a_category_on_a_transaction(world, db):  # noqa: F811
    client, ids = world
    category = db.query(Category).filter_by(name="Wonen").one()
    response = client.post(f"/transactions/{ids['tx']}/category", data={"category_id": category.id})
    assert response.status_code == 302
    db.expire_all()
    assert db.get(Transaction, ids["tx"]).category_id == category.id


def test_transactions_list_search_filters_and_csv_export(world):  # noqa: F811
    client, ids = world
    assert "Tegenpartij 3" in client.get("/transactions?search=Tegenpartij+3").text
    assert client.get(f"/transactions?account_id={ids['account']}&uncategorized=1").status_code == 200
    export = client.get("/transactions/export")
    assert export.status_code == 200 and "csv" in export.headers["content-type"]
    assert "Tegenpartij 1" in export.text


def test_create_a_rule_and_preview_it(world, db):  # noqa: F811
    client, ids = world
    category = db.query(Category).filter_by(name="Energie").one()
    created = client.post("/rules", data={
        "name": "Test-regel", "match_field": "counterparty", "match_type": "contains",
        "match_value": "Tegenpartij 5", "assign_category_id": category.id,
    })
    assert created.status_code in (302, 303)
    rule = db.query(Rule).filter_by(name="Test-regel").one()
    assert "Test-regel" in client.get("/rules").text
    preview = client.get(f"/rules/{rule.id}/preview")
    assert preview.status_code == 200


def test_save_a_budget_cell_and_see_it_on_the_page(world, db):  # noqa: F811
    client, ids = world
    category = db.query(Category).filter_by(name="Energie").one()   # subcategorie: daar staan de invoercellen
    from app import clock
    today = clock.today_nl()
    saved = client.post("/budgets/save", data={"category_id": category.id, "year": today.year,
                                               "month": today.month, "amount": "1.250,50"})
    assert saved.status_code == 200
    assert db.query(Budget).filter_by(category_id=category.id).one().amount == Decimal("1250.50")
    assert "1250" in client.get("/budgets").text or "1.250" in client.get("/budgets").text


def test_analytics_queries_for_each_grouping(world):  # noqa: F811
    client, ids = world
    for group_by in ("category", "month", "counterparty"):
        response = client.get(f"/analytics/query?group_by={group_by}")
        assert response.status_code == 200, group_by
    assert client.get("/analytics/stats").status_code == 200


def test_duplicates_and_split_pages_render(world):  # noqa: F811
    client, ids = world
    assert client.get("/transactions/duplicates").status_code == 200
    assert client.get(f"/transactions/{ids['tx']}/split").status_code == 200
    assert client.get("/transactions/create").status_code == 200


def test_rule_suggestions_show_full_description_example_and_group(world, db):  # noqa: F811
    from app.models import RuleSuggestion, User
    client, ids = world
    user = db.query(User).filter_by(username="smoke-admin").one()
    long_text = "Omschrijving 7 " + "x" * 120 + " einde-van-de-omschrijving"
    tx = db.query(Transaction).filter_by(import_hash="smoke-7").one()
    tx.description = long_text
    for name in ("Tegenpartij 7", "Tegenpartij 7"):
        db.add(RuleSuggestion(user_id=user.id, match_value=name, uncat_count=1, cat_count=0))
    db.commit()
    html = client.get("/rules").text
    assert "einde-van-de-omschrijving" in html          # volledige omschrijving zichtbaar als voorbeeld
    assert "Zelfde zoekterm: voorstel 1 van 2" in html
    assert "Zelfde zoekterm: voorstel 2 van 2" in html
    sid = db.query(RuleSuggestion).first().id
    data = client.get(f"/rules/suggestion/{sid}/transactions").json()
    assert any(t["description"] == long_text for t in data["transactions"])   # niet afgekapt
