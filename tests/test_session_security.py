"""Regression tests for account deactivation and session revocation."""
import os
import tempfile

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ["SECRET_KEY"] = "session-security-test"

from fastapi import Request

from app.auth import create_session_cookie, get_current_user, revoke_sessions
from app.database import Base, SessionLocal, engine
from app.models import User


def _request(cookie: str) -> Request:
    scope = {"type": "http", "headers": [(b"cookie", f"session={cookie}".encode())]}
    return Request(scope)


def test_deactivated_user_cannot_use_existing_cookie():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(username="inactive-session", password_hash="x", is_active=1)
        db.add(user)
        db.commit()
        cookie = create_session_cookie(user.id)
        user.is_active = 0
        db.commit()
        assert get_current_user(_request(cookie), db) is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_revoked_cookie_is_invalid_but_new_version_works():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(username="revoked-session", password_hash="x", is_active=1)
        db.add(user)
        db.commit()
        old_cookie = create_session_cookie(user.id, user.session_version)
        revoke_sessions(user)
        db.commit()
        assert get_current_user(_request(old_cookie), db) is None
        new_cookie = create_session_cookie(user.id, user.session_version)
        assert get_current_user(_request(new_cookie), db).id == user.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
