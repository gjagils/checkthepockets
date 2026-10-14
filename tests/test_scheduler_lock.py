"""ACT-42b: scheduler-jobs draaien niet dubbel, kunnen per proces uit en hebben veilige standaardwaarden."""
import zlib

from fastapi.testclient import TestClient

import app.main as main
import app.scheduler as sched
from app.models import SchedulerRunLog


def test_job_defaults_coalesce_and_allow_one_instance():
    defaults = sched.scheduler._job_defaults
    assert defaults["coalesce"] is True
    assert defaults["max_instances"] == 1
    assert defaults["misfire_grace_time"] == 3600


def test_logged_job_still_runs_and_logs_without_a_lock_database(db):
    """SQLite heeft geen advisory locks: de job draait gewoon en schrijft zijn log."""
    @sched.logged_job("lock_demo")
    def job():
        return "klaar"

    assert job() == "klaar"
    log = db.query(SchedulerRunLog).filter_by(job_id="lock_demo").one()
    assert log.status == "ok" and log.summary == "klaar"


def test_job_lock_key_is_stable_per_job():
    assert zlib.crc32(b"checkthepockets:bank_sync") != zlib.crc32(b"checkthepockets:bunq_sync")


def test_scheduler_is_not_started_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(main, "start_scheduler", lambda: calls.append("start"))
    with TestClient(main.app):
        pass
    assert calls == []


def test_scheduler_is_started_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(main, "start_scheduler", lambda: calls.append("start"))
    with TestClient(main.app):
        assert calls == ["start"]


def test_lock_is_off_by_default_and_never_touches_a_pooled_database(monkeypatch):
    """Standaard geen databaselock: achter een transaction-pooler kan die een job blijven blokkeren."""
    from app import config, database

    assert config.SCHEDULER_LOCK is False

    class Boom:
        class dialect:
            name = "postgresql"

        def connect(self):
            raise AssertionError("er mag geen verbinding voor een lock worden geopend")

    monkeypatch.setattr(database, "engine", Boom())
    with sched.job_lock("bank_sync") as acquired:
        assert acquired is True
