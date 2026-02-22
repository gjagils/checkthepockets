from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Category
from app.auth import require_login

router = APIRouter(prefix="/categories")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def categories_list(
    request: Request,
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    query = db.query(Category).filter(Category.user_id == user.id)
    if account_id:
        query = query.filter(Category.account_id == account_id)

    all_categories = query.order_by(Category.name).all()

    # Build hierarchy: top-level (parent_id=None) with their children
    top_level = [c for c in all_categories if c.parent_id is None]
    children_map = {}
    for c in all_categories:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

    return templates.TemplateResponse(
        "categories/list.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "top_level": top_level,
            "children_map": children_map,
        },
    )


@router.post("")
def create_category(
    request: Request,
    name: str = Form(...),
    account_id: int = Form(0),
    parent_id: int = Form(0),
    color: str = Form(""),
    is_income: int = Form(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    acc_id = account_id if account_id else None
    par_id = parent_id if parent_id else None

    # Verify account belongs to user
    if acc_id:
        account = (
            db.query(Account)
            .filter(Account.id == acc_id, Account.user_id == user.id)
            .first()
        )
        if not account:
            return RedirectResponse("/categories", status_code=302)

    # If parent is set, inherit account_id from parent
    if par_id:
        parent = (
            db.query(Category)
            .filter(Category.id == par_id, Category.user_id == user.id)
            .first()
        )
        if not parent:
            return RedirectResponse("/categories", status_code=302)
        acc_id = parent.account_id

    cat = Category(
        user_id=user.id,
        account_id=acc_id,
        name=name.strip(),
        parent_id=par_id,
        color=color.strip() or None,
        is_income=is_income,
    )
    db.add(cat)
    db.commit()

    redirect = "/categories"
    if acc_id:
        redirect += f"?account_id={acc_id}"
    return RedirectResponse(redirect, status_code=302)


@router.post("/{category_id}/delete")
def delete_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not cat:
        return RedirectResponse("/categories", status_code=302)

    acc_id = cat.account_id

    # Delete children first
    db.query(Category).filter(
        Category.parent_id == category_id,
        Category.user_id == user.id,
    ).delete()

    db.delete(cat)
    db.commit()

    redirect = "/categories"
    if acc_id:
        redirect += f"?account_id={acc_id}"
    return RedirectResponse(redirect, status_code=302)
