"""
Nordigen / GoCardless bank connection router.

Handles bank linking via OAuth flow, transaction syncing,
and connection management.
"""

import datetime
import logging
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import NordigenConnection, Account, Transaction, Rule
from app.auth import require_login
from app.config import NORDIGEN_SECRET_ID
from app.nordigen_client import (
    get_institutions,
    create_requisition,
    get_requisition,
    get_account_details,
    get_transactions,
    parse_nordigen_transaction,
    delete_requisition,
    NordigenError,
)
from app.rules_engine import apply_rules_to_transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nordigen")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def nordigen_overview(
    request: Request,
    country: str = Query("NL"),
    db: Session = Depends(get_db),
):
    """Main bank connection page: list institutions and active connections."""
    user = require_login(request, db)

    # Get active connections
    connections = (
        db.query(NordigenConnection)
        .filter(NordigenConnection.user_id == user.id)
        .order_by(NordigenConnection.created_at.desc())
        .all()
    )

    # Check if Nordigen is configured
    configured = bool(NORDIGEN_SECRET_ID)

    # Fetch institutions list (only if configured)
    institutions = []
    institution_error = None
    if configured:
        try:
            institutions = get_institutions(country)
        except NordigenError as e:
            institution_error = str(e)
        except Exception as e:
            institution_error = f"Kan bankenlijst niet laden: {e}"

    # Get user's accounts for linking
    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    return templates.TemplateResponse(
        "nordigen/connect.html",
        {
            "request": request,
            "user": user,
            "connections": connections,
            "institutions": institutions,
            "institution_error": institution_error,
            "configured": configured,
            "accounts": accounts,
            "country": country,
            "now": datetime.datetime.utcnow(),
        },
    )


@router.post("/link")
def link_bank(
    request: Request,
    institution_id: str = Form(...),
    institution_name: str = Form(""),
    db: Session = Depends(get_db),
):
    """Create a Nordigen requisition and redirect user to bank OAuth."""
    user = require_login(request, db)

    # Build callback URL
    base_url = str(request.base_url).rstrip("/")
    redirect_url = f"{base_url}/nordigen/callback"

    try:
        result = create_requisition(
            institution_id=institution_id,
            redirect_url=redirect_url,
            reference=f"ctp-{user.id}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        )
    except NordigenError as e:
        logger.error("Failed to create requisition: %s", e)
        return RedirectResponse("/nordigen?error=requisition_failed", status_code=302)

    # Calculate access validity
    access_days = result.get("_access_valid_for_days", 90)
    access_valid_until = datetime.datetime.utcnow() + datetime.timedelta(days=access_days)

    # Save connection as pending
    conn = NordigenConnection(
        user_id=user.id,
        institution_id=institution_id,
        institution_name=institution_name.strip() or institution_id,
        requisition_id=result["id"],
        status="pending",
        access_valid_until=access_valid_until,
    )
    db.add(conn)
    db.commit()

    # Redirect user to bank authorization page
    link = result.get("link")
    if not link:
        return RedirectResponse("/nordigen?error=no_link", status_code=302)

    return RedirectResponse(link, status_code=302)


@router.get("/callback")
def nordigen_callback(
    request: Request,
    ref: str = Query(""),
    db: Session = Depends(get_db),
):
    """Handle return from bank OAuth. Activate connection and fetch accounts."""
    user = require_login(request, db)

    # Find the most recent pending connection for this user
    conn = (
        db.query(NordigenConnection)
        .filter(
            NordigenConnection.user_id == user.id,
            NordigenConnection.status == "pending",
        )
        .order_by(NordigenConnection.created_at.desc())
        .first()
    )

    if not conn:
        return RedirectResponse("/nordigen?error=no_pending", status_code=302)

    try:
        req_data = get_requisition(conn.requisition_id)
    except NordigenError as e:
        logger.error("Failed to get requisition %s: %s", conn.requisition_id, e)
        conn.status = "error"
        db.commit()
        return RedirectResponse("/nordigen?error=requisition_fetch_failed", status_code=302)

    status = req_data.get("status", "")
    accounts_list = req_data.get("accounts", [])

    if status != "LN" or not accounts_list:
        # LN = Linked. If not linked, mark as error
        if status in ("CR", "GC", "UA"):
            # Still in progress - user may not have completed auth
            return RedirectResponse("/nordigen?error=auth_incomplete", status_code=302)
        conn.status = "error"
        db.commit()
        return RedirectResponse("/nordigen?error=link_failed", status_code=302)

    # Use the first account (most banks have one main account)
    nordigen_account_id = accounts_list[0]
    conn.nordigen_account_id = nordigen_account_id
    conn.status = "active"

    # Try to fetch account details for IBAN
    try:
        details = get_account_details(nordigen_account_id)
        conn.iban = details.get("iban")
    except NordigenError:
        pass

    # Auto-link to existing local account by IBAN
    if conn.iban:
        local_account = (
            db.query(Account)
            .filter(Account.user_id == user.id, Account.iban == conn.iban)
            .first()
        )
        if local_account:
            conn.account_id = local_account.id

    # If multiple accounts, create additional connections
    for extra_acc_id in accounts_list[1:]:
        extra_conn = NordigenConnection(
            user_id=user.id,
            institution_id=conn.institution_id,
            institution_name=conn.institution_name,
            requisition_id=conn.requisition_id,
            nordigen_account_id=extra_acc_id,
            status="active",
            access_valid_until=conn.access_valid_until,
        )
        # Try to get IBAN for extra account
        try:
            extra_details = get_account_details(extra_acc_id)
            extra_conn.iban = extra_details.get("iban")
            if extra_conn.iban:
                local_acc = (
                    db.query(Account)
                    .filter(Account.user_id == user.id, Account.iban == extra_conn.iban)
                    .first()
                )
                if local_acc:
                    extra_conn.account_id = local_acc.id
        except NordigenError:
            pass
        db.add(extra_conn)

    db.commit()
    return RedirectResponse("/nordigen?success=linked", status_code=302)


@router.post("/connections/{connection_id}/link-account")
def link_local_account(
    connection_id: int,
    request: Request,
    account_id: int = Form(0),
    new_account_name: str = Form(""),
    db: Session = Depends(get_db),
):
    """Link a Nordigen connection to a local account (existing or new)."""
    user = require_login(request, db)

    conn = db.query(NordigenConnection).filter(
        NordigenConnection.id == connection_id,
        NordigenConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/nordigen", status_code=302)

    if account_id:
        # Link to existing account
        account = db.query(Account).filter(
            Account.id == account_id, Account.user_id == user.id
        ).first()
        if account:
            conn.account_id = account.id
    elif new_account_name.strip():
        # Create new account
        account = Account(
            user_id=user.id,
            name=new_account_name.strip(),
            iban=conn.iban,
            bank="nordigen",
        )
        db.add(account)
        db.flush()
        conn.account_id = account.id

    db.commit()
    return RedirectResponse("/nordigen", status_code=302)


@router.post("/connections/{connection_id}/sync")
def sync_connection(
    connection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Manually trigger a sync for a single connection."""
    user = require_login(request, db)

    conn = db.query(NordigenConnection).filter(
        NordigenConnection.id == connection_id,
        NordigenConnection.user_id == user.id,
        NordigenConnection.status == "active",
    ).first()
    if not conn:
        return RedirectResponse("/nordigen?error=not_found", status_code=302)

    if not conn.account_id:
        return RedirectResponse("/nordigen?error=no_local_account", status_code=302)

    try:
        imported, skipped = _sync_single_connection(conn, db)
        return RedirectResponse(
            f"/nordigen?success=synced&imported={imported}&skipped={skipped}",
            status_code=302,
        )
    except NordigenError as e:
        logger.error("Sync failed for connection %s: %s", conn.id, e)
        if e.status_code == 401:
            conn.status = "expired"
            db.commit()
            return RedirectResponse("/nordigen?error=expired", status_code=302)
        return RedirectResponse("/nordigen?error=sync_failed", status_code=302)


@router.post("/connections/{connection_id}/delete")
def delete_connection(
    connection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a bank connection."""
    user = require_login(request, db)

    conn = db.query(NordigenConnection).filter(
        NordigenConnection.id == connection_id,
        NordigenConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/nordigen", status_code=302)

    # Try to delete requisition at Nordigen (best effort)
    try:
        delete_requisition(conn.requisition_id)
    except Exception:
        pass

    db.delete(conn)
    db.commit()
    return RedirectResponse("/nordigen", status_code=302)


def _sync_single_connection(conn: NordigenConnection, db: Session) -> tuple[int, int]:
    """
    Sync transactions for a single connection.
    Returns (imported_count, skipped_count).
    """
    if not conn.nordigen_account_id or not conn.account_id:
        return 0, 0

    # Determine date_from for incremental sync
    date_from = None
    if conn.last_synced_at:
        date_from = conn.last_synced_at.strftime("%Y-%m-%d")

    raw_transactions = get_transactions(conn.nordigen_account_id, date_from=date_from)

    # Load rules for auto-categorization
    active_rules = (
        db.query(Rule)
        .filter(Rule.user_id == conn.user_id, Rule.is_active == 1)
        .all()
    )

    imported = 0
    skipped = 0

    for raw_tx in raw_transactions:
        parsed = parse_nordigen_transaction(raw_tx)

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

    conn.last_synced_at = datetime.datetime.utcnow()
    db.commit()

    return imported, skipped


def sync_all_active_connections(db: Session) -> dict:
    """
    Sync all active connections. Called by the scheduler.
    Returns summary dict.
    """
    connections = (
        db.query(NordigenConnection)
        .filter(NordigenConnection.status == "active")
        .all()
    )

    total_imported = 0
    total_skipped = 0
    errors = 0

    for conn in connections:
        if not conn.account_id or not conn.nordigen_account_id:
            continue

        # Check if access has expired
        if conn.access_valid_until and conn.access_valid_until < datetime.datetime.utcnow():
            conn.status = "expired"
            db.commit()
            continue

        try:
            imported, skipped = _sync_single_connection(conn, db)
            total_imported += imported
            total_skipped += skipped
            logger.info(
                "Synced connection %s (%s): %d imported, %d skipped",
                conn.id, conn.institution_name, imported, skipped,
            )
        except NordigenError as e:
            errors += 1
            logger.error("Sync failed for connection %s: %s", conn.id, e)
            if e.status_code == 401:
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
