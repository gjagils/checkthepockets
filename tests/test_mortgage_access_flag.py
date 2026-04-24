"""Tests voor can_access_mortgage feature-flag (GJA-47)."""
from __future__ import annotations

import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import (
    allowed_start_pages,
    create_session_cookie,
    hash_password,
)
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


def _make_user(db, *, username, is_admin=0, can_access_mortgage=0):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"),
        is_admin=is_admin,
        can_access_mortgage=can_access_mortgage,
        is_verified=1, is_active=1,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ── Route-guard: /hypotheek gate ontkoppeld van is_admin ─────────────────


def test_mortgage_route_accessible_for_flagged_non_admin(db_session):
    user = _make_user(db_session, username="alice", is_admin=0, can_access_mortgage=1)
    resp = _client(user.id).get("/hypotheek")
    # 200 + hypotheek-index template — niet 404
    assert resp.status_code == 200


def test_mortgage_route_404_for_admin_without_flag(db_session):
    """Kern van de ontkoppeling: admin-zijn geeft niet langer toegang tot
    hypotheek. Een admin zonder de flag krijgt 404, net als een gewone user."""
    admin = _make_user(db_session, username="admin", is_admin=1, can_access_mortgage=0)
    resp = _client(admin.id).get("/hypotheek")
    assert resp.status_code == 404


def test_mortgage_route_404_for_regular_user(db_session):
    user = _make_user(db_session, username="bob", is_admin=0, can_access_mortgage=0)
    resp = _client(user.id).get("/hypotheek")
    assert resp.status_code == 404


# ── Toggle-endpoint in admin-router ───────────────────────────────────────


def test_admin_can_toggle_mortgage_access(db_session):
    admin = _make_user(db_session, username="admin", is_admin=1, can_access_mortgage=0)
    target = _make_user(db_session, username="alice", is_admin=0, can_access_mortgage=0)
    target_id = target.id

    client = _client(admin.id)
    resp = client.post(
        f"/admin/users/{target_id}/toggle-mortgage-access",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db_session.expire_all()
    refreshed = db_session.query(User).filter_by(id=target_id).one()
    assert refreshed.can_access_mortgage == 1

    # Tweede toggle: terug naar 0
    client.post(f"/admin/users/{target_id}/toggle-mortgage-access", follow_redirects=False)
    db_session.expire_all()
    refreshed2 = db_session.query(User).filter_by(id=target_id).one()
    assert refreshed2.can_access_mortgage == 0


def test_non_admin_cannot_toggle_mortgage_access(db_session):
    user = _make_user(db_session, username="bob", is_admin=0, can_access_mortgage=0)
    target = _make_user(db_session, username="alice", is_admin=0, can_access_mortgage=0)
    target_id = target.id

    resp = _client(user.id).post(
        f"/admin/users/{target_id}/toggle-mortgage-access",
        follow_redirects=False,
    )
    assert resp.status_code == 403

    db_session.expire_all()
    refreshed = db_session.query(User).filter_by(id=target_id).one()
    assert refreshed.can_access_mortgage == 0


def test_admin_can_toggle_own_mortgage_access(db_session):
    """Anders dan toggle-admin mag een admin wel zijn eigen hypotheek-flag
    zetten — het is persoonlijke-finance, geen admin-privilege."""
    admin = _make_user(db_session, username="admin", is_admin=1, can_access_mortgage=1)
    admin_id = admin.id

    _client(admin_id).post(
        f"/admin/users/{admin_id}/toggle-mortgage-access",
        follow_redirects=False,
    )
    db_session.expire_all()
    refreshed = db_session.query(User).filter_by(id=admin_id).one()
    assert refreshed.can_access_mortgage == 0


# ── START_PAGE_OPTIONS filtert /hypotheek op de flag ────────────────────


def test_start_page_options_hide_hypotheek_without_flag(db_session):
    user = _make_user(db_session, username="bob", is_admin=0, can_access_mortgage=0)
    paths = {o["path"] for o in allowed_start_pages(user)}
    assert "/hypotheek" not in paths
    assert "/dashboard" in paths  # non-gated opties blijven


def test_start_page_options_show_hypotheek_with_flag(db_session):
    user = _make_user(db_session, username="alice", is_admin=0, can_access_mortgage=1)
    paths = {o["path"] for o in allowed_start_pages(user)}
    assert "/hypotheek" in paths


def test_start_page_options_hypotheek_independent_of_admin(db_session):
    """Admin-zonder-flag ziet /hypotheek NIET in de dropdown — bewijst de
    ontkoppeling ook op auth-laag, niet alleen op route-laag."""
    admin = _make_user(db_session, username="admin", is_admin=1, can_access_mortgage=0)
    paths = {o["path"] for o in allowed_start_pages(admin)}
    assert "/hypotheek" not in paths


# ── Nav-link zichtbaarheid in base.html ──────────────────────────────────


def test_nav_shows_hypotheek_link_with_flag(db_session):
    user = _make_user(db_session, username="alice", is_admin=0, can_access_mortgage=1)
    body = _client(user.id).get("/dashboard").text
    assert 'href="/hypotheek"' in body


def test_nav_hides_hypotheek_link_without_flag(db_session):
    admin = _make_user(db_session, username="admin", is_admin=1, can_access_mortgage=0)
    body = _client(admin.id).get("/dashboard").text
    assert 'href="/hypotheek"' not in body
