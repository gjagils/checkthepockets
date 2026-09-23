import hashlib
import logging
import os
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# Initialiseer root logger voordat we app-modules importeren — anders blijven
# logger.info/warning-calls in scheduler.py, email_service.py etc. stil omdat
# de default root-level WARNING is en er geen handler op stdout staat.
# LOG_LEVEL kan via env-var worden overschreven (DEBUG/INFO/WARNING/ERROR).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

from app.auth import LoginRequired, get_current_user
from app.database import get_db
from app.routers import auth, transactions, accounts, categories, rules, budgets, recurring, dashboard, savings, analytics, portfolio, networth, settings, admin, banking, inbox, persons, mortgage, info
from app.scheduler import start_scheduler

from app.config import APP_URL, COOKIE_SECURE, CSRF_ENFORCE, SECRET_KEY, validate_production_config

validate_production_config()

app = FastAPI(title="Check Your Pockets", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="oauth_state", https_only=COOKIE_SECURE)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """Reject cross-origin state-changing cookie requests in production."""
    if CSRF_ENFORCE and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        expected = APP_URL.rstrip("/")
        supplied = origin or (f"{urlsplit(referer).scheme}://{urlsplit(referer).netloc}" if referer else None)
        # Login/register clients may not have a cookie yet; authenticated
        # browser mutations must carry same-origin metadata.
        has_session = bool(request.cookies.get("session"))
        if has_session and supplied != expected:
            return PlainTextResponse("CSRF origin check failed", status_code=403)
    return await call_next(request)
_landing_templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Cache-busting: generate a version hash at startup so CSS/JS URLs change on each deploy
_ASSET_VERSION = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]


@app.middleware("http")
async def add_asset_version(request: Request, call_next):
    """Make asset_version available in all template contexts."""
    request.state.asset_version = _ASSET_VERSION
    return await call_next(request)


@app.middleware("http")
async def add_inbox_count(request: Request, call_next):
    """Populate request.state.inbox_count for the nav badge (authenticated users)."""
    request.state.inbox_count = 0
    if not request.url.path.startswith("/static"):
        try:
            from app.auth import get_session_user_id
            from app.database import SessionLocal
            from app.routers.inbox import inbox_count
            uid = get_session_user_id(request)
            if uid:
                db = SessionLocal()
                try:
                    request.state.inbox_count = inbox_count(db, uid)
                finally:
                    db.close()
        except Exception:
            logger.warning("Inbox count unavailable for this request", exc_info=True)
    return await call_next(request)

@app.get("/")
def landing(request: Request):
    """Landing page — redirect to user's preferred start page if logged in."""
    from app.auth import user_start_page
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    except Exception:
        user = None
    finally:
        db.close()
    if user:
        return RedirectResponse(user_start_page(user), status_code=302)
    return _landing_templates.TemplateResponse("landing.html", {"request": request})


@app.get("/privacy")
def privacy(request: Request):
    return _landing_templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/terms")
def terms(request: Request):
    return _landing_templates.TemplateResponse("terms.html", {"request": request})


@app.get("/healthz")
def healthz():
    """Liveness probe: the process is serving requests."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness probe: the process can reach its configured database."""
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    return {"status": "ready"}


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(rules.router)
app.include_router(budgets.router)
app.include_router(recurring.router)
app.include_router(savings.router)
app.include_router(analytics.router)
app.include_router(portfolio.router)
app.include_router(persons.router)
app.include_router(networth.router)
app.include_router(settings.router)
app.include_router(admin.router)
app.include_router(banking.router)
app.include_router(inbox.router)
app.include_router(mortgage.router)
app.include_router(info.router)


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=302)
