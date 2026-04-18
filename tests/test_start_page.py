"""Tests voor per-user startpagina (GJA-5)."""
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password, user_start_page
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="user", is_admin=0, start_page=None):
    u = User(
        username=username,
        email=f"{username}@x.nl",
        password_hash=hash_password("password123"),
        is_admin=is_admin,
        start_page=start_page,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


def test_user_start_page_default_for_none(db_session):
    u = _make_user(db_session, "alice")
    assert user_start_page(u) == "/dashboard"


def test_user_start_page_respects_saved_value(db_session):
    u = _make_user(db_session, "alice", start_page="/transactions")
    assert user_start_page(u) == "/transactions"


def test_user_start_page_falls_back_on_disallowed_value(db_session):
    u = _make_user(db_session, "alice", start_page="/some-fake-route")
    assert user_start_page(u) == "/dashboard"


def test_user_start_page_admin_only_blocked_for_regular_user(db_session):
    u = _make_user(db_session, "alice", is_admin=0, start_page="/hypotheek")
    assert user_start_page(u) == "/dashboard"


def test_user_start_page_admin_only_allowed_for_admin(db_session):
    u = _make_user(db_session, "admin", is_admin=1, start_page="/hypotheek")
    assert user_start_page(u) == "/hypotheek"


def test_root_redirects_to_user_start_page_when_logged_in(db_session):
    u = _make_user(db_session, "alice", start_page="/budgets")
    resp = _client(u.id).get("/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/budgets"


def test_root_shows_landing_when_logged_out():
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 200


def test_login_redirects_to_start_page(db_session):
    u = _make_user(db_session, "alice", start_page="/savings")

    client = TestClient(app, follow_redirects=False)
    resp = client.post("/login", data={"username": "alice", "password": "password123"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/savings"


def test_settings_shows_start_page_dropdown(db_session):
    u = _make_user(db_session, "alice")
    body = _client(u.id).get("/settings").text
    assert 'name="start_page"' in body
    # Extract de <select>-regio voor de start_page dropdown.
    select_region = body.split('name="start_page"', 1)[1].split("</select>", 1)[0]
    # Admin-only optie mag niet verschijnen voor niet-admin.
    assert "/hypotheek" not in select_region


def test_settings_admin_sees_hypotheek_option(db_session):
    admin = _make_user(db_session, "bob", is_admin=1)
    body = _client(admin.id).get("/settings").text
    select_region = body.split('name="start_page"', 1)[1].split("</select>", 1)[0]
    assert "/hypotheek" in select_region


def test_post_updates_start_page(db_session):
    u = _make_user(db_session, "alice")
    assert u.start_page is None or u.start_page == "/dashboard"

    resp = _client(u.id).post("/settings/start-page", data={"start_page": "/portfolio"})
    assert resp.status_code == 200
    assert "Startpagina opgeslagen" in resp.text

    db_session.expire_all()
    u = db_session.query(User).filter(User.username == "alice").one()
    assert u.start_page == "/portfolio"


def test_post_rejects_disallowed_value(db_session):
    u = _make_user(db_session, "alice")
    resp = _client(u.id).post(
        "/settings/start-page", data={"start_page": "/admin/secret"},
    )
    assert resp.status_code == 400
    assert "Onbekende startpagina-optie" in resp.text

    db_session.expire_all()
    # Value blijft ongewijzigd.
    u = db_session.query(User).filter(User.username == "alice").one()
    assert u.start_page in (None, "/dashboard")


def test_non_admin_cannot_set_admin_only_start_page(db_session):
    u = _make_user(db_session, "alice", is_admin=0)
    resp = _client(u.id).post(
        "/settings/start-page", data={"start_page": "/hypotheek"},
    )
    assert resp.status_code == 400
    db_session.expire_all()
    u = db_session.query(User).filter(User.username == "alice").one()
    assert u.start_page != "/hypotheek"
