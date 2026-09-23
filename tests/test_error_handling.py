"""Fault injection for operational errors and log content (ACT-24)."""
import json
import logging
import os
import tempfile

import pytest
import requests

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app import enable_banking
from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.enable_banking import EnableBankingError, _check, safe_error_message
from app.main import app
from app.models import BankConnection, User

SESSION_ID = "sess-8f3a-secret"
ACCOUNT_UID = "acc-77c1-secret"


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def banking_user(db, monkeypatch):
    user = User(username="bank-admin", password_hash="x")
    db.add(user)
    db.flush()
    conn = BankConnection(
        user_id=user.id, bank_name="Testbank", session_id=SESSION_ID, status="active",
        accounts_json=json.dumps([{"uid": ACCOUNT_UID, "iban": "", "name": ""}]),
    )
    db.add(conn)
    db.commit()
    monkeypatch.setattr("app.routers.banking.SUPER_ADMIN_USERNAME", user.username)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client, conn


def _network_error(path):
    return requests.ConnectionError(f"HTTPSConnectionPool(host='api.enablebanking.com'): Max retries exceeded with url: {path}")


def _assert_no_ids(text):
    assert SESSION_ID not in text
    assert ACCOUNT_UID not in text


def test_api_error_message_hides_ids_and_query():
    class FakeResp:
        ok = False
        status_code = 404
        url = f"https://api.enablebanking.com/accounts/{ACCOUNT_UID}/transactions?continuation_key=abc"
        text = ""

        def json(self):
            return {"error": "NOT_FOUND", "message": "Account not found"}

    with pytest.raises(EnableBankingError) as exc:
        _check(FakeResp())

    message = safe_error_message(exc.value)
    _assert_no_ids(message)
    assert "continuation_key" not in message
    assert "/accounts/<id>/transactions" in message
    assert "NOT_FOUND" in message


def test_network_error_message_hides_request_path():
    message = safe_error_message(_network_error(f"/sessions/{SESSION_ID}"))
    _assert_no_ids(message)
    assert "ConnectionError" in message


def test_disconnect_logs_failed_revocation_without_session_id(db, banking_user, monkeypatch, caplog):
    client, conn = banking_user

    def fail(session_id):
        raise _network_error(f"/sessions/{session_id}")

    monkeypatch.setattr(enable_banking, "delete_session", fail)
    with caplog.at_level(logging.WARNING, logger="app.routers.banking"):
        response = client.post(f"/banking/disconnect/{conn.id}")

    assert response.status_code == 302
    db.expire_all()
    assert db.get(BankConnection, conn.id).status == "revoked"
    assert "Unable to revoke remote banking session" in caplog.text
    _assert_no_ids(caplog.text)


def test_manual_sync_failure_is_stored_and_logged_without_ids(db, banking_user, monkeypatch, caplog):
    client, conn = banking_user

    def fail(account_uid, **kwargs):
        raise _network_error(f"/accounts/{account_uid}/transactions")

    monkeypatch.setattr(enable_banking, "get_transactions", fail)
    with caplog.at_level(logging.INFO, logger="app.routers.banking"):
        response = client.post(f"/banking/sync/{conn.id}", data={"account_uid": ACCOUNT_UID})

    assert response.status_code == 200
    # The owner's page lists their own account UIDs in a form; the error itself must not.
    assert "Kan transacties niet ophalen: verbinding met Enable Banking mislukt (ConnectionError)" in response.text
    db.expire_all()
    stored = db.get(BankConnection, conn.id)
    assert stored.last_sync_status == "error"
    _assert_no_ids(stored.last_sync_error)
    assert "Bank sync fout" in caplog.text
    _assert_no_ids(caplog.text)


def test_scheduler_sync_failure_is_logged_without_account_uid(db, banking_user, monkeypatch, caplog):
    from app.scheduler import _sync_all_bank_connections

    def fail(account_uid, **kwargs):
        raise _network_error(f"/accounts/{account_uid}/transactions")

    monkeypatch.setattr(enable_banking, "get_transactions", fail)
    with caplog.at_level(logging.ERROR, logger="app.scheduler"):
        _sync_all_bank_connections()

    assert "Bank sync fout voor Testbank" in caplog.text
    _assert_no_ids(caplog.text)


def test_inbox_count_failure_is_logged_and_page_still_renders(db, monkeypatch, caplog):
    user = User(username="inbox-fail", password_hash="x")
    db.add(user)
    db.commit()

    def fail(db, user_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.routers.inbox.inbox_count", fail)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = client.get("/info")

    assert response.status_code == 200
    assert "Inbox count unavailable" in caplog.text


def test_landing_logs_session_lookup_failure(monkeypatch, caplog):
    def fail(request, db):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.main.get_current_user", fail)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = TestClient(app, follow_redirects=False).get("/")

    assert response.status_code == 200
    assert "Session lookup failed on landing page" in caplog.text
