"""
Plaid bank connection router.

Handles bank linking via Plaid Link widget, transaction syncing,
and connection management.
"""

import datetime
import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PlaidConnection, Account, Transaction, Rule
from app.auth import require_login
from app.config import PLAID_CLIENT_ID, PLAID_ENV
from app.plaid_client import (
    create_link_token,
    exchange_public_token,
    get_item,
    get_institution,
    get_accounts,
    sync_transactions,
    parse_plaid_transaction,
    remove_item,
    PlaidError,
)
from app.rules_engine import apply_rules_to_transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plaid")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def plaid_overview(
    request: Request,
    db: Session = Depends(get_db),
):
    """Main bank connection page: show active connections and Link button."""
    user = require_login(request, db)

    connections = (
        db.query(PlaidConnection)
        .filter(PlaidConnection.user_id == user.id)
        .order_by(PlaidConnection.created_at.desc())
        .all()
    )

    configured = bool(PLAID_CLIENT_ID)

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    return templates.TemplateResponse(
        "plaid/connect.html",
        {
            "request": request,
            "user": user,
            "connections": connections,
            "configured": configured,
            "accounts": accounts,
            "plaid_env": PLAID_ENV,
        },
    )


@router.post("/create-link-token")
def api_create_link_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """API endpoint: create a Plaid Link token for the frontend widget."""
    user = require_login(request, db)

    try:
        link_token = create_link_token(user_id=str(user.id))
        return JSONResponse({"link_token": link_token})
    except PlaidError as e:
        logger.error("Failed to create link token: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/exchange-token")
async def api_exchange_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    API endpoint: exchange public_token from Plaid Link for access_token.
    Called by frontend JavaScript after user completes bank authorization.
    """
    user = require_login(request, db)

    body = await request.json()
    public_token = body.get("public_token", "")
    institution_id = body.get("institution_id", "")
    institution_name = body.get("institution_name", "")

    if not public_token:
        return JSONResponse({"error": "Geen public_token ontvangen"}, status_code=400)

    try:
        result = exchange_public_token(public_token)
    except PlaidError as e:
        logger.error("Failed to exchange token: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

    access_token = result["access_token"]
    item_id = result["item_id"]

    # Get institution name if not provided
    if not institution_name and institution_id:
        try:
            inst = get_institution(institution_id)
            institution_name = inst.get("name", institution_id)
        except PlaidError:
            institution_name = institution_id

    if not institution_name:
        institution_name = "Onbekende bank"

    # Get accounts from Plaid
    plaid_accounts = []
    try:
        plaid_accounts = get_accounts(access_token)
    except PlaidError as e:
        logger.warning("Could not fetch accounts: %s", e)

    # Create a connection for each Plaid account (or one if no accounts found)
    if plaid_accounts:
        for pa in plaid_accounts:
            conn = PlaidConnection(
                user_id=user.id,
                institution_id=institution_id or None,
                institution_name=institution_name,
                access_token=access_token,
                item_id=item_id,
                plaid_account_id=pa.get("account_id"),
                status="active",
            )

            # Try to auto-link by IBAN or account name
            mask = pa.get("mask", "")
            pa_name = pa.get("name", "")
            iban = pa.get("iban")

            if iban:
                local = db.query(Account).filter(
                    Account.user_id == user.id, Account.iban == iban
                ).first()
                if local:
                    conn.account_id = local.id

            db.add(conn)
    else:
        conn = PlaidConnection(
            user_id=user.id,
            institution_id=institution_id or None,
            institution_name=institution_name,
            access_token=access_token,
            item_id=item_id,
            status="active",
        )
        db.add(conn)

    db.commit()

    return JSONResponse({"ok": True, "accounts": len(plaid_accounts)})


@router.post("/connections/{connection_id}/link-account")
def link_local_account(
    connection_id: int,
    request: Request,
    account_id: int = Form(0),
    new_account_name: str = Form(""),
    db: Session = Depends(get_db),
):
    """Link a Plaid connection to a local account (existing or new)."""
    user = require_login(request, db)

    conn = db.query(PlaidConnection).filter(
        PlaidConnection.id == connection_id,
        PlaidConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/plaid", status_code=302)

    if account_id:
        account = db.query(Account).filter(
            Account.id == account_id, Account.user_id == user.id
        ).first()
        if account:
            conn.account_id = account.id
    elif new_account_name.strip():
        account = Account(
            user_id=user.id,
            name=new_account_name.strip(),
            iban=None,
            bank="plaid",
        )
        db.add(account)
        db.flush()
        conn.account_id = account.id

    db.commit()
    return RedirectResponse("/plaid", status_code=302)


@router.post("/connections/{connection_id}/sync")
def sync_connection(
    connection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Manually trigger a sync for a single connection."""
    user = require_login(request, db)

    conn = db.query(PlaidConnection).filter(
        PlaidConnection.id == connection_id,
        PlaidConnection.user_id == user.id,
        PlaidConnection.status == "active",
    ).first()
    if not conn:
        return RedirectResponse("/plaid?error=not_found", status_code=302)

    if not conn.account_id:
        return RedirectResponse("/plaid?error=no_local_account", status_code=302)

    try:
        imported, skipped = _sync_single_connection(conn, db)
        return RedirectResponse(
            f"/plaid?success=synced&imported={imported}&skipped={skipped}",
            status_code=302,
        )
    except PlaidError as e:
        logger.error("Sync failed for connection %s: %s", conn.id, e)
        if e.error_code == "ITEM_LOGIN_REQUIRED":
            conn.status = "expired"
            db.commit()
            return RedirectResponse("/plaid?error=expired", status_code=302)
        return RedirectResponse("/plaid?error=sync_failed", status_code=302)


@router.post("/connections/{connection_id}/delete")
def delete_connection(
    connection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a bank connection."""
    user = require_login(request, db)

    conn = db.query(PlaidConnection).filter(
        PlaidConnection.id == connection_id,
        PlaidConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/plaid", status_code=302)

    # Remove item at Plaid (best effort)
    try:
        remove_item(conn.access_token)
    except Exception:
        pass

    db.delete(conn)
    db.commit()
    return RedirectResponse("/plaid", status_code=302)


def _sync_single_connection(conn: PlaidConnection, db: Session) -> tuple[int, int]:
    """
    Sync transactions for a single connection.
    Returns (imported_count, skipped_count).
    """
    if not conn.access_token or not conn.account_id:
        return 0, 0

    result = sync_transactions(conn.access_token, cursor=conn.cursor)

    # Load rules for auto-categorization
    active_rules = (
        db.query(Rule)
        .filter(Rule.user_id == conn.user_id, Rule.is_active == 1)
        .all()
    )

    imported = 0
    skipped = 0

    for raw_tx in result["added"]:
        # If we have a specific plaid_account_id, only import matching transactions
        if conn.plaid_account_id and raw_tx.get("account_id") != conn.plaid_account_id:
            continue

        parsed = parse_plaid_transaction(raw_tx)

        # Check for duplicate
        exists = (
            db.query(Transaction)
            .filter(Transaction.import_hash == parsed["import_hash"])
            .first()
        )
        if exists:
            skipped += 1
            continue

        # Parse date
        try:
            tx_date = date_type.fromisoformat(parsed["date"])
        except (ValueError, TypeError):
            tx_date = date_type.today()

        tx = Transaction(
            account_id=conn.account_id,
            date=tx_date,
            amount=parsed["amount"],
            currency=parsed["currency"],
            description=parsed["description"],
            counterparty=parsed["counterparty"],
            counterparty_iban=parsed["counterparty_iban"],
            balance_after=parsed["balance_after"],
            import_hash=parsed["import_hash"],
        )
        db.add(tx)
        db.flush()

        # Apply rules
        if active_rules:
            apply_rules_to_transaction(active_rules, tx, db)

        imported += 1

    # Update cursor for incremental sync
    conn.cursor = result["next_cursor"]
    conn.last_synced_at = datetime.datetime.utcnow()
    db.commit()

    return imported, skipped


def sync_all_active_connections(db: Session) -> dict:
    """
    Sync all active connections. Called by the scheduler.
    Returns summary dict.
    """
    connections = (
        db.query(PlaidConnection)
        .filter(PlaidConnection.status == "active")
        .all()
    )

    total_imported = 0
    total_skipped = 0
    errors = 0

    for conn in connections:
        if not conn.account_id or not conn.access_token:
            continue

        try:
            imported, skipped = _sync_single_connection(conn, db)
            total_imported += imported
            total_skipped += skipped
            logger.info(
                "Synced connection %s (%s): %d imported, %d skipped",
                conn.id, conn.institution_name, imported, skipped,
            )
        except PlaidError as e:
            errors += 1
            logger.error("Sync failed for connection %s: %s", conn.id, e)
            if e.error_code == "ITEM_LOGIN_REQUIRED":
                conn.status = "expired"
                db.commit()
        except Exception as e:
            errors += 1
            logger.error("Unexpected error syncing connection %s: %s", conn.id, e)

    return {
        "connections": len(connections),
        "imported": total_imported,
        "skipped": total_skipped,
        "errors": errors,
    }
