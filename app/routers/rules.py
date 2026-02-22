from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Rule, Category, Tag
from app.auth import require_login
from app.rules_engine import apply_rules_to_all, suggest_rules

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MATCH_FIELDS = {
    "counterparty": "Tegenpartij",
    "description": "Omschrijving",
    "counterparty_iban": "IBAN tegenpartij",
}

MATCH_TYPES = {
    "contains": "Bevat",
    "exact": "Is exact",
    "starts_with": "Begint met",
}


@router.get("/rules")
def rules_list(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    rules = (
        db.query(Rule)
        .filter(Rule.user_id == user.id)
        .order_by(Rule.is_active.desc(), Rule.name)
        .all()
    )
    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.name)
        .all()
    )
    tags = (
        db.query(Tag)
        .filter(Tag.user_id == user.id)
        .order_by(Tag.name)
        .all()
    )

    suggestions = suggest_rules(db, user.id)

    return templates.TemplateResponse(
        "rules/list.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "categories": categories,
            "tags": tags,
            "suggestions": suggestions,
            "match_fields": MATCH_FIELDS,
            "match_types": MATCH_TYPES,
        },
    )


@router.post("/rules")
def create_rule(
    request: Request,
    name: str = Form(...),
    match_field: str = Form(...),
    match_type: str = Form(...),
    match_value: str = Form(...),
    amount_min: str = Form(""),
    amount_max: str = Form(""),
    assign_category_id: int | None = Form(None),
    assign_tag_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    name = name.strip()
    match_value = match_value.strip()
    if not name or not match_value:
        return RedirectResponse("/rules", status_code=302)
    if match_field not in MATCH_FIELDS:
        return RedirectResponse("/rules", status_code=302)
    if match_type not in MATCH_TYPES:
        return RedirectResponse("/rules", status_code=302)

    # Validate category/tag belong to user
    if assign_category_id:
        cat = db.query(Category).filter(
            Category.id == assign_category_id, Category.user_id == user.id
        ).first()
        if not cat:
            assign_category_id = None

    if assign_tag_id:
        tag = db.query(Tag).filter(
            Tag.id == assign_tag_id, Tag.user_id == user.id
        ).first()
        if not tag:
            assign_tag_id = None

    # Parse amounts
    parsed_min = None
    parsed_max = None
    if amount_min.strip():
        try:
            parsed_min = Decimal(amount_min.strip())
        except InvalidOperation:
            pass
    if amount_max.strip():
        try:
            parsed_max = Decimal(amount_max.strip())
        except InvalidOperation:
            pass

    rule = Rule(
        user_id=user.id,
        name=name,
        match_field=match_field,
        match_type=match_type,
        match_value=match_value,
        amount_min=parsed_min,
        amount_max=parsed_max,
        assign_category_id=assign_category_id,
        assign_tag_id=assign_tag_id,
    )
    db.add(rule)
    db.commit()

    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/{rule_id}/edit")
def edit_rule(
    rule_id: int,
    request: Request,
    name: str = Form(...),
    match_field: str = Form(...),
    match_type: str = Form(...),
    match_value: str = Form(...),
    amount_min: str = Form(""),
    amount_max: str = Form(""),
    assign_category_id: int | None = Form(None),
    assign_tag_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.user_id == user.id).first()
    if not rule:
        return RedirectResponse("/rules", status_code=302)

    name = name.strip()
    match_value = match_value.strip()
    if not name or not match_value:
        return RedirectResponse("/rules", status_code=302)

    rule.name = name
    rule.match_field = match_field if match_field in MATCH_FIELDS else rule.match_field
    rule.match_type = match_type if match_type in MATCH_TYPES else rule.match_type
    rule.match_value = match_value

    if amount_min.strip():
        try:
            rule.amount_min = Decimal(amount_min.strip())
        except InvalidOperation:
            pass
    else:
        rule.amount_min = None

    if amount_max.strip():
        try:
            rule.amount_max = Decimal(amount_max.strip())
        except InvalidOperation:
            pass
    else:
        rule.amount_max = None

    if assign_category_id:
        cat = db.query(Category).filter(
            Category.id == assign_category_id, Category.user_id == user.id
        ).first()
        rule.assign_category_id = cat.id if cat else None
    else:
        rule.assign_category_id = None

    if assign_tag_id:
        tag = db.query(Tag).filter(
            Tag.id == assign_tag_id, Tag.user_id == user.id
        ).first()
        rule.assign_tag_id = tag.id if tag else None
    else:
        rule.assign_tag_id = None

    db.commit()
    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/{rule_id}/toggle")
def toggle_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.user_id == user.id).first()
    if rule:
        rule.is_active = 0 if rule.is_active else 1
        db.commit()
    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/{rule_id}/delete")
def delete_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.user_id == user.id).first()
    if rule:
        db.delete(rule)
        db.commit()
    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/apply")
def apply_all_rules(
    request: Request,
    only_uncategorized: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    affected = apply_rules_to_all(db, user.id, only_uncategorized=bool(only_uncategorized))
    # Redirect back with result count via query param
    return RedirectResponse(f"/rules?applied={affected}", status_code=302)
