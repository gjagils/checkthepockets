import datetime
import secrets

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Transaction, Account, AuthToken
from app.auth import (
    hash_password,
    verify_password,
    set_session_cookie,
    get_current_user,
    require_login,
    COOKIE_NAME,
)
from app.config import (
    REGISTRATION_OPEN, REQUIRE_EMAIL_VERIFICATION,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, APP_URL,
    SUPER_ADMIN_USERNAME,
)
from app.email_service import send_verification_email, send_password_reset_email
from app.rate_limit import is_rate_limited, record_failed_attempt, clear_attempts
from app.template_config import templates

# ──────────────────────────────────────────────────────────────────────────────
# Google OAuth setup (only if credentials are configured)
# ──────────────────────────────────────────────────────────────────────────────

_google_oauth = None

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    try:
        from authlib.integrations.starlette_client import OAuth
        _oauth = OAuth()
        _oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _google_oauth = _oauth.google
    except Exception:
        pass


def google_login_enabled() -> bool:
    return _google_oauth is not None

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _enforce_super_admin(user: "User", db: Session) -> None:
    """Ensure the super admin always has is_admin=1 and is_active=1."""
    if SUPER_ADMIN_USERNAME and user.username == SUPER_ADMIN_USERNAME:
        changed = False
        if not user.is_admin:
            user.is_admin = 1
            changed = True
        if not user.is_active:
            user.is_active = 1
            changed = True
        if changed:
            db.commit()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _create_token(db: Session, user_id: int | None, token_type: str,
                  hours: int = 24, email: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)
    db.add(AuthToken(
        user_id=user_id,
        token=token,
        token_type=token_type,
        expires_at=expires,
        email=email,
    ))
    db.commit()
    return token


def _consume_token(db: Session, token: str, token_type: str) -> AuthToken | None:
    """Return and invalidate a valid, unused, unexpired token or None."""
    t = db.query(AuthToken).filter(
        AuthToken.token == token,
        AuthToken.token_type == token_type,
        AuthToken.used_at.is_(None),
        AuthToken.expires_at > datetime.datetime.utcnow(),
    ).first()
    if t:
        t.used_at = datetime.datetime.utcnow()
        db.commit()
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "google_login_enabled": google_login_enabled(),
    })


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)

    if is_rate_limited(ip):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Te veel mislukte pogingen. Probeer het over een minuut opnieuw."},
            status_code=429,
        )

    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.password_hash):
        record_failed_attempt(ip)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Ongeldige gebruikersnaam of wachtwoord"},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Je account is gedeactiveerd. Neem contact op met de beheerder."},
            status_code=403,
        )

    if REQUIRE_EMAIL_VERIFICATION and not user.is_verified:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Bevestig je e-mailadres eerst via de link in de verificatiemail."},
            status_code=403,
        )

    clear_attempts(ip)
    _enforce_super_admin(user, db)
    user.last_login_at = datetime.datetime.utcnow()
    db.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    return set_session_cookie(response, user.id)


# ──────────────────────────────────────────────────────────────────────────────
# Register
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/register")
def register_page(request: Request, invite: str = "", db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)

    if not REGISTRATION_OPEN:
        # Validate invite token before showing the form
        if invite:
            t = db.query(AuthToken).filter(
                AuthToken.token == invite,
                AuthToken.token_type == "invite",
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > datetime.datetime.utcnow(),
            ).first()
            if not t:
                return templates.TemplateResponse(
                    "auth/login.html",
                    {"request": request, "error": "Ongeldige of verlopen uitnodigingslink."},
                )
        else:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Registratie is gesloten. Je hebt een uitnodigingslink nodig."},
            )

    return templates.TemplateResponse("auth/register.html", {"request": request, "invite": invite})


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    password_confirm: str = Form(...),
    invite: str = Form(""),
    db: Session = Depends(get_db),
):
    errors = []

    # Validate invite if registration is closed
    invite_token = None
    if not REGISTRATION_OPEN:
        invite_token = _consume_token(db, invite, "invite")
        if not invite_token:
            errors.append("Ongeldige of verlopen uitnodigingslink.")

    if len(username) < 3:
        errors.append("Gebruikersnaam moet minimaal 3 tekens zijn")
    if len(password) < 8:
        errors.append("Wachtwoord moet minimaal 8 tekens zijn")
    if password != password_confirm:
        errors.append("Wachtwoorden komen niet overeen")
    if db.query(User).filter(User.username == username).first():
        errors.append("Gebruikersnaam is al in gebruik")
    if email and db.query(User).filter(User.email == email).first():
        errors.append("Dit e-mailadres is al in gebruik")

    if errors:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "errors": errors, "username": username,
             "email": email, "invite": invite},
            status_code=400,
        )

    # First registered user becomes admin
    is_first_user = db.query(User).count() == 0

    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email.strip() or None,
        is_verified=0 if (REQUIRE_EMAIL_VERIFICATION and email) else 1,
        is_admin=1 if is_first_user else 0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Send verification email if needed
    if REQUIRE_EMAIL_VERIFICATION and user.email and not user.is_verified:
        token = _create_token(db, user.id, "verify_email", hours=24)
        send_verification_email(user.email, token)
        return templates.TemplateResponse(
            "auth/verify_email.html",
            {"request": request, "email": user.email, "mode": "sent"},
        )

    response = RedirectResponse("/dashboard", status_code=302)
    return set_session_cookie(response, user.id)


# ──────────────────────────────────────────────────────────────────────────────
# Email verification
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/verify-email")
def verify_email(request: Request, token: str = "", db: Session = Depends(get_db)):
    t = _consume_token(db, token, "verify_email")
    if not t or not t.user_id:
        return templates.TemplateResponse(
            "auth/verify_email.html",
            {"request": request, "mode": "invalid"},
        )
    user = db.query(User).filter(User.id == t.user_id).first()
    if user:
        user.is_verified = 1
        db.commit()
    return templates.TemplateResponse(
        "auth/verify_email.html",
        {"request": request, "mode": "confirmed"},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Forgot / reset password
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/forgot-password")
def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    # Always show the same message to prevent user enumeration
    user = db.query(User).filter(User.email == email.strip()).first()
    if user and user.email:
        token = _create_token(db, user.id, "reset_password", hours=1)
        send_password_reset_email(user.email, token)

    return templates.TemplateResponse(
        "auth/forgot_password.html",
        {"request": request, "sent": True},
    )


@router.get("/reset-password")
def reset_password_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    t = db.query(AuthToken).filter(
        AuthToken.token == token,
        AuthToken.token_type == "reset_password",
        AuthToken.used_at.is_(None),
        AuthToken.expires_at > datetime.datetime.utcnow(),
    ).first()
    if not t:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {"request": request, "token": token, "invalid": True},
        )
    return templates.TemplateResponse(
        "auth/reset_password.html",
        {"request": request, "token": token},
    )


@router.post("/reset-password")
def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    errors = []
    if len(new_password) < 8:
        errors.append("Wachtwoord moet minimaal 8 tekens zijn")
    if new_password != new_password_confirm:
        errors.append("Wachtwoorden komen niet overeen")

    if errors:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {"request": request, "token": token, "errors": errors},
            status_code=400,
        )

    t = _consume_token(db, token, "reset_password")
    if not t or not t.user_id:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {"request": request, "token": token, "invalid": True},
        )

    user = db.query(User).filter(User.id == t.user_id).first()
    if user:
        user.password_hash = hash_password(new_password)
        db.commit()

    return templates.TemplateResponse(
        "auth/reset_password.html",
        {"request": request, "token": token, "success": True},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user},
    )


@router.post("/settings/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    errors = []
    if not verify_password(current_password, user.password_hash):
        errors.append("Huidig wachtwoord is onjuist")
    if len(new_password) < 8:
        errors.append("Nieuw wachtwoord moet minimaal 8 tekens zijn")
    if new_password != new_password_confirm:
        errors.append("Nieuwe wachtwoorden komen niet overeen")

    if errors:
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "errors": errors},
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user, "success": "Wachtwoord succesvol gewijzigd"},
    )


@router.post("/settings/digest")
def update_digest_preferences(
    request: Request,
    enabled: str = Form(""),
    weekday: int = Form(4),
    hour: int = Form(8),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    user.weekly_digest_enabled = 1 if enabled == "1" else 0
    if 0 <= weekday <= 6:
        user.weekly_digest_weekday = weekday
    if 0 <= hour <= 23:
        user.weekly_digest_hour = hour
    db.commit()

    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user, "digest_success": "Digest-voorkeuren opgeslagen"},
    )


@router.post("/settings/delete-account")
def delete_account(
    request: Request,
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    if not verify_password(confirm_password, user.password_hash):
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "delete_error": "Wachtwoord is onjuist"},
            status_code=400,
        )

    db.delete(user)
    db.commit()

    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post("/settings/delete-transactions")
def delete_all_transactions(
    request: Request,
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    if not verify_password(confirm_password, user.password_hash):
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "tx_delete_error": "Wachtwoord is onjuist"},
            status_code=400,
        )

    account_ids = db.query(Account.id).filter(Account.user_id == user.id).subquery()
    deleted = db.query(Transaction).filter(Transaction.account_id.in_(account_ids)).delete(synchronize_session=False)
    db.commit()

    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user, "success": f"{deleted} transactie(s) verwijderd."},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Google OAuth
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/auth/google")
async def google_login_redirect(request: Request):
    if not _google_oauth:
        return RedirectResponse("/login", status_code=302)
    redirect_uri = f"{APP_URL}/auth/google/callback"
    return await _google_oauth.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not _google_oauth:
        return RedirectResponse("/login", status_code=302)

    try:
        token = await _google_oauth.authorize_access_token(request)
    except Exception:
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Google login mislukt. Probeer het opnieuw.",
            "google_login_enabled": True,
        })

    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("email"):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Kon geen e-mailadres ophalen van Google.",
            "google_login_enabled": True,
        })

    email = userinfo["email"]
    name = userinfo.get("name", email.split("@")[0])

    # Look up existing user by email
    user = db.query(User).filter(User.email == email).first()

    if not user:
        if not REGISTRATION_OPEN:
            return templates.TemplateResponse("auth/login.html", {
                "request": request,
                "error": "Registratie is gesloten. Vraag een uitnodigingslink aan.",
                "google_login_enabled": True,
            })

        # Generate unique username from Google name
        base = name.replace(" ", "_").lower()[:50]
        username = base
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{base}_{suffix}"
            suffix += 1

        is_first = db.query(User).count() == 0
        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            email=email,
            is_verified=1,
            is_admin=1 if is_first else 0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Je account is gedeactiveerd. Neem contact op met de beheerder.",
            "google_login_enabled": True,
        })

    _enforce_super_admin(user, db)
    user.last_login_at = datetime.datetime.utcnow()
    db.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    return set_session_cookie(response, user.id)


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
