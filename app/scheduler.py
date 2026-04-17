"""
Background scheduler for periodic tasks.

Uses APScheduler to run scheduled background jobs.
"""

import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone as pytz_timezone

from app.config import ENABLE_BANKING_APP_ID

logger = logging.getLogger(__name__)

NL_TZ = pytz_timezone("Europe/Amsterdam")
scheduler = BackgroundScheduler(timezone=NL_TZ)


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
    from app.routers.inbox import inbox_count

    today = (now_utc or datetime.utcnow()).date()
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


def _run_weekly_digests():
    """Hourly tick: stuurt een digest naar users waarvan nu het ingestelde
    dag+uur (Europe/Amsterdam) overeenkomt en die hem de afgelopen 6 dagen
    nog niet hebben gehad. Skip lege weken (0 nieuw + 0 uncat)."""
    from app.database import SessionLocal
    from app.models import User
    from app.email_service import send_weekly_digest

    now_nl = datetime.now(NL_TZ)
    now_weekday = now_nl.weekday()
    now_hour = now_nl.hour
    threshold = datetime.utcnow() - timedelta(days=6)

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
            return

        for user in candidates:
            if user.weekly_digest_last_sent_at and user.weekly_digest_last_sent_at > threshold:
                continue
            per_account, uncat_total, new_total = compute_digest_stats(db, user.id)
            if new_total == 0 and uncat_total == 0:
                continue
            sent = send_weekly_digest(
                to=user.email,
                username=user.username,
                per_account=per_account,
                uncat_total=uncat_total,
                new_total=new_total,
            )
            if sent:
                user.weekly_digest_last_sent_at = datetime.utcnow()
                db.commit()
                logger.info("Weekly digest verzonden naar %s (new=%d, uncat=%d)",
                            user.email, new_total, uncat_total)
            else:
                logger.warning("Weekly digest verzenden faalde voor %s", user.email)
    except Exception as e:
        logger.error("Weekly digest run faalde: %s", e)
        db.rollback()
    finally:
        db.close()


def _sync_all_bank_connections():
    """Sync transactions for all active bank connections."""
    from app.database import SessionLocal
    from app.models import Account, BankConnection, Transaction, Rule
    from app.parsers.base import ParsedTransaction
    from app.rules_engine import apply_rules_to_transaction

    db = SessionLocal()
    try:
        connections = db.query(BankConnection).filter(
            BankConnection.status == "active",
            BankConnection.session_id.isnot(None),
        ).all()

        if not connections:
            logger.info("Bank sync: geen actieve koppelingen gevonden")
            return

        from app import enable_banking
        from app.routers.banking import _map_eb_transactions

        for conn in connections:
            accounts = json.loads(conn.accounts_json or "[]")
            for acc_info in accounts:
                uid = acc_info.get("uid")
                if not uid:
                    continue

                try:
                    raw = enable_banking.get_transactions(uid)
                    parsed = _map_eb_transactions(raw)
                except Exception as e:
                    logger.error("Bank sync fout voor %s/%s: %s", conn.bank_name, uid, e)
                    continue

                if not parsed:
                    continue

                # Find or create account
                iban = acc_info.get("iban")
                bank_key = conn.bank_name.lower().replace(" ", "_")
                account = db.query(Account).filter(
                    Account.user_id == conn.user_id,
                    Account.iban == iban,
                ).first()
                if not account:
                    account = Account(
                        user_id=conn.user_id,
                        name=f"{conn.bank_name} - {iban or 'account'}",
                        iban=iban,
                        bank=bank_key,
                    )
                    db.add(account)
                    db.flush()

                active_rules = db.query(Rule).filter(
                    Rule.user_id == conn.user_id, Rule.is_active == 1
                ).all()

                imported = 0
                for p in parsed:
                    exists = db.query(Transaction).filter(
                        Transaction.import_hash == p.import_hash
                    ).first()
                    if exists:
                        continue

                    from decimal import Decimal
                    db_tx = Transaction(
                        account_id=account.id,
                        date=p.date,
                        amount=p.amount,
                        currency=p.currency,
                        description=p.description,
                        counterparty=p.counterparty,
                        counterparty_iban=p.counterparty_iban,
                        balance_after=p.balance_after,
                        import_hash=p.import_hash,
                    )
                    db.add(db_tx)
                    db.flush()

                    if active_rules:
                        apply_rules_to_transaction(active_rules, db_tx, db)
                    imported += 1

                if imported:
                    logger.info("Bank sync: %d transacties geimporteerd voor %s (%s)",
                                imported, conn.bank_name, iban)

            conn.last_synced_at = datetime.utcnow()

        db.commit()

        # Draai alle regels nogmaals (vangt rename → match ketens)
        synced_user_ids = {c.user_id for c in connections}
        from app.rules_engine import apply_rules_to_all
        for user_id in synced_user_ids:
            extra = apply_rules_to_all(db, user_id)
            if extra:
                logger.info("Bank sync: %d extra transacties gecategoriseerd voor user %d", extra, user_id)

        # Auto-link recurring, then sync projections
        from app.routers.transactions import auto_link_recurring_after_import
        from app.routers.recurring import cleanup_matched_projected, sync_projected_transactions
        today = datetime.utcnow().date()
        for user_id in synced_user_ids:
            auto_link_recurring_after_import(db, user_id)
            cleanup_matched_projected(user_id, db)
            sync_projected_transactions(user_id, today.year, today.month, db)
        db.commit()

        logger.info("Bank sync voltooid voor %d koppelingen", len(connections))

    except Exception as e:
        logger.error("Bank sync mislukt: %s", e)
        db.rollback()
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
        _run_weekly_digests,
        "cron",
        minute=0,
        timezone=NL_TZ,
        id="weekly_digest",
        replace_existing=True,
    )
    logger.info("Weekly digest tick ingepland elk heel uur (Europe/Amsterdam)")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))
    else:
        logger.info("No scheduled jobs configured, scheduler not started")
