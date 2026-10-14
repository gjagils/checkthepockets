"""bunq API-koppeling met een eigen persoonlijke API-sleutel (ACT-31): rekeningen kiezen en importeren."""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import clock
from app.auth import is_super_admin, require_login
from app.bunq_client import BunqClient, BunqError
from app.bunq_sync import account_kind_for, iban_taken, refresh_links, resolve_account, sync_connection
from app.config import BUNQ_API_BASE
from app.crypto import encryption_enabled
from app.database import get_db
from app.models import Account, BunqAccountLink, BunqConnection
from app.template_config import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/banking/bunq")


def _allowed(user) -> bool:
    """Net als de bankkoppeling: alleen de beheerder zolang dit niet voor iedereen open is."""
    return is_super_admin(user)


def _connection(db: Session, user_id: int) -> BunqConnection | None:
    return db.query(BunqConnection).filter(BunqConnection.user_id == user_id).first()


def _links(db: Session, connection: BunqConnection | None) -> list[BunqAccountLink]:
    if connection is None:
        return []
    rows = db.query(BunqAccountLink).filter_by(connection_id=connection.id).all()
    return sorted(rows, key=lambda l: (l.bunq_status != "ACTIVE", l.description or ""))


def _render(request, user, db, **extra):
    connection = _connection(db, user.id)
    own_accounts = db.query(Account).filter(Account.user_id == user.id).order_by(Account.name).all()
    context = {
        "request": request, "user": user, "connection": connection,
        "links": _links(db, connection), "own_accounts": own_accounts,
        "encryption_ready": encryption_enabled(), "sandbox": "sandbox" in BUNQ_API_BASE,
        "reports": None, "dry_run": False, "error": None, "success": None, "warnings": [],
    }
    context.update(extra)
    return templates.TemplateResponse(request, "banking/bunq.html", context)


def _guard(request, db):
    user = require_login(request, db)
    return user, (None if _allowed(user) else RedirectResponse("/banking/connect", status_code=302))


@router.get("")
def bunq_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request, db)
    return denied or _render(request, user, db)


@router.post("")
def bunq_save_key(request: Request, api_key: str = Form(...), db: Session = Depends(get_db)):
    user, denied = _guard(request, db)
    if denied:
        return denied
    api_key = api_key.strip()
    if not encryption_enabled():
        return _render(request, user, db, error="Opslaan geweigerd: veldversleuteling (FIELD_ENCRYPTION_KEY) staat niet aan.")
    if len(api_key) < 20:
        return _render(request, user, db, error="Dit lijkt geen bunq API-sleutel.")
    connection = _connection(db, user.id)
    if connection is None:
        connection = BunqConnection(user_id=user.id, api_key=api_key)
        db.add(connection)
    else:
        connection.api_key = api_key
        connection.private_key_pem = None
        connection.installation_token = None
    connection.last_status = "never"
    connection.last_error = None
    db.commit()
    return RedirectResponse("/banking/bunq", status_code=302)


@router.post("/check")
def bunq_check(request: Request, db: Session = Depends(get_db)):
    """Open a session and refresh the list of bunq accounts (read-only)."""
    user, denied = _guard(request, db)
    if denied:
        return denied
    connection = _connection(db, user.id)
    if connection is None:
        return RedirectResponse("/banking/bunq", status_code=302)

    client = BunqClient(BUNQ_API_BASE)
    error = None
    try:
        session = client.connect(connection.api_key, connection.private_key_pem, connection.installation_token)
        connection.private_key_pem = session.private_key_pem
        connection.installation_token = session.installation_token
        accounts = client.list_accounts(session)
        refresh_links(db, connection, accounts)
        connection.last_status = "ok"
        connection.last_error = None
        logger.info("bunq: %d rekeningen opgehaald (soorten: %s)", len(accounts),
                    sorted({a.kind for a in accounts}))
    except BunqError as exc:
        error = str(exc)
        connection.last_status = "error"
        connection.last_error = error
        logger.warning("bunq: controle mislukt (%s, HTTP %s)", exc.kind, exc.status)
    connection.last_checked_at = clock.now_utc()
    db.commit()
    return _render(request, user, db, error=error)


@router.post("/accounts")
async def bunq_save_accounts(request: Request, db: Session = Depends(get_db)):
    """Save which bunq accounts to import, their kind, and the own account they map to."""
    user, denied = _guard(request, db)
    if denied:
        return denied
    connection = _connection(db, user.id)
    if connection is None:
        return RedirectResponse("/banking/bunq", status_code=302)
    form = await request.form()
    enabled_ids = {int(v) for v in form.getlist("enable") if str(v).isdigit()}
    warnings = []
    try:
        for link in _links(db, connection):
            link.enabled = 1 if link.id in enabled_ids else 0
            kind = form.get(f"kind_{link.id}") or account_kind_for(link.bunq_kind)
            choice = form.get(f"account_{link.id}") or "auto"
            if link.enabled:
                account = resolve_account(db, user.id, link, choice, kind)
                if link.account_id != account.id:
                    link.last_payment_id = None   # andere doelrekening: opnieuw vanaf het begin
                link.account_id = account.id
                other = iban_taken(db, user.id, account, link.iban) if link.iban and account.iban != link.iban else None
                if other is not None:
                    warnings.append(
                        f"{link.description or link.iban}: het IBAN staat al op de rekening "
                        f"\u201c{other.name}\u201d. Voeg die twee rekeningen eerst samen (Rekeningen \u2192 Samenvoegen) "
                        f"en kies daarna de samengevoegde rekening.")
            elif link.account is not None:
                # Soort mag ook van een niet-geselecteerde, al gekoppelde rekening wijzigen.
                link.account.kind = kind if kind in ("payment", "savings") else link.account.kind
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("bunq: selectie opslaan mislukt")
        return _render(request, user, db, error="Opslaan is niet gelukt; er is niets gewijzigd. Zie de serverlog.")
    return _render(request, user, db, success="Selectie opgeslagen.", warnings=warnings)


@router.post("/sync")
def bunq_sync(request: Request, mode: str = Form("preview"), db: Session = Depends(get_db)):
    """Preview (nothing stored) or import the payments of all selected accounts."""
    user, denied = _guard(request, db)
    if denied:
        return denied
    connection = _connection(db, user.id)
    if connection is None:
        return RedirectResponse("/banking/bunq", status_code=302)
    dry_run = mode != "import"
    reports, error = None, None
    try:
        reports = sync_connection(db, connection, BunqClient(BUNQ_API_BASE), dry_run)
        db.commit()
    except BunqError as exc:
        db.rollback()
        error = str(exc)
        logger.warning("bunq: synchronisatie mislukt (%s, HTTP %s)", exc.kind, exc.status)
    except Exception:
        db.rollback()
        logger.exception("bunq: synchronisatie mislukt")
        error = "Synchroniseren is niet gelukt; er is niets opgeslagen. Zie de serverlog."
    return _render(request, user, db, reports=reports, dry_run=dry_run, error=error)


@router.post("/delete")
def bunq_delete(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request, db)
    if denied:
        return denied
    connection = _connection(db, user.id)
    if connection:
        db.query(BunqAccountLink).filter_by(connection_id=connection.id).delete(synchronize_session=False)
        db.delete(connection)
        db.commit()
    return RedirectResponse("/banking/bunq", status_code=302)
