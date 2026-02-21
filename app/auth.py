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
