from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import LoginRequired
from app.routers import auth, transactions, accounts, categories, tags, rules, budgets, recurring, dashboard, savings, analytics, portfolio, networth, plaid
from app.scheduler import start_scheduler

app = FastAPI(title="Check The Pockets", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
app.include_router(plaid.router)


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=302)
