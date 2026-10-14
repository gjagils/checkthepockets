"""bunq API-koppeling met een eigen persoonlijke API-sleutel (ACT-31a: verbinden en rekeningen tonen)."""
import datetime
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.bunq_client import BunqClient, BunqError
from app.config import BUNQ_API_BASE, SUPER_ADMIN_USERNAME
from app.crypto import encryption_enabled
from app.database import get_db
from app.models import BunqConnection
from app.template_config import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/banking/bunq")


def _allowed(user) -> bool:
    """Net als de bankkoppeling: alleen de beheerder zolang dit niet voor iedereen open is."""
    return bool(SUPER_ADMIN_USERNAME and user.username == SUPER_ADMIN_USERNAME)


def _connection(db: Session, user_id: int) -> BunqConnection | None:
    return db.query(BunqConnection).filter(BunqConnection.user_id == user_id).first()


def _render(request, user, db, **extra):
    context = {
        "request": request, "user": user, "connection": _connection(db, user.id),
        "encryption_ready": encryption_enabled(), "sandbox": "sandbox" in BUNQ_API_BASE,
        "accounts": None, "error": None, "success": None,
    }
    context.update(extra)
    return templates.TemplateResponse("banking/bunq.html", context)


@router.get("")
def bunq_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not _allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    return _render(request, user, db)


@router.post("")
def bunq_save_key(request: Request, api_key: str = Form(...), db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not _allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
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
    """Open a session and list all monetary accounts (read-only)."""
    user = require_login(request, db)
    if not _allowed(user):
        return RedirectResponse("/banking/connect", status_code=302)
    connection = _connection(db, user.id)
    if connection is None:
        return RedirectResponse("/banking/bunq", status_code=302)

    client = BunqClient(BUNQ_API_BASE)
    accounts = None
    error = None
    try:
        session = client.connect(connection.api_key, connection.private_key_pem, connection.installation_token)
        connection.private_key_pem = session.private_key_pem
        connection.installation_token = session.installation_token
        accounts = client.list_accounts(session)
        connection.last_status = "ok"
        connection.last_error = None
        logger.info("bunq: %d rekeningen opgehaald (soorten: %s)", len(accounts),
                    sorted({a.kind for a in accounts}))
    except BunqError as exc:
        error = str(exc)
        connection.last_status = "error"
        connection.last_error = error
        logger.warning("bunq: controle mislukt (%s, HTTP %s)", exc.kind, exc.status)
    connection.last_checked_at = datetime.datetime.utcnow()
    db.commit()
    return _render(request, user, db, accounts=accounts, error=error)


@router.post("/delete")
def bunq_delete(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if _allowed(user):
        connection = _connection(db, user.id)
        if connection:
            db.delete(connection)
            db.commit()
    return RedirectResponse("/banking/bunq", status_code=302)
