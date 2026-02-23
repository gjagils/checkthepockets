"""
Background scheduler for periodic tasks.

Uses APScheduler to run daily bank transaction syncs.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _daily_plaid_sync():
    """Sync all active Plaid bank connections."""
    from app.routers.plaid import sync_all_active_connections

    db = SessionLocal()
    try:
        result = sync_all_active_connections(db)
        logger.info(
            "Daily Plaid sync: %d connections, %d imported, %d skipped, %d errors",
            result["connections"],
            result["imported"],
            result["skipped"],
            result["errors"],
        )
    except Exception as e:
        logger.error("Daily Plaid sync failed: %s", e)
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler with all configured jobs."""
    from app.config import PLAID_CLIENT_ID

    if PLAID_CLIENT_ID:
        scheduler.add_job(
            _daily_plaid_sync,
            "cron",
            hour=6,
            minute=0,
            id="plaid_daily_sync",
            replace_existing=True,
        )
        logger.info("Plaid daily sync scheduled at 06:00")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))
    else:
        logger.info("No scheduled jobs configured, scheduler not started")
