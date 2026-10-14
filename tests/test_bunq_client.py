"""bunq API-koppeling (ACT-31a): client, opslag en routes met een nagebootste bunq."""
import base64
import json
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

import app.routers.bunq as bunq_router
from app.auth import create_session_cookie
from app.bunq_client import BunqClient, BunqError, generate_private_key_pem
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import BunqConnection, User

API_KEY = "sandbox_0123456789abcdef0123456789abcdef"

ACCOUNTS = {"Response": [
    {"MonetaryAccountBank": {
        "id": 11, "description": "Samen", "status": "ACTIVE",
        "balance": {"value": "123.45", "currency": "EUR"},
        "alias": [{"type": "EMAIL", "value": "a@b.nl"}, {"type": "IBAN", "value": "NL01BUNQ0000000011"}]}},
    {"MonetaryAccountSavings": {
        "id": 12, "description": "Spaar 2", "status": "ACTIVE",
        "balance": {"value": "5000.00", "currency": "EUR"},
        "alias": [{"type": "IBAN", "value": "NL01BUNQ0000000012"}]}},
]}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeBunq:
    """Replays bunq; records requests. `reject_sessions` makes the first N session-server calls 401."""

    def __init__(self, reject_sessions=0):
        self.calls = []
        self.reject_sessions = reject_sessions
        self.client_public_key = None

    def request(self, method, url, headers=None, data=None, timeout=None):
        path = url.split("/v1", 1)[1]
        self.calls.append((method, path, dict(headers), data))
        if path == "/installation":
            self.client_public_key = json.loads(data)["client_public_key"]
            return FakeResponse(200, {"Response": [{"Id": {"id": 1}}, {"Token": {"token": "inst-token"}}]})
        if path == "/device-server":
            return FakeResponse(200, {"Response": [{"Id": {"id": 2}}]})
        if path == "/session-server":
            if self.reject_sessions:
                self.reject_sessions -= 1
                return FakeResponse(401, {"Error": [{"error_description": "Incorrect API key or IP address."}]})
            return FakeResponse(200, {"Response": [
                {"Id": {"id": 3}}, {"Token": {"token": "session-token"}}, {"UserPerson": {"id": 77}}]})
        if path.startswith("/user/77/monetary-account"):
            return FakeResponse(200, ACCOUNTS)
        return FakeResponse(404, {"Error": [{"error_description": "nope"}]})


@pytest.fixture(autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_connect_lists_all_account_kinds_and_signs_posts():
    fake = FakeBunq()
    client = BunqClient("https://api.bunq.test/v1", http=fake)
    session = client.connect(API_KEY)
    accounts = client.list_accounts(session)

    assert [(a.kind, a.iban, str(a.balance)) for a in accounts] == [
        ("MonetaryAccountBank", "NL01BUNQ0000000011", "123.45"),
        ("MonetaryAccountSavings", "NL01BUNQ0000000012", "5000.00"),
    ]
    assert [c[1] for c in fake.calls[:3]] == ["/installation", "/device-server", "/session-server"]

    public_key = serialization.load_pem_public_key(fake.client_public_key.encode())
    for method, path, headers, data in fake.calls:
        if path in ("/device-server", "/session-server"):
            signature = base64.b64decode(headers["X-Bunq-Client-Signature"])
            public_key.verify(signature, data.encode(), padding.PKCS1v15(), hashes.SHA256())  # raises if wrong
    assert fake.calls[1][2]["X-Bunq-Client-Authentication"] == "inst-token"
    assert fake.calls[-1][2]["X-Bunq-Client-Authentication"] == "session-token"


def test_rejected_stored_installation_registers_again_once():
    fake = FakeBunq(reject_sessions=1)
    client = BunqClient("https://api.bunq.test/v1", http=fake)
    session = client.connect(API_KEY, private_key_pem=generate_private_key_pem(), installation_token="old-token")
    assert session.token == "session-token"
    paths = [c[1] for c in fake.calls]
    assert paths.count("/installation") == 1 and paths.count("/session-server") == 2


def test_unreadable_stored_key_registers_again():
    fake = FakeBunq()
    client = BunqClient("https://api.bunq.test/v1", http=fake)
    session = client.connect(API_KEY, private_key_pem="kapot", installation_token="old-token")
    assert session.token == "session-token"
    assert [c[1] for c in fake.calls].count("/installation") == 1


def test_error_message_has_no_secrets():
    fake = FakeBunq(reject_sessions=5)
    client = BunqClient("https://api.bunq.test/v1", http=fake)
    with pytest.raises(BunqError) as excinfo:
        client.connect(API_KEY)
    assert API_KEY not in str(excinfo.value)
    assert excinfo.value.kind == "auth"


def _client_for(user, monkeypatch, fake, admin=True, encryption=True):
    monkeypatch.setattr(bunq_router, "SUPER_ADMIN_USERNAME", user.username if admin else "someone-else")
    monkeypatch.setattr(bunq_router, "encryption_enabled", lambda: encryption)
    monkeypatch.setattr(bunq_router, "BunqClient", lambda base: BunqClient("https://api.bunq.test/v1", http=fake))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


def _user(db, name="bunq-user"):
    user = User(username=name, password_hash="x")
    db.add(user)
    db.commit()
    return user


def test_route_saves_key_checks_and_shows_savings_account(monkeypatch):
    db = SessionLocal()
    try:
        user = _user(db)
        fake = FakeBunq()
        client = _client_for(user, monkeypatch, fake)

        assert client.post("/banking/bunq", data={"api_key": API_KEY}).status_code == 302
        page = client.post("/banking/bunq/check")
        assert page.status_code == 200
        assert "Spaar 2" in page.text and "NL01BUNQ0000000012" in page.text
        assert API_KEY not in page.text

        db.expire_all()
        connection = db.query(BunqConnection).one()
        assert connection.last_status == "ok"
        assert connection.installation_token == "inst-token" and connection.private_key_pem

        assert client.post("/banking/bunq/delete").status_code == 302
        db.expire_all()
        assert db.query(BunqConnection).count() == 0
    finally:
        db.close()


def test_route_refuses_to_store_key_without_encryption(monkeypatch):
    db = SessionLocal()
    try:
        user = _user(db)
        client = _client_for(user, monkeypatch, FakeBunq(), encryption=False)
        page = client.post("/banking/bunq", data={"api_key": API_KEY})
        assert page.status_code == 200 and "geweigerd" in page.text
        assert db.query(BunqConnection).count() == 0
    finally:
        db.close()


def test_route_is_admin_only(monkeypatch):
    db = SessionLocal()
    try:
        user = _user(db)
        client = _client_for(user, monkeypatch, FakeBunq(), admin=False)
        assert client.post("/banking/bunq", data={"api_key": API_KEY}).status_code == 302
        assert db.query(BunqConnection).count() == 0
    finally:
        db.close()
