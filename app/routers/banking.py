"""Enable Banking PSD2 integration — connect bank accounts and sync transactions."""

import json
import logging
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.config import APP_URL, ENABLE_BANKING_APP_ID, SUPER_ADMIN_USERNAME
from app.database import get_db
from app.models import Account, BankConnection, Transaction, Rule, Category, ImportBatch
from app.parsers.base import ParsedTransaction
from app.enable_banking import safe_error_message
from app.import_service import store_parsed_transactions
from app.template_config import templates

router = APIRouter(prefix="/banking")


def _is_configured() -> bool:
    return bool(ENABLE_BANKING_APP_ID)


def _is_banking_allowed(user) -> bool:
    """Only super admin can use banking in restricted mode."""
    return bool(SUPER_ADMIN_USERNAME and user.username == SUPER_ADMIN_USERNAME)


def _normalize_iban(value: str | None) -> str | None:
    """Canoniek IBAN: spaties weg, uppercase. Voorkomt match-misses door
    verschillen tussen API-responses (NL81 BUNQ 2088 ...) en DB-records
    (NL81BUNQ2088...)."""
    if not value:
        return None
    clean = "".join(value.split()).upper()
    return clean or None


# ── Bank selection page ─────────────────────────────────────────────────────


CONNECT_COUNTRIES = ["NL", "BE", "DE"]


def _render_connect(request: Request, user, db: Session, country: str = "NL", error: str | None = None):
    """Koppelpagina met bestaande koppelingen + banklijst voor het gekozen land.

    De banklijst komt live van Enable Banking zodat de naam in het formulier
    altijd exact overeenkomt met wat /auth verwacht. Als de API niet
    bereikbaar is, blijft de pagina werken (met een lege lijst + melding)."""
    connections = db.query(BankConnection).filter(
        BankConnection.user_id == user.id,
        BankConnection.status.in_(["active", "pending"]),
    ).all()

    banks: list[dict] = []
    if _is_configured():
        from app import enable_banking
        try:
            banks = enable_banking.list_banks(country, psu_type="personal")
        except Exception as e:
            logger.error("Banklijst ophalen mislukt (%s): %s", country, safe_error_message(e))
            error = error or f"Kan banklijst niet ophalen: {safe_error_message(e)}"
    else:
        error = error or "Enable Banking is niet geconfigureerd."

    return templates.TemplateResponse(
        "banking/connect.html",
        {
            "request": request, "user": user,
            "connections": connections,
            "banks": sorted(banks, key=lambda b: b.get("name", "").lower()),
            "country": country,
            "countries": CONNECT_COUNTRIES,
            "error": error,
        },
    )


@router.get("/connect")
def connect_page(request: Request, country: str = "NL", db: Session = Depends(get_db)):
    """Show available banks to connect."""
    user = require_login(request, db)

    if not _is_banking_allowed(user):
        return templates.TemplateResponse(
            "banking/connect.html",
            {"request": request, "user": user, "banks": [], "connections": [], "restricted": True},
        )

    country = country.upper() if country.upper() in CONNECT_COUNTRIES else "NL"
    return _render_connect(request, user, db, country=country)


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

    from app import enable_banking

    # Enable Banking eist de exacte ASPSP-naam ("bunq", niet "Bunq") en geeft
    # anders 422 WRONG_ASPSP_PROVIDED. Zoek daarom case-insensitief op en
    # gebruik de canonieke naam uit de API.
    try:
        bank = enable_banking.find_bank(bank_name, bank_country)
    except Exception as e:
        return _render_connect(request, user, db, country=bank_country,
                               error=f"Kan banklijst niet ophalen: {safe_error_message(e)}")
    if not bank:
        return _render_connect(request, user, db, country=bank_country,
                               error=f"Bank '{bank_name}' niet gevonden voor {bank_country}. Kies een bank uit de lijst.")
    bank_name = bank["name"]
    valid_days = enable_banking.consent_days_for(bank)

    state = str(uuid.uuid4())
    redirect_url = f"{APP_URL}/banking/callback"

    # Store state in session for CSRF protection
    request.session["eb_state"] = state
    request.session["eb_bank_name"] = bank_name
    request.session["eb_bank_country"] = bank_country
    request.session["eb_valid_days"] = valid_days

    try:
        result = enable_banking.start_authorization(
            bank_name=bank_name,
            bank_country=bank_country,
            redirect_url=redirect_url,
            state=state,
            valid_days=valid_days,
        )
    except Exception as e:
        logger.error("Enable Banking /auth mislukt voor %s/%s: %s", bank_name, bank_country, safe_error_message(e))
        return _render_connect(request, user, db, country=bank_country,
                               error=f"Kan autorisatie niet starten: {safe_error_message(e)}")

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


def _consent_valid_until(session_data: dict, fallback_days: int) -> datetime:
    """Werkelijke consent-vervaldatum uit de sessie-response (access.valid_until,
    ISO-8601 met tijdzone) als naïeve UTC — de kolom is timezone-loos en de
    rest van de app gebruikt utcnow(). Valt terug op nu + fallback_days."""
    raw = (session_data.get("access") or {}).get("valid_until")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            logger.warning("Onbegrijpelijke valid_until van Enable Banking: %r", raw)
    return datetime.utcnow() + timedelta(days=fallback_days)


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
        logger.error("Enable Banking sessie aanmaken mislukt: %s", safe_error_message(e))
        if conn:
            conn.status = "revoked"
            db.commit()
        return templates.TemplateResponse(
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": f"Kan sessie niet aanmaken: {safe_error_message(e)}"},
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
        except Exception as e:
            logger.warning("Rekeningdetails ophalen mislukt (koppeling id=%s): %s", conn.id if conn else None, safe_error_message(e))
            iban = ""
            name = ""
        enriched_accounts.append({"uid": uid, "iban": iban, "name": name})

    if conn:
        conn.session_id = session_id
        conn.accounts_json = json.dumps(enriched_accounts)
        conn.status = "active"
        conn.valid_until = _consent_valid_until(
            session_data, request.session.get("eb_valid_days") or enable_banking.DEFAULT_CONSENT_DAYS
        )
        db.commit()

    # Clean up session
    for key in ["eb_state", "eb_bank_name", "eb_bank_country", "eb_connection_id", "eb_valid_days"]:
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
    account_iban = _normalize_iban(account_info["iban"]) if account_info else None

    from app import enable_banking
    logger.info("Bank sync gestart: %s koppeling id=%s from=%s to=%s", conn.bank_name, conn.id, date_from, date_to)
    try:
        raw_transactions = enable_banking.get_transactions(
            account_uid,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        logger.info("Bank sync: %d ruwe transacties opgehaald", len(raw_transactions))
    except Exception as e:
        logger.error("Bank sync fout (koppeling id=%s): %s", conn.id, safe_error_message(e))
        conn.last_sync_status = "error"
        conn.last_sync_error = safe_error_message(e)[:500]
        db.commit()
        return templates.TemplateResponse(
            "banking/sync.html",
            {
                "request": request, "user": user,
                "connection": conn,
                "accounts": stored_accounts,
                "error": f"Kan transacties niet ophalen: {safe_error_message(e)}",
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

    # Find or create the Account record.
    #
    # Match-strategie (in volgorde):
    #   1. Primair op external_uid (stabiele Enable Banking account_uid).
    #   2. Fallback op (bank, genormaliseerde IBAN) — ook als het Account
    #      al een external_uid heeft die verschilt van de huidige. Dat
    #      dekt: reauthorisatie na 90 dagen (nieuwe uid voor zelfde
    #      rekening) én legacy accounts aangemaakt vóór external_uid-kolom.
    #
    # Pas nadat we een Account hebben gevonden óf nieuw aangemaakt, wordt
    # external_uid op de huidige sync-uid gezet. Zo kan een sync nooit
    # meer stiekem een nieuw duplicate Account aanmaken als er al een
    # bestaand Account voor dezelfde bank+IBAN is.
    bank_key = conn.bank_name.lower().replace(" ", "_")
    display = (conn.display_name or conn.bank_name).strip()
    preferred_name = f"{display} - {account_iban}" if account_iban else display
    account = db.query(Account).filter(
        Account.user_id == user.id,
        Account.external_uid == account_uid,
    ).first()
    matched_by = "external_uid" if account else None

    if not account and account_iban:
        # Zoek alle accounts met gelijke bank + genormaliseerde IBAN.
        # We matchen in Python omdat bestaande DB-records whitespace of
        # andere casing kunnen hebben (pre-normalisatie).
        iban_candidates = (
            db.query(Account)
            .filter(
                Account.user_id == user.id,
                Account.bank == bank_key,
                Account.iban.isnot(None),
            )
            .all()
        )
        normalized_matches = [
            a for a in iban_candidates
            if _normalize_iban(a.iban) == account_iban
        ]
        if normalized_matches:
            # Prefereer een match zonder external_uid (legacy). Anders pak
            # de eerste; we linken alsnog — maar loggen een WARNING zodat
            # we multi-uid-scenario's in het oog houden.
            legacy = [a for a in normalized_matches if a.external_uid is None]
            if legacy:
                account = legacy[0]
                matched_by = "iban_legacy_fallback"
            else:
                account = normalized_matches[0]
                matched_by = "iban_fallback_reauth"
                logger.warning(
                    "Bank sync: matched Account id=%s op IBAN %s terwijl het "
                    "al een andere external_uid=%s had; nieuwe uid=%s werd "
                    "gelinkt. Mogelijk reauthorisatie.",
                    account.id, account_iban, account.external_uid, account_uid,
                )

    if account:
        # Zet/updat external_uid en IBAN canoniek op het Account record.
        if account.external_uid != account_uid:
            account.external_uid = account_uid
        if account_iban and _normalize_iban(account.iban) != account_iban:
            account.iban = account_iban
        # Synchroniseer de naam met de connection-display_name, tenzij de
        # gebruiker het account handmatig een custom naam heeft gegeven.
        autogen_prefixes = (f"{conn.bank_name} -", f"{display} -", f"{conn.bank_name}",)
        if account.name == f"{conn.bank_name} - account" or any(
            account.name.startswith(p) for p in autogen_prefixes
        ):
            account.name = preferred_name
        logger.info(
            "Bank sync: using existing Account id=%s name=%s matched_by=%s",
            account.id, account.name, matched_by,
        )
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
        # WAARSCHUWING: een sync die een nieuw Account aanmaakt is verdacht
        # voor een bestaande gebruiker — verwachte flow is dat het Account
        # al bestaat (aangemaakt bij connect). Log zichtbaar zodat we dit
        # type situaties bij toekomstige bugs in één oogopslag zien.
        logger.warning(
            "Bank sync: created NEW Account id=%s name=%s bank=%s iban=%s "
            "uid=%s — check of er géén ander Account voor deze IBAN bestaat.",
            account.id, account.name, bank_key, account_iban, account_uid,
        )

    # Import transactions (skip duplicates)
    active_rules = db.query(Rule).filter(Rule.user_id == user.id, Rule.is_active == 1).all()
    batch = ImportBatch(user_id=user.id, account_id=account.id, source="enable_banking", total_count=len(parsed))
    db.add(batch)
    db.flush()
    result = store_parsed_transactions(db, account, parsed, active_rules, batch.id)
    imported, skipped, auto_categorized = result.imported, result.skipped, result.auto_categorized

    conn.last_synced_at = datetime.utcnow()
    conn.last_sync_status = "success"
    conn.last_sync_error = None
    batch.imported_count = imported
    batch.skipped_count = skipped
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
            "rejected": 0,
            "batch": batch,
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
    except ValueError:
        logger.warning("Ongeldige rekeninglijst bij koppeling id=%s; rekeningnamen niet bijgewerkt", conn.id)
        stored_accounts = []
    bank_key = conn.bank_name.lower().replace(" ", "_")
    uids = [a.get("uid") for a in stored_accounts if a.get("uid")]
    ibans = [a.get("iban") for a in stored_accounts if a.get("iban")]

    linked: list[Account] = []
    if uids:
        linked += db.query(Account).filter(
            Account.user_id == user.id,
            Account.external_uid.in_(uids),
        ).all()
    # Legacy fallback: accounts zonder external_uid (aangemaakt vóór migratie 031)
    legacy_q = db.query(Account).filter(
        Account.user_id == user.id,
        Account.bank == bank_key,
        Account.external_uid.is_(None),
    )
    if ibans:
        legacy = legacy_q.filter(Account.iban.in_(ibans)).all()
    else:
        legacy = legacy_q.all()
    # Dedup (by id)
    seen = {a.id for a in linked}
    for a in legacy:
        if a.id not in seen:
            linked.append(a)
            seen.add(a.id)

    autogen_starts = (
        f"{old_display} -", f"{old_display}",
        f"{conn.bank_name} -", f"{conn.bank_name}",
        f"{bank_key} -", f"{bank_key}",
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
        except Exception as e:
            logger.warning("Unable to revoke remote banking session for connection id=%s: %s", conn.id, safe_error_message(e))

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
