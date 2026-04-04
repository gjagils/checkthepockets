import hashlib
import time

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired, get_current_user
from app.database import get_db
from app.routers import auth, transactions, accounts, categories, tags, rules, budgets, recurring, dashboard, savings, analytics, portfolio, networth, settings, admin
from app.scheduler import start_scheduler

from app.config import SECRET_KEY

app = FastAPI(title="Check Your Pockets", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="oauth_state")
_landing_templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Cache-busting: generate a version hash at startup so CSS/JS URLs change on each deploy
_ASSET_VERSION = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]


@app.middleware("http")
async def add_asset_version(request: Request, call_next):
    """Make asset_version available in all template contexts."""
    request.state.asset_version = _ASSET_VERSION
    return await call_next(request)

@app.get("/")
def landing(request: Request):
    """Landing page — redirect to dashboard if already logged in."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    except Exception:
        user = None
    finally:
        db.close()
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return _landing_templates.TemplateResponse("landing.html", {"request": request})


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(tags.router)
app.include_router(rules.router)
app.include_router(budgets.router)
app.include_router(recurring.router)
app.include_router(savings.router)
app.include_router(analytics.router)
app.include_router(portfolio.router)
app.include_router(networth.router)
app.include_router(settings.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=302)
