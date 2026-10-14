"""ACT-33: auth-fixes uit de codereview (A5, B1, B2, B3, B6, B7, B8, B10)."""
import datetime
import os
import tempfile
from types import SimpleNamespace

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient
from starlette.requests import Request

import app.email_service as email_service
import app.routers.auth as auth_router
from app import rate_limit
from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import AuthToken, User


@pytest.fixture(autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    rate_limit._buckets.clear()
    rate_limit._login_failures.clear()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _request(peer, xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def _invite(db, token="invite-1"):
    db.add(AuthToken(user_id=None, token=token, token_type="invite",
                     expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=1)))
    db.commit()
    return token


def _register(client, **overrides):
    data = {"username": "nieuwe_gebruiker", "email": "", "password": "wachtwoord123",
            "password_confirm": "wachtwoord123", "invite": "invite-1"}
    data.update(overrides)
    return client.post("/register", data=data, follow_redirects=False)


# ── A5 ─────────────────────────────────────────────────────────────────────

def test_typo_does_not_burn_the_invite(db, monkeypatch):
    monkeypatch.setattr(auth_router, "REGISTRATION_OPEN", False)
    _invite(db)
    client = TestClient(app)
    assert _register(client, password_confirm="anders").status_code == 400
    assert db.query(AuthToken).one().used_at is None            # niet verbrand
    assert _register(client).status_code == 302                 # lukt met dezelfde link
    db.expire_all()
    assert db.query(AuthToken).one().used_at is not None
    assert _register(client, username="tweede").status_code == 400   # eenmalig


# ── B10 ────────────────────────────────────────────────────────────────────

def test_email_is_normalised_and_unique_ignoring_case(db, monkeypatch):
    monkeypatch.setattr(auth_router, "REGISTRATION_OPEN", True)
    client = TestClient(app)
    assert _register(client, username="  eerste  ", email=" A@X.nl ").status_code == 302
    user = db.query(User).one()
    assert user.username == "eerste" and user.email == "a@x.nl"
    dup = _register(client, username="tweede", email="a@x.NL")
    assert dup.status_code == 400
    assert _register(client, username="derde", email="geen-email").status_code == 400


# ── B3 ─────────────────────────────────────────────────────────────────────

def test_register_is_rate_limited(db, monkeypatch):
    monkeypatch.setattr(auth_router, "REGISTRATION_OPEN", True)
    client = TestClient(app)
    codes = [_register(client, username=f"gebruiker{i}", email=f"u{i}@x.nl").status_code for i in range(7)]
    assert codes[:5] == [302] * 5 and codes[5:] == [429, 429]


def test_forgot_password_sends_no_mail_when_limited_and_shows_same_page(db, monkeypatch):
    db.add(User(username="mailer", password_hash=hash_password("x" * 10), email="m@x.nl"))
    db.commit()
    sent = []
    monkeypatch.setattr(auth_router, "send_password_reset_email", lambda to, token: sent.append(to))
    client = TestClient(app)
    pages = [client.post("/forgot-password", data={"email": "M@x.nl"}) for _ in range(5)]
    assert all(p.status_code == 200 for p in pages)
    assert len(sent) == 3                                       # per adres maximaal 3 per uur


# ── B1 ─────────────────────────────────────────────────────────────────────

def test_google_login_needs_a_verified_email(db, monkeypatch):
    db.add(User(username="bestaand", password_hash=hash_password("x" * 10), email="victim@x.nl"))
    db.commit()

    class FakeOAuth:
        def __init__(self, verified):
            self.verified = verified

        async def authorize_access_token(self, request):
            return {"userinfo": {"email": "Victim@x.nl", "email_verified": self.verified, "name": "V"}}

    client = TestClient(app, follow_redirects=False)
    monkeypatch.setattr(auth_router, "_google_oauth", FakeOAuth(False))
    refused = client.get("/auth/google/callback")
    assert refused.status_code == 200 and "niet geverifieerd" in refused.text
    assert "session" not in refused.cookies

    monkeypatch.setattr(auth_router, "_google_oauth", FakeOAuth(True))
    accepted = client.get("/auth/google/callback")
    assert accepted.status_code == 302 and "session" in accepted.cookies   # gewoon match, ook op hoofdletters


# ── B2 ─────────────────────────────────────────────────────────────────────

def test_client_ip_only_trusts_forwarded_header_from_private_peers():
    # Proxy (privé) achter Cloudflare: meest rechtse publieke adres, links is door de client te vervalsen.
    assert auth_router._client_ip(_request("192.168.48.3", "6.6.6.6, 1.1.1.1, 10.0.0.5")) == "1.1.1.1"
    assert auth_router._client_ip(_request("192.168.48.3", "10.1.1.1")) == "192.168.48.3"
    assert auth_router._client_ip(_request("192.168.48.3")) == "192.168.48.3"
    # Direct publiek verbonden: de header telt niet.
    assert auth_router._client_ip(_request("8.8.8.8", "1.2.3.4")) == "8.8.8.8"
    assert auth_router._client_ip(_request("testclient", "1.2.3.4")) == "testclient"


# ── B7 / B8 ────────────────────────────────────────────────────────────────

def test_logout_needs_post(db):
    user = User(username="uitlogger", password_hash=hash_password("x" * 10))
    db.add(user)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    got = client.get("/logout")
    assert got.status_code == 302 and got.headers["location"] == "/"
    assert "set-cookie" not in got.headers                      # GET logt niet uit
    posted = client.post("/logout")
    assert posted.status_code == 303 and "session=" in posted.headers["set-cookie"]


def test_delete_all_transactions_shortcut_is_gone(db):
    user = User(username="wisser", password_hash=hash_password("x" * 10))
    db.add(user)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    assert client.post("/accounts/delete-all-transactions").status_code in (404, 405)


# ── B6 ─────────────────────────────────────────────────────────────────────

def test_mail_html_escapes_user_supplied_names(monkeypatch):
    captured = []
    monkeypatch.setattr(email_service, "_send", lambda to, subject, html: captured.append(html) or True)
    email_service.send_invite_email("a@x.nl", "tok", "<script>alert(1)</script>")
    email_service.send_weekly_digest("a@x.nl", "<b>naam</b>", [("<i>rekening</i>", 2)], 2, 3)
    joined = "\n".join(captured)
    assert "<script>" not in joined and "<b>naam</b>" not in joined and "<i>rekening</i>" not in joined
    assert "&lt;script&gt;" in joined
