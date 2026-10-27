from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import Account, Category, Transaction
from app.redirects import safe_redirect
from app.transaction_queries import inbox_count, inbox_query as _inbox_query  # noqa: F401  (inbox_count: bestaande importeurs)

router = APIRouter()


@router.get("/inbox")
def inbox_page(
    request: Request,
    account_id: str = Query(""),
    db: Session = Depends(get_db),
):
    """De inbox is de transactiepagina met het filter "Niet gecategoriseerd"."""
    require_login(request, db)
    target = "/transactions?category_id=-1"
    if account_id.strip().isdigit():
        target += f"&account_id={int(account_id.strip())}"
    return RedirectResponse(target, status_code=302)


@router.post("/inbox/{transaction_id}/category")
def set_category(
    request: Request,
    transaction_id: int,
    category_id: int = Form(...),
    redirect_to: str = Form("/inbox"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == transaction_id, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return safe_redirect(redirect_to, "/inbox", status_code=303)

    # Verifieer dat de categorie van deze gebruiker is
    cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not cat:
        return safe_redirect(redirect_to, "/inbox", status_code=303)

    tx.category_id = cat.id
    tx.assigned_by_rule_id = None
    tx.is_reviewed = 1
    db.commit()

    return safe_redirect(redirect_to, "/inbox", status_code=303)
