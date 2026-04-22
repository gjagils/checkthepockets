"""Tests voor scheduler-log decorator + admin dashboard (LIN-42)."""
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import SchedulerRunLog, User
from app.scheduler import logged_job


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(SchedulerRunLog).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="admin", is_admin=1):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"), is_admin=is_admin,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ──────────────────────────────────────────────────────────────────────────────
# Decorator-unit-tests
# ──────────────────────────────────────────────────────────────────────────────

def test_logged_job_writes_ok_log_on_success(db_session):
    @logged_job("unit_ok")
    def doer():
        return "deed 7 dingen"

    doer()

    logs = db_session.query(SchedulerRunLog).filter(SchedulerRunLog.job_id == "unit_ok").all()
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "ok"
    assert log.summary == "deed 7 dingen"
    assert log.started_at is not None
    assert log.finished_at is not None
    assert log.finished_at >= log.started_at


def test_logged_job_writes_error_log_and_reraises(db_session):
    @logged_job("unit_err")
    def doer():
        raise RuntimeError("boem")

    with pytest.raises(RuntimeError, match="boem"):
        doer()

    log = (
        db_session.query(SchedulerRunLog)
        .filter(SchedulerRunLog.job_id == "unit_err")
        .one()
    )
    assert log.status == "error"
    assert "RuntimeError" in (log.summary or "")
    assert "boem" in (log.summary or "")
    assert log.finished_at is not None


def test_logged_job_accepts_none_return(db_session):
    @logged_job("unit_none")
    def doer():
        return None

    doer()

    log = db_session.query(SchedulerRunLog).filter(SchedulerRunLog.job_id == "unit_none").one()
    assert log.status == "ok"
    assert log.summary == ""


def test_logged_job_truncates_long_summary(db_session):
    @logged_job("unit_long")
    def doer():
        return "x" * 10_000

    doer()

    log = db_session.query(SchedulerRunLog).filter(SchedulerRunLog.job_id == "unit_long").one()
    assert log.status == "ok"
    assert len(log.summary) == 5000


# ──────────────────────────────────────────────────────────────────────────────
# Admin-route tests
# ──────────────────────────────────────────────────────────────────────────────

def test_admin_scheduler_requires_admin(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    resp = _client(user.id).get("/admin/scheduler")
    assert resp.status_code == 403


def test_admin_scheduler_renders_empty_state(db_session):
    admin = _make_user(db_session, "admin", is_admin=1)
    resp = _client(admin.id).get("/admin/scheduler")
    assert resp.status_code == 200
    body = resp.text
    assert "Scheduler" in body
    assert "Ingeplande jobs" in body
    assert "Recente runs" in body


def test_admin_scheduler_shows_recent_runs(db_session):
    admin = _make_user(db_session, "admin", is_admin=1)

    @logged_job("test_job")
    def doer():
        return "alles goed"

    doer()

    resp = _client(admin.id).get("/admin/scheduler")
    body = resp.text
    assert "test_job" in body
    assert "OK" in body
    assert "alles goed" in body


def test_admin_scheduler_run_unknown_job_redirects_with_error(db_session):
    admin = _make_user(db_session, "admin", is_admin=1)
    resp = _client(admin.id).post(
        "/admin/scheduler/run",
        data={"job_id": "no_such_job"},
    )
    assert resp.status_code == 302
    assert "error=unknown_job" in resp.headers["location"]


def test_admin_scheduler_run_triggers_known_job(db_session, monkeypatch):
    """Klik op 'Run nu' voor bank_sync → decorator schrijft een log-rij.

    We monkeypatchen de onderliggende sync-functie zodat we niet de echte
    Enable Banking-flow aanraken.
    """
    admin = _make_user(db_session, "admin", is_admin=1)

    # Vervang de gedecoreerde functie door een trivial doer + decorator.
    @logged_job("bank_sync")
    def fake_sync():
        return "0 tx geïmporteerd uit 0 koppeling(en)"

    monkeypatch.setattr("app.scheduler._sync_all_bank_connections", fake_sync)

    resp = _client(admin.id).post(
        "/admin/scheduler/run",
        data={"job_id": "bank_sync"},
    )
    assert resp.status_code == 302
    assert "flash=triggered" in resp.headers["location"]

    log = (
        db_session.query(SchedulerRunLog)
        .filter(SchedulerRunLog.job_id == "bank_sync")
        .order_by(SchedulerRunLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.status == "ok"
    assert "0 tx" in log.summary


def test_admin_scheduler_run_requires_admin(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    resp = _client(user.id).post(
        "/admin/scheduler/run",
        data={"job_id": "bank_sync"},
    )
    assert resp.status_code == 403
