"""ACT-38b: 'vandaag' is de Nederlandse datum, niet die van de UTC-container."""
import datetime

from app import clock


class _Fake:
    """datetime-module dat 'nu' vastzet op 31 maart 22:30 UTC (= 1 april 00:30 in Nederland)."""

    timezone = datetime.timezone
    date = datetime.date

    class datetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime.datetime(2026, 3, 31, 22, 30, tzinfo=datetime.timezone.utc)
            return moment.astimezone(tz) if tz else moment


def test_today_nl_is_already_the_next_day_after_22_utc(monkeypatch):
    monkeypatch.setattr(clock, "datetime", _Fake)
    assert clock.today_nl() == datetime.date(2026, 4, 1)          # date.today() in UTC gaf 31 maart
    assert clock.now_utc() == datetime.datetime(2026, 3, 31, 22, 30)


def test_now_utc_is_naive_and_current():
    now = clock.now_utc()
    assert now.tzinfo is None
    assert abs((datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - now).total_seconds()) < 5


def test_no_deprecated_time_calls_left_in_app():
    import pathlib
    offenders = []
    for path in pathlib.Path("app").rglob("*.py"):
        if path.name == "clock.py":
            continue
        text = path.read_text()
        for needle in ("utcnow(", ".today()"):
            if needle in text:
                offenders.append(f"{path}: {needle}")
    assert offenders == []


def test_scheduler_really_schedules_in_amsterdam_time(monkeypatch):
    """APScheduler 3.11 draait zonder pytz; de schedules moeten nog steeds op NL-tijd staan."""
    from apscheduler.schedulers.background import BackgroundScheduler

    import app.scheduler as sched

    fresh = BackgroundScheduler(timezone=sched.NL_TZ)
    monkeypatch.setattr(sched, "scheduler", fresh)
    sched.start_scheduler()
    try:
        jobs = {job.id: job for job in fresh.get_jobs()}
        assert {"bunq_sync", "wealth_plan_january"} <= set(jobs)
        nxt = jobs["bunq_sync"].next_run_time
        assert nxt is not None and nxt.utcoffset() == nxt.astimezone(clock.NL_TZ).utcoffset()
        assert (nxt.hour, nxt.minute) in {(1, 30), (17, 30)}          # 01:30 en 17:30 Amsterdam
    finally:
        if fresh.running:
            fresh.shutdown(wait=False)
