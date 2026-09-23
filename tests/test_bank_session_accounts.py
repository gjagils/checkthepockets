"""Accounts from an Enable Banking session stay visible (ACT-25a/b)."""
import json
import logging
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app import enable_banking
from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import BankConnection, User
from app.routers.banking import _describe_session_accounts, _merge_session_uids

SAVINGS_WITHOUT_UID = {
    "account_id": {"iban": "NL11BUNQ0000000001"}, "cash_account_type": "SVGS",
    "account_servicer": {"bic_fi": "BUNQNL2A"}, "uid": None,
}
SAVINGS_WITH_UID = {
    "account_id": {"iban": "NL22BUNQ0000000002"}, "cash_account_type": "SVGS", "uid": "uid-savings-2",
}


def _details(uid):
    if uid == "uid-savings-3":
        return {"account_id": {"iban": "NL33BUNQ0000000003"}, "cash_account_type": "SVGS"}
    return {"account_id": [{"iban": "NL22BUNQ0000000002"}], "account_servicer": {"bic_fi": "BUNQNL2A"}}


def test_describe_keeps_accounts_without_uid_in_order():
    described = _describe_session_accounts([SAVINGS_WITHOUT_UID, SAVINGS_WITH_UID], _details)

    assert described == [
        {"uid": None, "iban": "NL11BUNQ0000000001", "name": "BUNQNL2A", "type": "Spaarrekening", "available": False},
        {"uid": "uid-savings-2", "iban": "NL22BUNQ0000000002", "name": "BUNQNL2A", "type": "Spaarrekening", "available": True},
    ]


def test_describe_falls_back_to_session_iban_when_details_fail():
    def fail(uid):
        raise RuntimeError("details unavailable")

    [account] = _describe_session_accounts([SAVINGS_WITH_UID, "not-an-account"], fail)

    assert (account["iban"], account["available"]) == ("NL22BUNQ0000000002", True)


def test_merge_adds_uids_missing_from_post_response():
    merged = _merge_session_uids(
        [SAVINGS_WITH_UID],
        {"accounts": ["uid-savings-2", "uid-savings-3"],
         "accounts_data": [{"uid": "uid-savings-3", "identification_hash": "h"}, {"uid": "uid-savings-4"}]},
    )
    assert merged == [SAVINGS_WITH_UID, {"uid": "uid-savings-3"}, {"uid": "uid-savings-4"}]
    assert _merge_session_uids([SAVINGS_WITH_UID], {}) == [SAVINGS_WITH_UID]


@pytest.fixture
def banking_client(monkeypatch):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    user = User(username="bunq-user", password_hash="x")
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.routers.banking.SUPER_ADMIN_USERNAME", user.username)
    state = {}

    def start_authorization(**kwargs):
        state["value"] = kwargs["state"]
        return {"url": "https://bank.example/authorize"}

    monkeypatch.setattr(enable_banking, "find_bank", lambda name, country: {"name": "bunq"})
    monkeypatch.setattr(enable_banking, "consent_days_for", lambda bank: 90)
    monkeypatch.setattr(enable_banking, "start_authorization", start_authorization)
    monkeypatch.setattr(enable_banking, "get_account_details", _details)
    monkeypatch.setattr(enable_banking, "get_session", lambda session_id: {"accounts": [], "accounts_data": []})
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    try:
        yield client, db, state, monkeypatch
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _authorize(client, state, monkeypatch, accounts):
    monkeypatch.setattr(enable_banking, "create_session",
                        lambda code: {"session_id": "sess-1", "accounts": accounts})
    assert client.post("/banking/connect", data={"bank_name": "bunq", "bank_country": "NL"}).status_code == 302
    return client.get("/banking/callback", params={"code": "auth-code", "state": state["value"]})


def test_callback_shows_and_stores_unavailable_account(banking_client, caplog):
    client, db, state, monkeypatch = banking_client

    with caplog.at_level(logging.INFO, logger="app.routers.banking"):
        response = _authorize(client, state, monkeypatch, [SAVINGS_WITHOUT_UID, SAVINGS_WITH_UID])

    assert response.status_code == 200
    assert "Van 1 van de 2 rekening(en)" in response.text
    assert "NL11BUNQ0000000001" in response.text
    assert "Bank levert geen transacties voor deze rekening" in response.text
    conn = db.query(BankConnection).one()
    stored = json.loads(conn.accounts_json)
    assert [a["available"] for a in stored] == [False, True]
    assert "2 rekening(en) ontvangen, 1 op te halen; #1 Spaarrekening zonder uid, #2 Spaarrekening met uid" in caplog.text
    assert "NL11BUNQ" not in caplog.text and "uid-savings-2" not in caplog.text

    sync_page = client.get(f"/banking/sync/{conn.id}")
    assert sync_page.status_code == 200
    assert sync_page.text.count("<option value=") == 1
    assert 'value="uid-savings-2"' in sync_page.text
    assert "De bank levert geen transacties voor" in sync_page.text


def test_callback_without_fetchable_accounts_is_not_reported_as_success(banking_client):
    client, db, state, monkeypatch = banking_client

    response = _authorize(client, state, monkeypatch, [SAVINGS_WITHOUT_UID])

    assert "levert voor geen van de rekeningen transacties" in response.text
    assert "Transacties ophalen</a>" not in response.text
    conn = db.query(BankConnection).one()
    sync_page = client.get(f"/banking/sync/{conn.id}")
    assert "Deze koppeling heeft geen rekeningen waarvan transacties op te halen zijn" in sync_page.text


def test_callback_adds_account_listed_only_in_session_lookup(banking_client, caplog):
    client, db, state, monkeypatch = banking_client
    monkeypatch.setattr(enable_banking, "get_session", lambda session_id: {
        "accounts": ["uid-savings-2", "uid-savings-3"],
        "accounts_data": [{"uid": "uid-savings-2"}, {"uid": "uid-savings-3"}],
    })

    with caplog.at_level(logging.INFO, logger="app.routers.banking"):
        response = _authorize(client, state, monkeypatch, [SAVINGS_WITH_UID])

    assert "Van 2 van de 2 rekening(en)" in response.text
    assert "NL33BUNQ0000000003" in response.text
    stored = json.loads(db.query(BankConnection).one().accounts_json)
    assert [(a["uid"], a["type"]) for a in stored] == [("uid-savings-2", "Spaarrekening"), ("uid-savings-3", "Spaarrekening")]
    assert "2 in accounts, 2 in accounts_data, 1 extra" in caplog.text
    assert "1 rekening(en) met velden [['account_id', 'cash_account_type', 'uid']]" in caplog.text
    assert "uid-savings-3" not in caplog.text


def test_callback_survives_failed_session_lookup(banking_client, caplog):
    client, db, state, monkeypatch = banking_client

    def fail(session_id):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(enable_banking, "get_session", fail)
    with caplog.at_level(logging.WARNING, logger="app.routers.banking"):
        response = _authorize(client, state, monkeypatch, [SAVINGS_WITH_UID])

    assert "Van 1 van de 1 rekening(en)" in response.text
    assert "Enable Banking sessie opvragen mislukt" in caplog.text
