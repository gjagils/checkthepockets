from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Transaction, SavingsPlan, Category, Rule, Person
from app.auth import require_login
from app.template_config import templates

router = APIRouter()


@router.get("/accounts")
def accounts_list(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )
    persons = (
        db.query(Person)
        .filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    return templates.TemplateResponse(
        "accounts/list.html",
        {"request": request, "user": user, "accounts": accounts, "persons": persons},
    )


@router.post("/accounts/{account_id}/owners")
def set_account_owners(
    account_id: int,
    request: Request,
    owner_id: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id)
        .first()
    )
    if not account:
        return RedirectResponse("/accounts", status_code=302)

    if owner_id:
        owners = (
            db.query(Person)
            .filter(Person.user_id == user.id, Person.id.in_(set(owner_id)))
            .all()
        )
    else:
        owners = []
    account.owners = owners
    db.commit()
    return RedirectResponse("/accounts", status_code=302)


@router.post("/accounts/{account_id}/delete")
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id)
        .first()
    )
    if account:
        # Verwijder gerelateerde records eerst (geen CASCADE op FK)
        db.query(Transaction).filter(Transaction.account_id == account.id).delete(synchronize_session=False)
        db.query(SavingsPlan).filter(SavingsPlan.account_id == account.id).delete(synchronize_session=False)
        # Ontkoppel categorieën en regels (nullable FK, zet op NULL)
        db.query(Category).filter(Category.account_id == account.id).update({"account_id": None}, synchronize_session=False)
        db.query(Rule).filter(Rule.condition_account_id == account.id).update({"condition_account_id": None}, synchronize_session=False)
        db.delete(account)
        db.commit()
    return RedirectResponse("/accounts", status_code=302)


@router.post("/accounts/delete-all-transactions")
def delete_all_transactions(request: Request, db: Session = Depends(get_db)):
    """Delete all transactions for the current user (for testing)."""
    user = require_login(request, db)
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    account_ids = [a.id for a in accounts]
    if account_ids:
        db.query(Transaction).filter(Transaction.account_id.in_(account_ids)).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse("/accounts", status_code=302)
