"""ACT-34b: formulierparsing (A13), transfer/split-randgevallen (A15) en veilige redirects (B9)."""
import json
from datetime import date
from decimal import Decimal

import pytest


from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.forms import parse_amount, parse_int, parse_iso_date, parse_percent
from app.main import app
from app.models import Account, Category, Rule, Transaction, User
from app.redirects import safe_path


def _world(db):
    user = User(username="forms-user", password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    a = Account(user_id=user.id, name="A", bank="abn_amro")
    b = Account(user_id=user.id, name="B", bank="bunq")
    db.add_all([a, b])
    db.flush()
    return user, a, b


def _tx(account, n, amount="-10.00", **extra):
    return Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal(amount),
                       description="x", import_hash=f"h{n}", **extra)


def _client(user):
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


# ── A13 ────────────────────────────────────────────────────────────────────

def test_parsers_return_none_instead_of_raising():
    assert parse_int("12") == 12 and parse_int(" 7 ") == 7
    assert parse_int("abc") is None and parse_int("1,2,3") is None and parse_int("") is None
    assert parse_int("x", 5) == 5
    assert parse_amount("12,50") == Decimal("12.50")
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("€ 5") == Decimal("5") and parse_amount(" 7.5 ") == Decimal("7.5")
    assert parse_amount("abc") is None and parse_amount("") is None and parse_amount("NaN") is None
    assert parse_percent("3,5%") == Decimal("3.5")
    assert parse_iso_date("2026-05-01") == date(2026, 5, 1) and parse_iso_date("1/5/26") is None


def test_rule_form_with_garbage_ids_and_amounts_does_not_crash(db):
    user, a, b = _world(db)
    db.commit()
    resp = _client(user).post("/rules", data={
        "name": "r", "match_field": "description", "match_type": "contains", "match_value": "x",
        "amount_min": "1,5", "amount_max": "geen bedrag",
        "condition_account_id": "1,2,3", "assign_category_id": "abc",
    })
    assert resp.status_code in (302, 303)
    rule = db.query(Rule).one()
    assert rule.amount_min == Decimal("1.5") and rule.amount_max is None
    assert rule.condition_account_id is None and rule.assign_category_id is None


def test_budget_cell_with_invalid_amount_is_a_400(db):
    user, a, b = _world(db)
    cat = Category(user_id=user.id, name="Boodschappen")
    db.add(cat)
    db.commit()
    client = _client(user)
    bad = client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 5, "amount": "abc"})
    assert bad.status_code == 400
    ok = client.post("/budgets/save", data={"category_id": cat.id, "year": 2026, "month": 5, "amount": "12,5"})
    assert ok.status_code == 200


def test_settings_import_with_invalid_values_rolls_back_with_a_message(db):
    user, a, b = _world(db)
    db.commit()
    payload = {"version": 1, "categories": [{"name": "Nieuw"}], "rules": [],
               "recurring": [{"name": "Huur", "amount_expected": "geen-getal", "frequency": "monthly"}],
               "budgets": []}
    resp = _client(user).post("/settings/import/confirm", data={"raw_json": json.dumps(payload), "strategy": "overwrite"})
    assert resp.status_code == 200 and "ongeldige waarden" in resp.text
    assert db.query(Category).count() == 0                      # niets half opgeslagen


# ── A15 ────────────────────────────────────────────────────────────────────

def test_relinking_a_transfer_releases_the_old_partners(db):
    user, a, b = _world(db)
    t1, t2, t3, t4 = _tx(a, 1), _tx(b, 2, "10.00"), _tx(a, 3), _tx(b, 4, "10.00")
    db.add_all([t1, t2, t3, t4])
    db.flush()
    t1.transfer_id, t2.transfer_id = t2.id, t1.id
    db.commit()
    ids = [t.id for t in (t1, t2, t3, t4)]
    _client(user).post(f"/transactions/{ids[0]}/link-transfer", data={"partner_id": ids[3]})
    db.expire_all()
    rows = {t.id: t.transfer_id for t in db.query(Transaction)}
    assert rows[ids[0]] == ids[3] and rows[ids[3]] == ids[0]
    assert rows[ids[1]] is None                                  # oude partner hangt niet meer vast


def test_moving_a_transaction_unlinks_its_transfer_and_takes_split_children(db):
    user, a, b = _world(db)
    parent, partner = _tx(a, 1, "-100.00"), _tx(b, 2, "100.00")
    db.add_all([parent, partner])
    db.flush()
    child = _tx(a, 3, "-40.00", parent_id=parent.id)
    db.add(child)
    parent.transfer_id, partner.transfer_id = partner.id, parent.id
    db.commit()
    pid, partner_id, child_id, b_id = parent.id, partner.id, child.id, b.id

    client = _client(user)
    # Een deel van een splitsing verplaatsen mag niet.
    client.post(f"/transactions/{child_id}/move-account", data={"target_account_id": b_id})
    db.expire_all()
    assert db.get(Transaction, child_id).account_id == a.id

    client.post(f"/transactions/{pid}/move-account", data={"target_account_id": b_id})
    db.expire_all()
    assert db.get(Transaction, pid).account_id == b_id and db.get(Transaction, child_id).account_id == b_id
    assert db.get(Transaction, pid).transfer_id is None and db.get(Transaction, partner_id).transfer_id is None


# ── B9 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("evil", ["//evil.example", "/\\evil.example", "https://evil.example", "evil", "", "/ok\r\nSet-Cookie: x=1"])
def test_safe_path_rejects_offsite_targets(evil):
    assert safe_path(evil, "/fallback") == "/fallback"


def test_safe_path_keeps_same_site_paths():
    assert safe_path("/transactions?account_id=3&page=2", "/x") == "/transactions?account_id=3&page=2"
    assert safe_path(None, "/x") == "/x"


def test_form_redirect_cannot_leave_the_site(db):
    user, a, b = _world(db)
    tx = _tx(a, 1)
    db.add(tx)
    db.commit()
    resp = _client(user).post(f"/transactions/{tx.id}/exclude", data={"redirect_to": "//evil.example/phish"})
    assert resp.status_code == 302 and resp.headers["location"] == "/transactions"
    resp = _client(user).post(f"/transactions/{tx.id}/exclude", data={"redirect_to": "/budgets?year=2026"})
    assert resp.headers["location"] == "/budgets?year=2026"
