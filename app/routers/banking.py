"""Enable Banking PSD2 integration — connect bank accounts and sync transactions."""

import json
import logging
import uuid
from datetime import date as date_type, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.config import APP_URL, ENABLE_BANKING_APP_ID, SUPER_ADMIN_USERNAME
from app.database import get_db
from app.models import Account, BankConnection, Transaction, Rule, Category
from app.parsers.base import ParsedTransaction
from app.rules_engine import apply_rules_to_transaction
from app.template_config import templates

router = APIRouter(prefix="/banking")


def _is_configured() -> bool:
    return bool(ENABLE_BANKING_APP_ID)


def _is_banking_allowed(user) -> bool:
    """Only super admin can use banking in restricted mode."""
    return bool(SUPER_ADMIN_USERNAME and user.username == SUPER_ADMIN_USERNAME)


# ── Bank selection page ─────────────────────────────────────────────────────


@router.get("/connect")
def connect_page(request: Request, db: Session = Depends(get_db)):
    """Show available banks to connect."""
    user = require_login(request, db)

    if not _is_banking_allowed(user):
        return templates.TemplateResponse(
            "banking/connect.html",
            {"request": request, "user": user, "banks": [], "connections": [], "restricted": True},
        )

    if not _is_configured():
        return templates.TemplateResponse(
            "banking/connect.html",
            {"request": request, "user": user, "connections": [], "error": "Enable Banking is niet geconfigureerd."},
        )

    # Get existing connections for this user
    connections = db.query(BankConnection).filter(
        BankConnection.user_id == user.id,
        BankConnection.status.in_(["active", "pending"]),
    ).all()

    return templates.TemplateResponse(
        "banking/connect.html",
        {"request": request, "user": user, "connections": connections},
    )


# ── Start authorization ─────────────────────────────────────────────────────


@router.post("/connect")
async def start_connect(request: Request, db: Session = Depends(get_db)):
    """Start PSD2 authorization for a selected bank."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    form = await request.form()
    bank_name = form.get("bank_name", "").strip()
    bank_country = form.get("bank_country", "NL").strip()

    if not bank_name:
        return RedirectResponse("/banking/connect", status_code=302)

    state = str(uuid.uuid4())
    redirect_url = f"{APP_URL}/banking/callback"

    # Store state in session for CSRF protection
    request.session["eb_state"] = state
    request.session["eb_bank_name"] = bank_name
    request.session["eb_bank_country"] = bank_country

    from app import enable_banking
    try:
        result = enable_banking.start_authorization(
            bank_name=bank_name,
            bank_country=bank_country,
            redirect_url=redirect_url,
            state=state,
        )
    except Exception as e:
        return templates.TemplateResponse(
            "banking/connect.html",
            {
                "request": request, "user": user, "banks": [],
                "connections": [],
                "error": f"Kan autorisatie niet starten: {e}",
            },
        )

    # Create pending connection
    conn = BankConnection(
        user_id=user.id,
        bank_name=bank_name,
        bank_country=bank_country,
        status="pending",
    )
    db.add(conn)
    db.commit()
    request.session["eb_connection_id"] = conn.id

    return RedirectResponse(result["url"], status_code=302)


# ── OAuth callback ──────────────────────────────────────────────────────────


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    """Handle redirect from bank after PSD2 authorization."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)

    # Verify state
    expected_state = request.session.get("eb_state")
    if not state or state != expected_state:
        return templates.TemplateResponse(
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": "Ongeldige state parameter. Probeer opnieuw."},
        )

    if not code:
        return templates.TemplateResponse(
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": "Geen autorisatiecode ontvangen. Heb je de koppeling geweigerd?"},
        )

    connection_id = request.session.get("eb_connection_id")
    conn = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == user.id,
    ).first() if connection_id else None

    from app import enable_banking
    try:
        session_data = enable_banking.create_session(code)
    except Exception as e:
        if conn:
            conn.status = "revoked"
            db.commit()
        return templates.TemplateResponse(
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": f"Kan sessie niet aanmaken: {e}"},
        )

    session_id = session_data.get("session_id")
    accounts = session_data.get("accounts", [])

    # Enrich accounts with details (IBAN, name)
    enriched_accounts = []
    for acc in accounts:
        uid = acc.get("uid") or acc.get("account_uid")
        if not uid:
            continue
        try:
            details = enable_banking.get_account_details(uid)
            # Enable Banking kan account_id als dict OF als lijst teruggeven,
            # en verschillende banken gebruiken verschillende velden.
            iban = ""
            acc_id = details.get("account_id")
            if isinstance(acc_id, dict):
                iban = acc_id.get("iban") or acc_id.get("IBAN") or ""
            elif isinstance(acc_id, list):
                for entry in acc_id:
                    if isinstance(entry, dict):
                        iban = entry.get("iban") or entry.get("IBAN") or ""
                        if iban:
                            break
            if not iban:
                iban = details.get("iban") or ""
            name = details.get("account_servicer", {}).get("bic_fi", "") if isinstance(details.get("account_servicer"), dict) else ""
        except Exception:
            iban = ""
            name = ""
        enriched_accounts.append({"uid": uid, "iban": iban, "name": name})

    if conn:
        conn.session_id = session_id
        conn.accounts_json = json.dumps(enriched_accounts)
        conn.status = "active"
        conn.valid_until = datetime.utcnow() + timedelta(days=90)
        db.commit()

    # Clean up session
    for key in ["eb_state", "eb_bank_name", "eb_bank_country", "eb_connection_id"]:
        request.session.pop(key, None)

    return templates.TemplateResponse(
        "banking/result.html",
        {
            "request": request, "user": user,
            "success": True,
            "bank_name": conn.bank_name if conn else "Bank",
            "accounts": enriched_accounts,
            "connection_id": conn.id if conn else None,
        },
    )


# ── Sync transactions ───────────────────────────────────────────────────────


@router.get("/sync/{connection_id}")
def sync_page(connection_id: int, request: Request, db: Session = Depends(get_db)):
    """Show sync options for a bank connection."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    conn = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == user.id,
        BankConnection.status == "active",
    ).first()
    if not conn:
        return RedirectResponse("/banking/connect", status_code=302)

    accounts = json.loads(conn.accounts_json or "[]")
    return templates.TemplateResponse(
        "banking/sync.html",
        {"request": request, "user": user, "connection": conn, "accounts": accounts},
    )


@router.post("/sync/{connection_id}")
async def sync_transactions(connection_id: int, request: Request, db: Session = Depends(get_db)):
    """Fetch and import transactions from a connected bank account."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    form = await request.form()

    conn = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == user.id,
        BankConnection.status == "active",
    ).first()
    if not conn:
        return RedirectResponse("/banking/connect", status_code=302)

    account_uid = form.get("account_uid", "")
    date_from = form.get("date_from", "")
    date_to = form.get("date_to", "")

    if not account_uid:
        return RedirectResponse(f"/banking/sync/{connection_id}", status_code=302)

    # Find IBAN for this account from stored data
    stored_accounts = json.loads(conn.accounts_json or "[]")
    account_info = next((a for a in stored_accounts if a["uid"] == account_uid), None)
    account_iban = account_info["iban"] if account_info else None

    from app import enable_banking
    logger.info("Bank sync gestart: %s account=%s from=%s to=%s", conn.bank_name, account_uid, date_from, date_to)
    try:
        raw_transactions = enable_banking.get_transactions(
            account_uid,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        logger.info("Bank sync: %d ruwe transacties opgehaald", len(raw_transactions))
    except Exception as e:
        logger.error("Bank sync fout: %s", e)
        return templates.TemplateResponse(
            "banking/sync.html",
            {
                "request": request, "user": user,
                "connection": conn,
                "accounts": stored_accounts,
                "error": f"Kan transacties niet ophalen: {e}",
            },
        )

    # Map to ParsedTransaction
    parsed = _map_eb_transactions(raw_transactions)

    # Filter op datum (API geeft soms meer terug dan gevraagd)
    if date_from:
        parsed = [p for p in parsed if str(p.date) >= date_from]
    if date_to:
        parsed = [p for p in parsed if str(p.date) <= date_to]

    logger.info("Bank sync: %d transacties na datumfilter", len(parsed))

    if not parsed:
        return templates.TemplateResponse(
            "banking/sync.html",
            {
                "request": request, "user": user,
                "connection": conn,
                "accounts": stored_accounts,
                "error": "Geen transacties gevonden voor de geselecteerde periode.",
            },
        )

    # Find or create the Account record. We matchen primair op external_uid
    # (de stabiele Enable Banking account_uid) zodat meerdere rekeningen bij
    # dezelfde bank, of rekeningen zonder IBAN, nooit samenvallen.
    bank_key = conn.bank_name.lower().replace(" ", "_")
    display = (conn.display_name or conn.bank_name).strip()
    preferred_name = f"{display} - {account_iban}" if account_iban else display
    account = db.query(Account).filter(
        Account.user_id == user.id,
        Account.external_uid == account_uid,
    ).first()
    if not account and account_iban:
        # Legacy fallback: account dat eerder is aangemaakt zonder external_uid
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.bank == bank_key,
            Account.iban == account_iban,
            Account.external_uid.is_(None),
        ).first()
        if account:
            account.external_uid = account_uid
    if account:
        if account_iban and not account.iban:
            account.iban = account_iban
        # Synchroniseer de naam met de connection-display_name, tenzij de
        # gebruiker het account handmatig een custom naam heeft gegeven.
        autogen_prefixes = (f"{conn.bank_name} -", f"{display} -", f"{conn.bank_name}",)
        if account.name == f"{conn.bank_name} - account" or any(
            account.name.startswith(p) for p in autogen_prefixes
        ):
            account.name = preferred_name
    else:
        account = Account(
            user_id=user.id,
            name=preferred_name,
            iban=account_iban or None,
            bank=bank_key,
            external_uid=account_uid,
        )
        db.add(account)
        db.flush()

    # Import transactions (skip duplicates)
    active_rules = db.query(Rule).filter(Rule.user_id == user.id, Rule.is_active == 1).all()
    imported = skipped = auto_categorized = 0

    for p in parsed:
        exists = db.query(Transaction).filter(Transaction.import_hash == p.import_hash).first()
        if exists:
            skipped += 1
            continue

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
            if db_tx.category_id is not None:
                auto_categorized += 1

        imported += 1

    conn.last_synced_at = datetime.utcnow()
    db.commit()

    # Draai alle regels nogmaals over alle transacties (vangt rename → match
    # ketens en categoriseert eerder geïmporteerde transacties waarvoor nu
    # een matchende regel bestaat). We houden dit aantal apart zodat het niet
    # in het 'auto-gecategoriseerd bij deze import' getal wordt geteld.
    from app.rules_engine import apply_rules_to_all
    extra = apply_rules_to_all(db, user.id)
    if extra:
        logger.info("Bank sync: %d extra bestaande transacties gecategoriseerd via apply_rules_to_all", extra)

    # Auto-link recurring and sync projections
    from app.routers.transactions import auto_link_recurring_after_import
    from app.routers.recurring import cleanup_matched_projected, sync_projected_transactions
    auto_link_recurring_after_import(db, user.id)
    cleanup_matched_projected(user.id, db)
    # Re-sync projected transactions for current month to reflect new imports
    _today = date_type.today()
    sync_projected_transactions(user.id, _today.year, _today.month, db)
    db.commit()

    return templates.TemplateResponse(
        "banking/sync_result.html",
        {
            "request": request, "user": user,
            "imported": imported,
            "skipped": skipped,
            "auto_categorized": auto_categorized,
            "extra_categorized": extra,
            "total": len(parsed),
            "account": account,
            "connection": conn,
        },
    )


# ── Rename connection ──────────────────────────────────────────────────────


@router.post("/rename/{connection_id}")
async def rename_connection(connection_id: int, request: Request, db: Session = Depends(get_db)):
    """Rename a bank connection (custom display name)."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    form = await request.form()
    display_name = form.get("display_name", "").strip()

    conn = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/banking/connect", status_code=302)

    old_display = (conn.display_name or conn.bank_name).strip()
    conn.display_name = display_name or None
    new_display = (conn.display_name or conn.bank_name).strip()

    # Auto-rename linked accounts (alleen de auto-gegenereerde namen,
    # handmatig aangepaste account-namen laten we staan).
    try:
        stored_accounts = json.loads(conn.accounts_json or "[]")
    except Exception:
        stored_accounts = []
    uids = [a.get("uid") for a in stored_accounts if a.get("uid")]
    if uids:
        linked = db.query(Account).filter(
            Account.user_id == user.id,
            Account.external_uid.in_(uids),
        ).all()
        autogen_starts = (
            f"{old_display} -", f"{old_display}",
            f"{conn.bank_name} -", f"{conn.bank_name}",
        )
        for acc in linked:
            if any(acc.name.startswith(p) for p in autogen_starts) or acc.name == f"{conn.bank_name} - account":
                acc.name = f"{new_display} - {acc.iban}" if acc.iban else new_display
    db.commit()

    return RedirectResponse("/banking/connect", status_code=302)


# ── Disconnect ──────────────────────────────────────────────────────────────


@router.post("/disconnect/{connection_id}")
def disconnect(connection_id: int, request: Request, db: Session = Depends(get_db)):
    """Revoke consent and deactivate a bank connection."""
    user = require_login(request, db)
    if not _is_banking_allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    conn = db.query(BankConnection).filter(
        BankConnection.id == connection_id,
        BankConnection.user_id == user.id,
    ).first()
    if not conn:
        return RedirectResponse("/banking/connect", status_code=302)

    if conn.session_id:
        from app import enable_banking
        try:
            enable_banking.delete_session(conn.session_id)
        except Exception:
            pass

    conn.status = "revoked"
    conn.session_id = None
    db.commit()

    return RedirectResponse("/banking/connect", status_code=302)


# ── Transaction mapping ─────────────────────────────────────────────────────


def _map_eb_transactions(raw: list[dict]) -> list[ParsedTransaction]:
    """Map Enable Banking API transaction objects to ParsedTransaction."""
    result = []
    for tx in raw:
        try:
            # Date: booking_date or value_date
            date_str = tx.get("booking_date") or tx.get("value_date") or tx.get("transaction_date")
            if not date_str:
                continue
            tx_date = date_type.fromisoformat(date_str[:10])

            # Amount
            amount_obj = tx.get("transaction_amount") or {}
            amount_str = amount_obj.get("amount", "0")
            currency = amount_obj.get("currency", "EUR")
            amount = Decimal(amount_str)

            # Credit/debit indicator
            if tx.get("credit_debit_indicator") == "DBIT" and amount > 0:
                amount = -amount

            # Description
            desc_parts = []
            if tx.get("remittance_information"):
                info = tx["remittance_information"]
                if isinstance(info, list):
                    desc_parts.extend(info)
                elif isinstance(info, dict):
                    desc_parts.extend(info.get("unstructured", []))
                else:
                    desc_parts.append(str(info))
            if tx.get("additional_information"):
                desc_parts.append(tx["additional_information"])
            description = " ".join(desc_parts).strip() or "Geen omschrijving"

            # Counterparty
            counterparty = None
            counterparty_iban = None
            creditor = tx.get("creditor") or {}
            debtor = tx.get("debtor") or {}
            party = creditor or debtor
            if party:
                counterparty = party.get("name")
            creditor_acc = tx.get("creditor_account") or {}
            debtor_acc = tx.get("debtor_account") or {}
            party_acc = creditor_acc or debtor_acc
            if party_acc:
                counterparty_iban = party_acc.get("iban")

            # Balance after (if available)
            balance_after = None
            if tx.get("balance_after_transaction"):
                bal = tx["balance_after_transaction"]
                bal_amount = bal.get("balance_amount", {})
                if bal_amount.get("amount"):
                    try:
                        balance_after = Decimal(bal_amount["amount"])
                    except (InvalidOperation, ValueError):
                        pass

            result.append(ParsedTransaction(
                date=tx_date,
                amount=amount,
                currency=currency,
                description=description,
                counterparty=counterparty,
                counterparty_iban=counterparty_iban,
                balance_after=balance_after,
            ))
        except (ValueError, InvalidOperation, KeyError):
            continue

    return result
