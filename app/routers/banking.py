"""Enable Banking PSD2 integration — connect bank accounts and sync transactions."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import bank_sync, clock
from app.auth import is_super_admin, require_login
from app.config import APP_URL, ENABLE_BANKING_APP_ID
from app.database import get_db
from app.models import Account, BankConnection
from app.enable_banking import safe_error_message
from app.template_config import templates

router = APIRouter(prefix="/banking")


def _is_configured() -> bool:
    return bool(ENABLE_BANKING_APP_ID)


def _is_banking_allowed(user) -> bool:
    """Only super admin can use banking in restricted mode."""
    return is_super_admin(user)


_normalize_iban = bank_sync.normalize_iban  # alias; de logica staat in app/bank_sync.py


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
        request,
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
            request,
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
    rest van de app gebruikt clock.now_utc(). Valt terug op nu + fallback_days."""
    raw = (session_data.get("access") or {}).get("valid_until")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            logger.warning("Onbegrijpelijke valid_until van Enable Banking: %r", raw)
    return clock.now_utc() + timedelta(days=fallback_days)


ACCOUNT_TYPE_LABELS = {
    "CACC": "Betaalrekening",
    "SVGS": "Spaarrekening",
    "CARD": "Creditcard",
    "LOAN": "Lening",
    "TRAN": "Transactierekening",
}


def _extract_iban(data: dict) -> str:
    """IBAN uit een Enable Banking-rekening of -details. `account_id` kan een
    dict óf een lijst zijn, en banken gebruiken verschillende veldnamen."""
    acc_id = data.get("account_id")
    if isinstance(acc_id, dict):
        iban = acc_id.get("iban") or acc_id.get("IBAN") or ""
        if iban:
            return iban
    elif isinstance(acc_id, list):
        for entry in acc_id:
            if isinstance(entry, dict):
                iban = entry.get("iban") or entry.get("IBAN") or ""
                if iban:
                    return iban
    return data.get("iban") or ""


def _bic(data: dict) -> str:
    servicer = data.get("account_servicer")
    return servicer.get("bic_fi", "") if isinstance(servicer, dict) else ""


def _describe_session_accounts(session_accounts, get_details, conn=None) -> list[dict]:
    """Alle rekeningen uit een Enable Banking-sessie, ook die zonder `uid`.

    Zonder `uid` kan de bank geen saldo of transacties leveren (volgens Enable
    Banking bv. bij een geblokkeerde of gesloten rekening); die bewaren we met
    ``available=False`` zodat de gebruiker ziet wat er terugkwam.
    """
    described = []
    for acc in session_accounts or []:
        if not isinstance(acc, dict):
            continue
        uid = acc.get("uid") or acc.get("account_uid")
        iban = _extract_iban(acc)
        name = _bic(acc)
        details = None
        if uid:
            try:
                details = get_details(uid)
                iban = _extract_iban(details) or iban
                name = _bic(details) or name
            except Exception as e:
                logger.warning("Rekeningdetails ophalen mislukt (koppeling id=%s): %s",
                               conn.id if conn else None, safe_error_message(e))
        cash_type = acc.get("cash_account_type") or (details or {}).get("cash_account_type") or ""
        described.append({
            "uid": uid or None,
            "iban": iban,
            "name": name,
            "type": ACCOUNT_TYPE_LABELS.get(cash_type, cash_type),
            "available": bool(uid),
        })
    return described


def _merge_session_uids(session_accounts, session_info: dict, conn=None) -> list:
    """Voeg rekeningen toe die wel in GET /sessions staan maar niet in het
    antwoord van POST /sessions. Van die extra rekeningen is alleen de `uid`
    bekend; IBAN en soort komen uit de details."""
    known = {
        acc.get("uid") or acc.get("account_uid")
        for acc in session_accounts or [] if isinstance(acc, dict)
    }
    listed = [u for u in session_info.get("accounts") or [] if isinstance(u, str)]
    data_uids = [d.get("uid") for d in session_info.get("accounts_data") or [] if isinstance(d, dict)]
    extra = [u for u in dict.fromkeys(listed + [u for u in data_uids if u]) if u not in known]
    logger.info(
        "Enable Banking sessie opgevraagd (koppeling id=%s): %d in accounts, %d in accounts_data, %d extra",
        conn.id if conn else None, len(listed), len(data_uids), len(extra),
    )
    return list(session_accounts or []) + [{"uid": u} for u in extra]


def _available_accounts(stored_accounts: list[dict]) -> list[dict]:
    """Rekeningen waarvan transacties op te halen zijn (oude records: altijd met uid)."""
    return [a for a in stored_accounts if a.get("uid")]


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
            request,
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": "Ongeldige state parameter. Probeer opnieuw."},
        )

    if not code:
        return templates.TemplateResponse(
            request,
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
            request,
            "banking/result.html",
            {"request": request, "user": user, "success": False, "error": f"Kan sessie niet aanmaken: {safe_error_message(e)}"},
        )

    session_id = session_data.get("session_id")
    accounts = session_data.get("accounts", [])
    # Diagnose (ACT-25b): alleen veldnamen, nooit waarden.
    logger.info(
        "Enable Banking sessie aangemaakt (koppeling id=%s): velden %s; %d rekening(en) met velden %s",
        conn.id if conn else None, sorted(session_data), len(accounts) if isinstance(accounts, list) else -1,
        [sorted(acc) if isinstance(acc, dict) else type(acc).__name__ for acc in accounts]
        if isinstance(accounts, list) else type(accounts).__name__,
    )
    # POST /sessions geeft soms minder rekeningen terug dan de gebruiker koos;
    # vul aan met de lijst van GET /sessions (ACT-25b).
    if session_id:
        try:
            accounts = _merge_session_uids(accounts, enable_banking.get_session(session_id), conn)
        except Exception as e:
            logger.warning("Enable Banking sessie opvragen mislukt (koppeling id=%s): %s",
                           conn.id if conn else None, safe_error_message(e))

    enriched_accounts = _describe_session_accounts(accounts, enable_banking.get_account_details, conn)
    available_count = sum(1 for a in enriched_accounts if a["available"])
    logger.info(
        "Enable Banking sessie (koppeling id=%s): %d rekening(en) ontvangen, %d op te halen; %s",
        conn.id if conn else None, len(enriched_accounts), available_count,
        ", ".join(f"#{i + 1} {a['type'] or 'onbekend type'} {'met' if a['available'] else 'zonder'} uid"
                  for i, a in enumerate(enriched_accounts)) or "geen",
    )

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
        request,
        "banking/result.html",
        {
            "request": request, "user": user,
            "success": True,
            "bank_name": conn.bank_name if conn else "Bank",
            "accounts": enriched_accounts,
            "available_count": available_count,
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

    stored_accounts = json.loads(conn.accounts_json or "[]")
    return templates.TemplateResponse(
        request,
        "banking/sync.html",
        {
            "request": request, "user": user, "connection": conn,
            "accounts": _available_accounts(stored_accounts),
            "unavailable_accounts": [a for a in stored_accounts if not a.get("uid")],
        },
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

    stored_accounts = json.loads(conn.accounts_json or "[]")

    result = bank_sync.sync_account(
        db, conn, account_uid, date_from=date_from or None, date_to=date_to or None,
    )
    db.commit()
    if result.status != "ok":
        error = (
            f"Kan transacties niet ophalen: {result.error}" if result.status == "fetch_error"
            else "Geen transacties gevonden voor de geselecteerde periode."
        )
        return templates.TemplateResponse(
            request,
            "banking/sync.html",
            {
                "request": request, "user": user,
                "connection": conn,
                "accounts": _available_accounts(stored_accounts),
                "error": error,
            },
        )

    # Re-run the rules over all transactions (catches rename -> match chains), link recurring items and
    # refresh projections. The "extra" count is kept apart from "auto-categorised on import".
    extra = bank_sync.post_import(db, user.id)
    db.commit()
    imported, skipped, auto_categorized = result.imported, result.skipped, result.auto_categorized
    batch, account = result.batch, result.account

    return templates.TemplateResponse(
        request,
        "banking/sync_result.html",
        {
            "request": request, "user": user,
            "imported": imported,
            "skipped": skipped,
            "auto_categorized": auto_categorized,
            "extra_categorized": extra,
            "rejected": 0,
            "batch": batch,
            "total": result.total,
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


_map_eb_transactions = bank_sync.map_eb_transactions  # alias; de logica staat in app/bank_sync.py
