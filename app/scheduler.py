"""
Background scheduler for periodic tasks.

Uses APScheduler to run scheduled background jobs.
"""

import json
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import ENABLE_BANKING_APP_ID

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


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

        # Auto-link recurring for all synced users, then sync projections
        synced_user_ids = {c.user_id for c in connections}
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
            id="bank_sync",
            replace_existing=True,
        )
        logger.info("Bank sync ingepland om 01:00 en 17:00")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))
    else:
        logger.info("No scheduled jobs configured, scheduler not started")
