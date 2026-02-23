from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Tag, Transaction, transaction_tags
from app.auth import require_login

router = APIRouter(prefix="/tags")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def tags_list(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # Get tags with usage count
    tags_with_count = (
        db.query(
            Tag,
            func.count(transaction_tags.c.transaction_id).label("usage_count"),
        )
        .outerjoin(transaction_tags, transaction_tags.c.tag_id == Tag.id)
        .filter(Tag.user_id == user.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
        .all()
    )

    return templates.TemplateResponse(
        "tags/list.html",
        {
            "request": request,
            "user": user,
            "tags_with_count": tags_with_count,
        },
    )


@router.post("")
def create_tag(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse("/tags", status_code=302)

    # Check for duplicate
    existing = db.query(Tag).filter(
        Tag.user_id == user.id, Tag.name == name
    ).first()
    if existing:
        return RedirectResponse("/tags", status_code=302)

    tag = Tag(user_id=user.id, name=name)
    db.add(tag)
    db.commit()

    return RedirectResponse("/tags", status_code=302)


@router.post("/{tag_id}/edit")
def edit_tag(
    tag_id: int,
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
    if not tag:
        return RedirectResponse("/tags", status_code=302)

    name = name.strip()
    if name:
        tag.name = name
        db.commit()

    return RedirectResponse("/tags", status_code=302)


@router.post("/{tag_id}/delete")
def delete_tag(
    tag_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
    if tag:
        db.delete(tag)
        db.commit()

    return RedirectResponse("/tags", status_code=302)
