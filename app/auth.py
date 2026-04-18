import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.requests import Request
from starlette.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import SECRET_KEY, SESSION_MAX_AGE
from app.models import User

_signer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_cookie(user_id: int) -> str:
    return _signer.dumps({"uid": user_id})


def get_session_user_id(request: Request) -> int | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _signer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = get_session_user_id(request)
    if user_id is None:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_login(request: Request, db: Session) -> User:
    """Returns user or raises a redirect to login."""
    user = get_current_user(request, db)
    if user is None:
        raise LoginRequired()
    return user


class LoginRequired(Exception):
    pass


def set_session_cookie(response: RedirectResponse, user_id: int) -> RedirectResponse:
    response.set_cookie(
        COOKIE_NAME,
        create_session_cookie(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


# Whitelist van toegestane startpagina-routes. Label voor de UI-dropdown.
# `admin_only` weert opties uit het menu van niet-admins.
START_PAGE_OPTIONS = [
    {"path": "/dashboard", "label": "Dashboard", "admin_only": False},
    {"path": "/transactions", "label": "Transacties", "admin_only": False},
    {"path": "/budgets", "label": "Budgetten", "admin_only": False},
    {"path": "/savings", "label": "Sparen", "admin_only": False},
    {"path": "/portfolio", "label": "Portfolio", "admin_only": False},
    {"path": "/analytics", "label": "Analyse", "admin_only": False},
    {"path": "/accounts", "label": "Rekeningen", "admin_only": False},
    {"path": "/hypotheek", "label": "Hypotheek", "admin_only": True},
]


def allowed_start_pages(user: User) -> list[dict]:
    """Opties die deze user mag kiezen (admins zien ook admin-only pagina's)."""
    return [
        opt for opt in START_PAGE_OPTIONS
        if not opt["admin_only"] or user.is_admin
    ]


def user_start_page(user: User | None) -> str:
    """Route voor inlog/landing — valt terug op /dashboard als de keuze niet
    meer geldig is voor deze user (bv. admin-only pagina na rol-wijziging)."""
    default = "/dashboard"
    if user is None:
        return default
    pref = (user.start_page or "").strip()
    if not pref:
        return default
    for opt in allowed_start_pages(user):
        if opt["path"] == pref:
            return pref
    return default
