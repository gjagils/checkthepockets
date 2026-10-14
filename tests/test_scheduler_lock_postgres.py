"""ACT-42b: de advisory lock op een echte PostgreSQL (alleen met POSTGRES_TEST_URL; de CI-job doet dat)."""
import os
import zlib

import pytest
from sqlalchemy import create_engine, text

from app import config
import app.database as database
import app.scheduler as sched

URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL niet gezet")


@pytest.fixture
def pg(monkeypatch):
    engine = create_engine(URL)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(config, "SCHEDULER_LOCK", True)
    yield engine
    engine.dispose()


def _other_process_holds(engine, job_id):
    """Een tweede databasesessie die de lock vasthoudt, zoals een ander proces."""
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    key = zlib.crc32(f"checkthepockets:{job_id}".encode())
    assert conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    return conn, key


def test_a_job_that_runs_elsewhere_is_skipped(pg):
    ran = []

    @sched.logged_job("pg_lock_demo")
    def job():
        ran.append(1)
        return "gedraaid"

    holder, key = _other_process_holds(pg, "pg_lock_demo")
    try:
        assert job() == "overgeslagen: draait al in een ander proces"
        assert ran == []
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        holder.close()
    assert job() == "gedraaid" and ran == [1]                      # na vrijgeven draait hij weer


def test_the_lock_is_released_even_when_the_job_fails(pg):
    @sched.logged_job("pg_lock_fail")
    def broken():
        raise RuntimeError("kapot")

    with pytest.raises(RuntimeError):
        broken()
    with sched.job_lock("pg_lock_fail") as acquired:               # direct opnieuw te pakken
        assert acquired is True


def test_different_jobs_do_not_block_each_other(pg):
    holder, key = _other_process_holds(pg, "pg_lock_a")
    try:
        with sched.job_lock("pg_lock_b") as acquired:
            assert acquired is True
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        holder.close()
