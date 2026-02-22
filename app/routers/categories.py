from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Transaction
from app.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DEFAULT_COLORS = [
    "#1F6FB2", "#2DBE60", "#F2B233", "#E54D4D", "#9B59B6",
    "#1ABC9C", "#E67E22", "#3498DB", "#E91E63", "#00BCD4",
]


@router.get("/categories")
def categories_list(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    # Get top-level categories (no parent) with their children
    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id, Category.parent_id.is_(None))
        .order_by(Category.name)
        .all()
    )

    all_categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )

    return templates.TemplateResponse(
        "categories/list.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "all_categories": all_categories,
            "default_colors": DEFAULT_COLORS,
        },
    )


@router.post("/categories")
def create_category(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    color: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    name = name.strip()
    parent_id = int(parent_id) if parent_id.strip() else None

    if not name:
        return RedirectResponse("/categories", status_code=302)

    # Check for duplicate
    existing = (
        db.query(Category)
        .filter(Category.user_id == user.id, Category.name == name)
        .first()
    )
    if existing:
        return RedirectResponse("/categories", status_code=302)

    # Validate parent belongs to user
    if parent_id:
        parent = (
            db.query(Category)
            .filter(Category.id == parent_id, Category.user_id == user.id)
            .first()
        )
        if not parent:
            parent_id = None

    category = Category(
        user_id=user.id,
        name=name,
        parent_id=parent_id if parent_id else None,
        color=color or None,
    )
    db.add(category)
    db.commit()

    return RedirectResponse("/categories", status_code=302)


@router.post("/categories/{category_id}/edit")
def edit_category(
    category_id: int,
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    color: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not category:
        return RedirectResponse("/categories", status_code=302)

    name = name.strip()
    parent_id = int(parent_id) if parent_id.strip() else None
    if not name:
        return RedirectResponse("/categories", status_code=302)

    # Prevent setting self as parent or a child as parent
    if parent_id == category_id:
        parent_id = None

    # Validate parent belongs to user and is not a child of this category
    if parent_id:
        parent = (
            db.query(Category)
            .filter(Category.id == parent_id, Category.user_id == user.id)
            .first()
        )
        if not parent or parent.parent_id == category_id:
            parent_id = None

    category.name = name
    category.parent_id = parent_id if parent_id else None
    category.color = color or None
    db.commit()

    return RedirectResponse("/categories", status_code=302)


@router.post("/categories/{category_id}/delete")
def delete_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not category:
        return RedirectResponse("/categories", status_code=302)

    # Move child categories to parent (or top-level)
    for child in category.children:
        child.parent_id = category.parent_id

    # Unset category on transactions
    db.query(Transaction).filter(Transaction.category_id == category_id).update(
        {"category_id": None}
    )

    db.delete(category)
    db.commit()

    return RedirectResponse("/categories", status_code=302)
