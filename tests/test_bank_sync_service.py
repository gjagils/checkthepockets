"""ACT-42a: de gedeelde banksync (app/bank_sync.py) via het scheduler-pad en de handmatige pagina."""
import json
import pytest
import requests
from fastapi.testclient import TestClient

from app import bank_sync, enable_banking
from app.auth import create_session_cookie
from app.main import app
from app.models import Account, BankConnection, ImportBatch, Rule, Transaction, User
from app.scheduler import _sync_all_bank_connections

IBAN_A = "NL91ABNA0417164300"
IBAN_B = "NL81BUNQ2088619097"


def _raw(day, amount, name="Albert Heijn", ref="pas1"):
    return {
        "booking_date": f"2026-05-{day:02d}",
        "transaction_amount": {"amount": amount, "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "remittance_information": [f"{name} {ref}"],
        "creditor": {"name": name},
    }


@pytest.fixture
def world(db):
    user = User(username="sync-user", password_hash="x")
    db.add(user)
    db.flush()
    conn = BankConnection(
        user_id=user.id, bank_name="Testbank", session_id="sess", status="active",
        accounts_json=json.dumps([
            {"uid": "uid-a", "iban": "NL91 ABNA 0417 1643 00", "name": "A"},   # met spaties
            {"uid": "uid-b", "iban": IBAN_B, "name": "B"},
        ]),
    )
    db.add(conn)
    db.commit()
    return user, conn


def _fake_transactions(monkeypatch, per_uid):
    def fake(uid, **kwargs):
        value = per_uid[uid]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(enable_banking, "get_transactions", fake)


def test_scheduler_sync_creates_batches_status_and_matches_ibans(db, world, monkeypatch):
    user, conn = world
    # Bestaande rekening met IBAN zonder spaties én zonder external_uid (legacy) moet gevonden worden.
    legacy = Account(user_id=user.id, name="Testbank - eigen naam", bank="testbank", iban=IBAN_A)
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    _fake_transactions(monkeypatch, {"uid-a": [_raw(1, "10.00"), _raw(2, "5.00", "Shell", "p2")],
                                     "uid-b": [_raw(3, "7.00", "Bakker", "p3")]})

    summary = _sync_all_bank_connections()

    assert summary.startswith("3 tx geïmporteerd uit 1 koppeling(en)")
    db.expire_all()
    accounts = {a.external_uid: a for a in db.query(Account)}
    assert accounts["uid-a"].id == legacy_id                      # IBAN-match i.p.v. een duplicaat
    assert db.query(Account).count() == 2
    batches = db.query(ImportBatch).filter_by(source="enable_banking").all()
    assert sorted(b.imported_count for b in batches) == [1, 2]
    stored = db.get(BankConnection, conn.id)
    assert stored.last_sync_status == "success" and stored.last_sync_error is None
    assert stored.last_synced_at is not None


def test_one_failing_account_leaves_the_other_intact_and_sets_error_status(db, world, monkeypatch):
    user, conn = world
    _fake_transactions(monkeypatch, {
        "uid-a": requests.ConnectionError("kapot"),
        "uid-b": [_raw(3, "7.00", "Bakker", "p3")],
    })
    _sync_all_bank_connections()
    db.expire_all()
    assert db.query(Transaction).count() == 1                       # rekening B is wel binnen
    stored = db.get(BankConnection, conn.id)
    assert stored.last_sync_status == "error" and stored.last_sync_error
    assert "uid-a" not in stored.last_sync_error                    # geen account-id in de melding


def test_unexpected_exception_in_one_account_is_isolated_by_a_savepoint(db, world, monkeypatch):
    user, conn = world
    _fake_transactions(monkeypatch, {"uid-a": [_raw(1, "10.00")], "uid-b": [_raw(3, "7.00", "Bakker", "p3")]})
    real = bank_sync.store_parsed_transactions
    calls = []

    def flaky(db_, account, parsed, rules, batch_id):
        calls.append(account.external_uid)
        if account.external_uid == "uid-a":
            raise RuntimeError("database hapert")
        return real(db_, account, parsed, rules, batch_id)

    monkeypatch.setattr(bank_sync, "store_parsed_transactions", flaky)
    _sync_all_bank_connections()
    db.expire_all()
    assert calls == ["uid-a", "uid-b"]
    assert db.query(Transaction).count() == 1                       # B bewaard, A (incl. zijn batch) teruggedraaid
    assert db.query(ImportBatch).count() == 1
    assert db.get(BankConnection, conn.id).last_sync_status == "error"


def test_second_run_imports_nothing_twice(db, world, monkeypatch):
    _fake_transactions(monkeypatch, {"uid-a": [_raw(1, "10.00")], "uid-b": []})
    _sync_all_bank_connections()
    second = _sync_all_bank_connections()
    db.expire_all()
    assert second.startswith("0 tx geïmporteerd")
    assert db.query(Transaction).count() == 1


def test_active_rules_categorise_scheduler_imports_like_the_manual_sync(db, world, monkeypatch):
    from app.models import Category

    user, conn = world
    cat = Category(user_id=user.id, name="Boodschappen")
    db.add(cat)
    db.flush()
    db.add(Rule(user_id=user.id, name="ah", match_field="counterparty", match_type="contains",
                match_value="Albert", assign_category_id=cat.id))
    db.commit()
    _fake_transactions(monkeypatch, {"uid-a": [_raw(1, "10.00")], "uid-b": []})
    _sync_all_bank_connections()
    db.expire_all()
    assert db.query(Transaction).one().category_id == cat.id


def test_manual_sync_page_uses_the_same_service(db, world, monkeypatch):
    user, conn = world
    monkeypatch.setattr("app.routers.banking.SUPER_ADMIN_USERNAME", user.username)
    _fake_transactions(monkeypatch, {"uid-a": [_raw(1, "10.00"), _raw(2, "5.00", "Shell", "p2")]})
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    page = client.post(f"/banking/sync/{conn.id}", data={"account_uid": "uid-a"})
    assert page.status_code == 200
    db.expire_all()
    assert db.query(Transaction).count() == 2
    batch = db.query(ImportBatch).one()
    assert (batch.source, batch.imported_count) == ("enable_banking", 2)
    stored = db.get(BankConnection, conn.id)
    assert stored.last_sync_status == "success"


def test_scheduler_no_longer_imports_from_routers():
    import pathlib
    text = pathlib.Path("app/scheduler.py").read_text()
    assert "from app.routers" not in text
