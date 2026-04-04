from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Tag, Transaction, transaction_tags
from app.auth import require_login
from app.template_config import templates

router = APIRouter(prefix="/tags")


@router.get("")
def tags_list(
    request: Request,
    show_archived: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    query = (
        db.query(
            Tag,
            func.count(transaction_tags.c.transaction_id).label("usage_count"),
        )
        .outerjoin(transaction_tags, transaction_tags.c.tag_id == Tag.id)
        .filter(Tag.user_id == user.id)
    )

    if not show_archived:
        query = query.filter(Tag.is_archived == 0)

    tags_with_count = query.group_by(Tag.id).order_by(Tag.name).all()

    archived_count = db.query(Tag).filter(Tag.user_id == user.id, Tag.is_archived == 1).count()

    return templates.TemplateResponse(
        "tags/list.html",
        {
            "request": request,
            "user": user,
            "tags_with_count": tags_with_count,
            "show_archived": show_archived,
            "archived_count": archived_count,
        },
    )


@router.post("")
def create_tag(
    request: Request,
    name: str = Form(...),
    color: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse("/tags", status_code=302)

    existing = db.query(Tag).filter(Tag.user_id == user.id, Tag.name == name).first()
    if existing:
        return RedirectResponse("/tags", status_code=302)

    tag = Tag(user_id=user.id, name=name, color=color.strip() or None)
    db.add(tag)
    db.commit()

    return RedirectResponse("/tags", status_code=302)


@router.post("/{tag_id}/edit")
def edit_tag(
    tag_id: int,
    request: Request,
    name: str = Form(...),
    color: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
    if not tag:
        return RedirectResponse("/tags", status_code=302)

    name = name.strip()
    if name:
        tag.name = name
    tag.color = color.strip() or None
    db.commit()

    return RedirectResponse("/tags", status_code=302)


@router.post("/{tag_id}/archive")
def archive_tag(
    tag_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Toggle is_archived on a tag."""
    user = require_login(request, db)
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
    if tag:
        tag.is_archived = 0 if tag.is_archived else 1
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
