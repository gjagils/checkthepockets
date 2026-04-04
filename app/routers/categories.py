from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Account, Category, Transaction
from app.auth import require_login
from app.template_config import templates

router = APIRouter(prefix="/categories")


@router.get("")
def categories_list(
    request: Request,
    account_id: int = Query(0),
    show_archived: int = Query(0),
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

    if not show_archived:
        query = query.filter(Category.is_archived == 0)

    all_categories = query.order_by(Category.sort_order, Category.name).all()

    # Count archived
    archived_count_q = db.query(Category).filter(Category.user_id == user.id, Category.is_archived == 1)
    if account_id:
        archived_count_q = archived_count_q.filter(Category.account_id == account_id)
    archived_count = archived_count_q.count()

    # Build hierarchy: top-level (parent_id=None) with their children
    top_level = [c for c in all_categories if c.parent_id is None]
    children_map = {}
    for c in all_categories:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(c)

    # All non-archived categories for merge dropdown
    all_active = (
        db.query(Category)
        .filter(Category.user_id == user.id, Category.is_archived == 0)
        .order_by(Category.name)
        .all()
    )

    return templates.TemplateResponse(
        "categories/list.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "top_level": top_level,
            "children_map": children_map,
            "show_archived": show_archived,
            "archived_count": archived_count,
            "all_active": all_active,
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

    if acc_id:
        account = (
            db.query(Account)
            .filter(Account.id == acc_id, Account.user_id == user.id)
            .first()
        )
        if not account:
            return RedirectResponse("/categories", status_code=302)

    if par_id:
        parent = (
            db.query(Category)
            .filter(Category.id == par_id, Category.user_id == user.id)
            .first()
        )
        if not parent:
            return RedirectResponse("/categories", status_code=302)
        acc_id = parent.account_id
        is_income = parent.is_income

    max_order = (
        db.query(Category.sort_order)
        .filter(Category.user_id == user.id, Category.parent_id == par_id)
        .order_by(Category.sort_order.desc())
        .first()
    )
    next_order = (max_order[0] + 1) if max_order and max_order[0] is not None else 0

    cat = Category(
        user_id=user.id,
        account_id=acc_id,
        name=name.strip(),
        parent_id=par_id,
        color=color.strip() or None,
        is_income=is_income,
        sort_order=next_order,
    )
    db.add(cat)
    db.commit()

    redirect = "/categories"
    if acc_id:
        redirect += f"?account_id={acc_id}"
    return RedirectResponse(redirect, status_code=302)


@router.post("/{category_id}/edit")
def edit_category(
    request: Request,
    category_id: int,
    name: str = Form(...),
    account_id: int = Form(0),
    color: str = Form(""),
    is_income: int = Form(0),
    exclude_from_budget: int = Form(0),
    exclude_from_totals: int = Form(0),
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

    acc_id = account_id if account_id else None

    if acc_id:
        account = (
            db.query(Account)
            .filter(Account.id == acc_id, Account.user_id == user.id)
            .first()
        )
        if not account:
            return RedirectResponse("/categories", status_code=302)

    cat.name = name.strip()
    cat.color = color.strip() or None
    cat.exclude_from_budget = exclude_from_budget
    cat.exclude_from_totals = exclude_from_totals

    if cat.parent_id is None:
        cat.account_id = acc_id
        cat.is_income = is_income

        children = (
            db.query(Category)
            .filter(Category.parent_id == category_id, Category.user_id == user.id)
            .all()
        )
        for child in children:
            child.account_id = acc_id
            child.is_income = is_income

    db.commit()
    return RedirectResponse("/categories", status_code=302)


@router.post("/{category_id}/archive")
def archive_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
):
    """Toggle is_archived on a category (and its children)."""
    user = require_login(request, db)

    cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if cat:
        new_state = 0 if cat.is_archived else 1
        cat.is_archived = new_state
        # Cascade to children
        db.query(Category).filter(
            Category.parent_id == category_id,
            Category.user_id == user.id,
        ).update({"is_archived": new_state})
        db.commit()

    return RedirectResponse("/categories", status_code=302)


@router.post("/merge")
def merge_categories(
    request: Request,
    from_id: int = Form(...),
    to_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Move all transactions from category A to category B, then delete A."""
    user = require_login(request, db)

    if from_id == to_id:
        return RedirectResponse("/categories", status_code=302)

    from_cat = db.query(Category).filter(Category.id == from_id, Category.user_id == user.id).first()
    to_cat = db.query(Category).filter(Category.id == to_id, Category.user_id == user.id).first()

    if not from_cat or not to_cat:
        return RedirectResponse("/categories", status_code=302)

    # Move all transactions
    db.query(Transaction).filter(Transaction.category_id == from_id).update(
        {"category_id": to_id}
    )

    # Move children to target (re-parent)
    db.query(Category).filter(
        Category.parent_id == from_id, Category.user_id == user.id
    ).update({"parent_id": to_id})

    # Delete the source category
    db.delete(from_cat)
    db.commit()

    return RedirectResponse("/categories", status_code=302)


class ReorderItem(BaseModel):
    id: int
    sort_order: int


class ReorderRequest(BaseModel):
    items: List[ReorderItem]


@router.post("/reorder")
def reorder_categories(
    request: Request,
    payload: ReorderRequest,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    ids = [item.id for item in payload.items]
    categories = (
        db.query(Category)
        .filter(Category.id.in_(ids), Category.user_id == user.id)
        .all()
    )
    cat_map = {c.id: c for c in categories}

    for item in payload.items:
        if item.id in cat_map:
            cat_map[item.id].sort_order = item.sort_order

    db.commit()
    return JSONResponse({"ok": True})


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

    db.query(Category).filter(
        Category.parent_id == category_id,
        Category.user_id == user.id,
    ).delete()

    db.delete(cat)
    db.commit()

    return RedirectResponse("/categories", status_code=302)
