from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.auth import require_login
from app.database import get_db
from app.models import Account, Category, Transaction
from app.template_config import templates

router = APIRouter()


def _inbox_query(db: Session, user_id: int):
    """Transacties zonder categorie, excl. split-parents, projecties en excluded."""
    split_parent_ids = (
        db.query(Transaction.parent_id)
        .filter(Transaction.parent_id.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    return (
        db.query(Transaction)
        .join(Account)
        .options(joinedload(Transaction.account))
        .filter(
            Account.user_id == user_id,
            Transaction.category_id.is_(None),
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.id.notin_(split_parent_ids),
        )
    )


def inbox_count(db: Session, user_id: int) -> int:
    return _inbox_query(db, user_id).count()


def _grouped_categories(db: Session, user_id: int):
    """Return (parents, children_by_parent_id) — alleen actieve (niet-gearchiveerde) categorieën."""
    cats = (
        db.query(Category)
        .filter(Category.user_id == user_id, Category.is_archived == 0)
        .order_by(Category.sort_order, Category.name)
        .all()
    )
    parents = [c for c in cats if c.parent_id is None]
    children_by_parent: dict[int, list[Category]] = {}
    for c in cats:
        if c.parent_id is not None:
            children_by_parent.setdefault(c.parent_id, []).append(c)
    return parents, children_by_parent


@router.get("/inbox")
def inbox_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    transactions = (
        _inbox_query(db, user.id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )
    parents, children_by_parent = _grouped_categories(db, user.id)

    return templates.TemplateResponse(
        "inbox/index.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "parents": parents,
            "children_by_parent": children_by_parent,
            "inbox_total": len(transactions),
        },
    )


@router.post("/inbox/{transaction_id}/category")
def set_category(
    request: Request,
    transaction_id: int,
    category_id: int = Form(...),
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
        return RedirectResponse("/inbox", status_code=303)

    # Verifieer dat de categorie van deze gebruiker is
    cat = (
        db.query(Category)
        .filter(Category.id == category_id, Category.user_id == user.id)
        .first()
    )
    if not cat:
        return RedirectResponse("/inbox", status_code=303)

    tx.category_id = cat.id
    tx.assigned_by_rule_id = None
    tx.is_reviewed = 1
    db.commit()

    return RedirectResponse("/inbox", status_code=303)
