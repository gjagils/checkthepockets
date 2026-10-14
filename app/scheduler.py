"""
Background scheduler for periodic tasks.

Uses APScheduler to run scheduled background jobs.
"""

import functools
import zlib
from contextlib import contextmanager
import logging
import traceback
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app import clock
from app.config import ENABLE_BANKING_APP_ID

logger = logging.getLogger(__name__)

NL_TZ = clock.NL_TZ  # zoneinfo; APScheduler 3.11 heeft pytz niet meer nodig
# Eén run per job tegelijk; gemiste runs (bijv. na een herstart) binnen een uur nog inhalen, maar maximaal
# één keer ("coalesce") in plaats van elke gemiste run apart.
scheduler = BackgroundScheduler(
    timezone=NL_TZ,
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
)

_SUMMARY_MAX_LEN = 5000


@contextmanager
def job_lock(job_id: str):
    """Yield True when this process may run `job_id`, False when another process already does.

    A PostgreSQL session-level advisory lock on a dedicated autocommit connection, held for the whole
    job. With `--workers N` or a second container every process has its own scheduler; without this
    each job would run N times (double bank imports, double digest mails). Off unless SCHEDULER_LOCK=true
    (see config: session locks misbehave behind a transaction pooler such as Neon's), and other databases
    (SQLite in tests) have no lock: always True.
    """
    from sqlalchemy import text

    from app import config, database

    engine = database.engine
    if not config.SCHEDULER_LOCK or engine.dialect.name != "postgresql":
        yield True
        return
    key = zlib.crc32(f"checkthepockets:{job_id}".encode())
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    acquired = False
    try:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
        yield acquired
    finally:
        try:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        finally:
            conn.close()


def logged_job(job_id: str):
    """Decorator die start + eindlog schrijft naar `scheduler_run_log`.

    De onderliggende job-functie mag een korte status-string returnen
    (bv. `"3 digests verzonden"`); die wordt opgeslagen in `summary`.
    Bij een exception wordt de traceback bewaard en de fout verder
    geraised zodat APScheduler zelf ook z'n `job_error`-hooks triggert.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with job_lock(job_id) as acquired:
                if not acquired:
                    logger.info("Scheduler job %s draait al in een ander proces; overgeslagen", job_id)
                    return "overgeslagen: draait al in een ander proces"
                return _run_logged(fn, job_id, *args, **kwargs)

        def _run_logged(fn, job_id, *args, **kwargs):
            from app.database import SessionLocal
            from app.models import SchedulerRunLog

            db = SessionLocal()
            log = SchedulerRunLog(
                job_id=job_id,
                status="running",
                started_at=clock.now_utc(),
            )
            db.add(log)
            db.commit()
            db.refresh(log)

            try:
                result = fn(*args, **kwargs)
                log.status = "ok"
                log.summary = (str(result) if result is not None else "")[:_SUMMARY_MAX_LEN]
                return result
            except Exception:
                log.status = "error"
                log.summary = traceback.format_exc()[:_SUMMARY_MAX_LEN]
                logger.exception("Scheduler job %s faalde", job_id)
                raise
            finally:
                log.finished_at = clock.now_utc()
                try:
                    db.commit()
                finally:
                    db.close()

        return wrapper

    return decorator


def compute_digest_stats(db, user_id: int, now_utc: datetime | None = None):
    """Compute (per_account, uncat_total, new_total) voor de weekly digest.

    - per_account: lijst van (account_naam, aantal nieuwe transacties in de
      laatste 7 dagen o.b.v. boekdatum). Accounts zonder nieuwe transacties
      worden weggelaten.
    - uncat_total: totaal aantal transacties in de inbox (zonder categorie,
      excl. splits/projecties/excluded).
    - new_total: som van per_account.
    """
    from sqlalchemy import func
    from app.models import Account, Transaction
    from app.transaction_queries import inbox_count

    today = (now_utc or clock.now_utc()).date()
    since = today - timedelta(days=7)

    rows = (
        db.query(Account.name, func.count(Transaction.id))
        .join(Transaction, Transaction.account_id == Account.id)
        .filter(
            Account.user_id == user_id,
            Transaction.date >= since,
            Transaction.is_projected == 0,
            Transaction.is_excluded == 0,
        )
        .group_by(Account.name)
        .order_by(func.count(Transaction.id).desc(), Account.name)
        .all()
    )
    per_account = [(name, int(cnt)) for name, cnt in rows]
    new_total = sum(c for _, c in per_account)
    uncat_total = inbox_count(db, user_id)
    return per_account, uncat_total, new_total


@logged_job("weekly_digest")
def _run_weekly_digests():
    """Hourly tick: stuurt een digest naar users waarvan nu het ingestelde
    dag+uur (Europe/Amsterdam) overeenkomt en die hem de afgelopen 6 dagen
    nog niet hebben gehad. Skip lege weken (0 nieuw + 0 uncat).

    Returns een korte string met aantallen voor de scheduler-log.
    """
    from app.database import SessionLocal
    from app.models import User
    from app.email_service import send_weekly_digest

    now_nl = datetime.now(NL_TZ)
    now_weekday = now_nl.weekday()
    now_hour = now_nl.hour
    threshold = clock.now_utc() - timedelta(days=6)

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    db = SessionLocal()
    try:
        candidates = (
            db.query(User)
            .filter(
                User.weekly_digest_enabled == 1,
                User.is_active == 1,
                User.email.isnot(None),
                User.weekly_digest_weekday == now_weekday,
                User.weekly_digest_hour == now_hour,
            )
            .all()
        )
        if not candidates:
            return "geen kandidaten voor dit uur"

        for user in candidates:
            if user.weekly_digest_last_sent_at and user.weekly_digest_last_sent_at > threshold:
                skipped_count += 1
                continue
            per_account, uncat_total, new_total = compute_digest_stats(db, user.id)
            if new_total == 0 and uncat_total == 0:
                skipped_count += 1
                continue
            sent = send_weekly_digest(
                to=user.email,
                username=user.username,
                per_account=per_account,
                uncat_total=uncat_total,
                new_total=new_total,
            )
            if sent:
                user.weekly_digest_last_sent_at = clock.now_utc()
                db.commit()
                sent_count += 1
                logger.info("Weekly digest verzonden naar %s (new=%d, uncat=%d)",
                            user.email, new_total, uncat_total)
            else:
                failed_count += 1
                logger.warning("Weekly digest verzenden faalde voor %s", user.email)
    finally:
        db.close()

    return (
        f"{sent_count} verzonden, {failed_count} mislukt, {skipped_count} overgeslagen "
        f"({len(candidates)} kandidaten)"
    )


@logged_job("wealth_plan_january")
def _capture_january_wealth_plans():
    """Freeze missing yearly wealth baselines on the first day of January."""
    from app.database import SessionLocal
    from app.wealth_plan_service import capture_january_wealth_plans

    db = SessionLocal()
    try:
        captured = capture_january_wealth_plans(db)
        return f"{captured} vermogensplan(nen) vastgelegd"
    finally:
        db.close()


@logged_job("bank_sync")
def _sync_all_bank_connections():
    """Sync transactions for all active bank connections.

    Uses the same service as the manual sync page (app/bank_sync.py): ImportBatch per import, status
    fields on the connection, IBAN matching, and one failing account never undoes the others.
    Returns a short string with counts for the scheduler log.
    """
    from app import bank_sync
    from app.database import SessionLocal
    from app.models import BankConnection

    db = SessionLocal()
    try:
        connections = db.query(BankConnection).filter(
            BankConnection.status == "active",
            BankConnection.session_id.isnot(None),
        ).all()
        if not connections:
            logger.info("Bank sync: geen actieve koppelingen gevonden")
            return "geen actieve koppelingen"

        imported = failed = 0
        user_ids: set[int] = set()
        for conn in connections:
            try:
                results = bank_sync.sync_connection(db, conn)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Bank sync mislukt voor koppeling id=%s", conn.id)
                failed += 1
                continue
            imported += sum(r.imported for r in results)
            failed += sum(1 for r in results if r.status == "fetch_error")
            if any(r.status == "ok" for r in results):
                user_ids.add(conn.user_id)

        for user_id in user_ids:
            try:
                bank_sync.post_import(db, user_id)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Bank sync: vervolgstappen mislukt voor user %s", user_id)

        logger.info("Bank sync voltooid voor %d koppelingen", len(connections))
        return f"{imported} tx geïmporteerd uit {len(connections)} koppeling(en), {failed} mislukt"
    finally:
        db.close()


@logged_job("bunq_sync")
def _sync_all_bunq():
    """Import new payments of all selected bunq accounts (ACT-31b)."""
    from app.bunq_client import BunqClient, BunqError
    from app.bunq_sync import sync_connection
    from app.config import BUNQ_API_BASE
    from app.database import SessionLocal
    from app.models import BunqAccountLink, BunqConnection

    db = SessionLocal()
    try:
        connections = [
            c for c in db.query(BunqConnection).all()
            if db.query(BunqAccountLink).filter_by(connection_id=c.id, enabled=1).count()
        ]
        if not connections:
            return "geen bunq-koppelingen met geselecteerde rekeningen"
        total = 0
        for connection in connections:
            try:
                reports = sync_connection(db, connection, BunqClient(BUNQ_API_BASE), dry_run=False)
                db.commit()
                total += sum(r.new for r in reports)
            except BunqError as exc:
                db.rollback()
                logger.warning("bunq sync mislukt (%s, HTTP %s)", exc.kind, exc.status)
            except Exception:
                db.rollback()
                logger.exception("bunq sync mislukt")
        return f"{total} bunq-transacties geïmporteerd uit {len(connections)} koppeling(en)"
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler with all configured jobs."""
    if ENABLE_BANKING_APP_ID:
        scheduler.add_job(
            _sync_all_bank_connections,
            "cron",
            hour="1,17",
            minute=0,
            timezone=NL_TZ,
            id="bank_sync",
            replace_existing=True,
        )
        logger.info("Bank sync ingepland om 01:00 en 17:00 Europe/Amsterdam")

    scheduler.add_job(
        _sync_all_bunq,
        "cron",
        hour="1,17",
        minute=30,
        timezone=NL_TZ,
        id="bunq_sync",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_weekly_digests,
        "cron",
        minute=0,
        timezone=NL_TZ,
        id="weekly_digest",
        replace_existing=True,
    )
    logger.info("Weekly digest tick ingepland elk heel uur (Europe/Amsterdam)")

    scheduler.add_job(
        _capture_january_wealth_plans,
        "cron",
        month=1,
        day=1,
        hour=0,
        minute=5,
        timezone=NL_TZ,
        id="wealth_plan_january",
        replace_existing=True,
    )
    logger.info("Vermogensplan vastleggen ingepland op 1 januari 00:05 Europe/Amsterdam")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))
    else:
        logger.info("No scheduled jobs configured, scheduler not started")
