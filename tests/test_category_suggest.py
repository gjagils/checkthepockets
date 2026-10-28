"""Categoriesuggesties uit de historie en de AI-cache (ACT-58)."""
import hashlib
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import category_suggest
from app.auth import create_session_cookie, hash_password
from app.category_suggest import fill_ai_suggestions, merchant_hash, normalize_name, suggest_for
from app.main import app
from app.models import Account, Category, MerchantCategorySuggestion, Rule, Transaction, User


@pytest.fixture
def world(db):
    user = User(username="alice", email="a@x.nl", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Main", bank="custom", iban="NL01MAIN0000000000")
    db.add(account)
    db.flush()
    parent = Category(user_id=user.id, name="Huishouden")
    db.add(parent)
    db.flush()
    cats = {}
    for name in ("Boodschappen", "Horeca", "Kleding"):
        cats[name] = Category(user_id=user.id, name=name, parent_id=parent.id)
        db.add(cats[name])
    db.commit()
    return db, user, account, cats


def _tx(db, account, tag, *, counterparty=None, iban=None, description=None, category=None, amount="-10.00"):
    tx = Transaction(
        account_id=account.id, date=date(2026, 10, 1), amount=Decimal(amount), currency="EUR",
        description=description or f"desc {tag}", counterparty=counterparty, counterparty_iban=iban,
        category_id=category.id if category else None,
        import_hash=hashlib.sha256(tag.encode()).hexdigest(),
    )
    db.add(tx)
    db.commit()
    return tx


def test_normalize_name_drops_legal_forms_store_numbers_and_punctuation():
    assert normalize_name("Albert Heijn 1234 B.V.") == "albert heijn"
    assert normalize_name("ALBERT HEIJN") == "albert heijn"
    assert normalize_name(None) == ""


def test_history_suggests_the_category_given_before_to_the_same_counterparty(world):
    db, user, account, cats = world
    for i in range(3):
        _tx(db, account, f"old{i}", counterparty="Albert Heijn 1234", category=cats["Boodschappen"])
    new = _tx(db, account, "new", counterparty="ALBERT HEIJN 5678")

    result = suggest_for(db, user.id, [new])

    sug = result.by_tx[new.id]
    assert (sug.category_id, sug.source, sug.count, sug.total) == (cats["Boodschappen"].id, "historie", 3, 3)
    assert sug.label == "3× eerder"


def test_merchant_from_description_is_used_when_there_is_no_counterparty(world):
    db, user, account, cats = world
    _tx(db, account, "old", description="BEA, Apple Pay Bakkerij Bart NR:X70J2J, 01.04.26/10:43 VLEUTEN",
        category=cats["Horeca"])
    new = _tx(db, account, "new", description="BEA, Google Pay Bakkerij Bart NR:AB12CD, 03.05.26/09:01 VLEUTEN")

    assert suggest_for(db, user.id, [new]).by_tx[new.id].category_id == cats["Horeca"].id


def test_ambiguous_iban_falls_through_to_the_counterparty_name(world):
    """Een betaaldienst-IBAN met veel winkels mag de winkelnaam niet overstemmen."""
    db, user, account, cats = world
    psp = "NL99MOLL0123456789"
    _tx(db, account, "a", iban=psp, counterparty="Zalando", category=cats["Kleding"])
    _tx(db, account, "b", iban=psp, counterparty="Thuisbezorgd", category=cats["Horeca"])
    _tx(db, account, "c", iban=psp, counterparty="Bol", category=cats["Boodschappen"])
    new = _tx(db, account, "new", iban=psp, counterparty="Zalando")

    assert suggest_for(db, user.id, [new]).by_tx[new.id].category_id == cats["Kleding"].id


def test_no_suggestion_for_archived_categories_or_categorized_transactions(world):
    db, user, account, cats = world
    _tx(db, account, "old", counterparty="Kringloop", category=cats["Kleding"])
    done = _tx(db, account, "done", counterparty="Kringloop", category=cats["Kleding"])
    new = _tx(db, account, "new", counterparty="Kringloop")
    cats["Kleding"].is_archived = 1
    db.commit()

    result = suggest_for(db, user.id, [done, new])

    assert result.by_tx == {}
    assert result.ai_pending == 1


def test_other_users_history_is_never_used(world):
    db, user, account, cats = world
    bob = User(username="bob", email="b@x.nl", password_hash=hash_password("pw"))
    db.add(bob)
    db.flush()
    bob_acc = Account(user_id=bob.id, name="Bob", bank="custom", iban="NL02BOBB0000000000")
    db.add(bob_acc)
    db.commit()
    _tx(db, bob_acc, "bob", counterparty="Jumbo", category=cats["Boodschappen"])
    new = _tx(db, account, "new", counterparty="Jumbo")

    assert suggest_for(db, user.id, [new]).by_tx == {}


def test_ai_is_asked_once_per_counterparty_and_the_answer_is_cached(world, monkeypatch):
    db, user, account, cats = world
    _tx(db, account, "known", counterparty="Jumbo", category=cats["Boodschappen"])
    _tx(db, account, "jumbo-open", counterparty="Jumbo")       # heeft historie: niet naar de AI
    t1 = _tx(db, account, "c1", counterparty="Café Thijs")
    t2 = _tx(db, account, "c2", counterparty="CAFÉ THIJS B.V.")  # zelfde tegenpartij na normaliseren
    t3 = _tx(db, account, "z1", counterparty="Wehkamp")
    prompts = []

    def fake_call(prompt, *, max_tokens):
        prompts.append(prompt)
        lines = [line for line in prompt.splitlines() if line[:1].isdigit() and ". " in line]
        names = {int(line.split(".", 1)[0]): line.split(". ", 1)[1].split(" |")[0] for line in lines}
        answer = []
        for nr, name in names.items():
            cid = cats["Horeca"].id if "thijs" in name else (999999 if name == "wehkamp" else None)
            answer.append({"nr": nr, "category_id": cid})
        return answer

    monkeypatch.setattr(category_suggest, "ai_available", lambda: True)
    monkeypatch.setattr(category_suggest.ai_client, "call_json", fake_call)

    answered = fill_ai_suggestions(db, user.id)

    assert len(prompts) == 1
    assert "jumbo" not in prompts[0]
    assert answered == 2   # "café thijs" één keer, "wehkamp"
    rows = {r.merchant_hash: r.category_id for r in db.query(MerchantCategorySuggestion)}
    assert rows[merchant_hash("wehkamp")] is None    # onbekend id telt als "weet niet"
    assert "wehkamp" not in "".join(rows)             # geen leesbare naam in de cache

    result = suggest_for(db, user.id, [t1, t2, t3])
    assert result.by_tx[t1.id].source == "ai"
    assert result.by_tx[t1.id].category_id == cats["Horeca"].id
    assert result.by_tx[t2.id].category_id == cats["Horeca"].id
    assert t3.id not in result.by_tx
    assert result.ai_pending == 0

    # Een tweede keer: niets meer te vragen, dus geen call.
    assert fill_ai_suggestions(db, user.id) == 0
    assert len(prompts) == 1


def test_ai_failure_stores_nothing(world, monkeypatch):
    db, user, account, cats = world
    _tx(db, account, "x", counterparty="Wehkamp")

    def boom(prompt, *, max_tokens):
        raise RuntimeError("api down")

    monkeypatch.setattr(category_suggest, "ai_available", lambda: True)
    monkeypatch.setattr(category_suggest.ai_client, "call_json", boom)

    assert fill_ai_suggestions(db, user.id) == 0
    assert db.query(MerchantCategorySuggestion).count() == 0


def _client(user_id):
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_transaction_page_shows_the_suggestion_and_bulk_accept_applies_it(world):
    db, user, account, cats = world
    _tx(db, account, "old", counterparty="Albert Heijn", category=cats["Boodschappen"])
    new = _tx(db, account, "new", counterparty="Albert Heijn")
    other = _tx(db, account, "other", counterparty="Onbekend")
    client = _client(user.id)

    page = client.get("/transactions")
    assert page.status_code == 200
    assert "✓ Boodschappen" in page.text
    assert "Neem 1 suggestie over" in page.text

    resp = client.post(
        "/transactions/accept-suggestions",
        data={"tx_ids": [new.id, other.id], "redirect_to": "/transactions"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(Transaction, new.id).category_id == cats["Boodschappen"].id
    assert db.get(Transaction, new.id).is_reviewed == 1
    assert db.get(Transaction, other.id).category_id is None


def test_bulk_accept_ignores_transactions_of_another_user(world):
    db, user, account, cats = world
    bob = User(username="bob", email="b@x.nl", password_hash=hash_password("pw"))
    db.add(bob)
    db.commit()
    _tx(db, account, "old", counterparty="Albert Heijn", category=cats["Boodschappen"])
    new = _tx(db, account, "new", counterparty="Albert Heijn")

    _client(bob.id).post("/transactions/accept-suggestions", data={"tx_ids": [new.id]}, follow_redirects=False)

    db.expire_all()
    assert db.get(Transaction, new.id).category_id is None


# --- Per tegenpartij categoriseren (ACT-60) ---

def test_open_groups_bundle_name_variants_and_put_the_largest_first(world):
    db, user, account, cats = world
    _tx(db, account, "old", counterparty="Albert Heijn 1234", category=cats["Boodschappen"])
    for i in range(3):
        _tx(db, account, f"ah{i}", counterparty=f"ALBERT HEIJN {5670 + i}")
    _tx(db, account, "hm", counterparty="H&M")
    _tx(db, account, "bart", description="BEA, Apple Pay Bakkerij Bart NR:X70J2J, 01.04.26/10:43 VLEUTEN")

    groups, unnamed = category_suggest.open_groups(db, user.id)

    assert [g.count for g in groups] == [3, 1, 1]
    ah = groups[0]
    assert ah.suggestion.category_id == cats["Boodschappen"].id
    assert (ah.rule_field, ah.rule_value) == ("counterparty", "albert heijn")
    by_name = {g.name: g for g in groups}
    # "h m" staat niet letterlijk in "h&m" en "H&M" is te kort: geen regel.
    assert by_name["H&M"].rule_value is None
    assert by_name["Bakkerij Bart"].rule_field == "description"
    assert unnamed == 0


def test_group_apply_categorizes_the_group_and_the_rule_only_fills_open_transactions(world):
    db, user, account, cats = world
    a = _tx(db, account, "a", counterparty="Café Thijs")
    b = _tx(db, account, "b", counterparty="CAFÉ THIJS B.V.")
    other_month = _tx(db, account, "c", counterparty="Cafe Thijs")   # zonder accent: andere groep
    done = _tx(db, account, "d", counterparty="Café Thijs Utrecht", category=cats["Kleding"])
    later = _tx(db, account, "e", counterparty="café thijs terras")  # eigen groep, wel door de regel
    groups, _ = category_suggest.open_groups(db, user.id)
    key = next(g.key for g in groups if g.count == 2)

    resp = _client(user.id).post(
        "/transactions/groups/apply",
        data={"key": key, "category_id": cats["Horeca"].id, "make_rule": "1", "tx_ids": [a.id, b.id]},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert "applied=2" in resp.headers["location"]
    assert "rule_extra=1" in resp.headers["location"]
    db.expire_all()
    assert {db.get(Transaction, t.id).category_id for t in (a, b, later)} == {cats["Horeca"].id}
    assert db.get(Transaction, done.id).category_id == cats["Kleding"].id     # nooit overschreven
    assert db.get(Transaction, other_month.id).category_id is None
    rule = db.query(Rule).one()
    assert (rule.match_field, rule.match_type, rule.match_value) == ("counterparty", "contains", "café thijs")
    assert rule.assign_category_id == cats["Horeca"].id


def test_group_page_renders_and_apply_ignores_foreign_or_unknown_input(world):
    db, user, account, cats = world
    tx = _tx(db, account, "a", counterparty="Wehkamp")
    client = _client(user.id)

    page = client.get("/transactions/groups")
    assert page.status_code == 200
    assert "Wehkamp" in page.text and "Toewijzen (<span class=\"tx-group-count\">1</span>)" in page.text
    assert "Per tegenpartij" in client.get("/transactions").text

    bob = User(username="bob", email="b@x.nl", password_hash=hash_password("pw"))
    db.add(bob)
    db.commit()
    key = category_suggest.open_groups(db, user.id)[0][0].key
    _client(bob.id).post("/transactions/groups/apply",
                         data={"key": key, "category_id": cats["Kleding"].id, "tx_ids": [tx.id]})
    client.post("/transactions/groups/apply", data={"key": key, "category_id": 999999, "tx_ids": [tx.id]})
    client.post("/transactions/groups/apply", data={"key": key, "category_id": cats["Kleding"].id})  # niets gekozen

    db.expire_all()
    assert db.get(Transaction, tx.id).category_id is None
    assert db.query(Rule).count() == 0


def test_deselected_transactions_stay_open_also_when_a_rule_is_made(world):
    db, user, account, cats = world
    keep = _tx(db, account, "a", counterparty="Wehkamp")
    skip = _tx(db, account, "b", counterparty="WEHKAMP", amount="250.00")   # retour: niet meenemen
    key = category_suggest.open_groups(db, user.id)[0][0].key

    resp = _client(user.id).post(
        "/transactions/groups/apply",
        data={"key": key, "category_id": cats["Kleding"].id, "make_rule": "1", "tx_ids": [keep.id]},
        follow_redirects=False,
    )

    assert "applied=1" in resp.headers["location"]
    db.expire_all()
    assert db.get(Transaction, keep.id).category_id == cats["Kleding"].id
    assert db.get(Transaction, skip.id).category_id is None
    assert db.query(Rule).count() == 1


def test_a_deselected_transaction_can_get_its_own_category(world):
    db, user, account, cats = world
    keep = _tx(db, account, "a", counterparty="Bol")
    other = _tx(db, account, "b", counterparty="BOL")
    left = _tx(db, account, "c", counterparty="bol")
    key = category_suggest.open_groups(db, user.id)[0][0].key
    client = _client(user.id)

    client.post("/transactions/groups/apply", data={
        "key": key, "category_id": cats["Boodschappen"].id, "tx_ids": [keep.id],
        f"other_cat_{other.id}": cats["Kleding"].id, f"other_cat_{keep.id}": cats["Horeca"].id,
    })

    db.expire_all()
    assert db.get(Transaction, keep.id).category_id == cats["Boodschappen"].id   # aangevinkt wint
    assert db.get(Transaction, other.id).category_id == cats["Kleding"].id
    assert db.get(Transaction, left.id).category_id is None

    # Alleen een eigen keuze, niets aangevinkt en geen groepscategorie: werkt ook.
    client.post("/transactions/groups/apply", data={"key": key, f"other_cat_{left.id}": cats["Horeca"].id})
    db.expire_all()
    assert db.get(Transaction, left.id).category_id == cats["Horeca"].id


def test_group_apply_does_not_compute_suggestions(world, monkeypatch):
    """Toewijzen moet licht blijven: de historie ontsleutelen hield de databaseverbinding te lang open."""
    db, user, account, cats = world
    tx = _tx(db, account, "a", counterparty="Wehkamp")
    key = category_suggest.open_groups(db, user.id)[0][0].key

    def no_history(*args, **kwargs):
        raise AssertionError("suggesties niet nodig bij toewijzen")

    monkeypatch.setattr(category_suggest, "suggest_for", no_history)
    _client(user.id).post("/transactions/groups/apply",
                          data={"key": key, "category_id": cats["Kleding"].id, "tx_ids": [tx.id]},
                          follow_redirects=False)

    db.expire_all()
    assert db.get(Transaction, tx.id).category_id == cats["Kleding"].id
