import json
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
import io

from app.database import get_db
from app.models import Category, Tag, Rule, RecurringTransaction, Budget
from app.auth import require_login
from app.template_config import templates

router = APIRouter(prefix="/settings")


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


@router.get("/export")
def export_settings(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    # Categories: parents first, then children (so import can resolve parent names)
    all_cats = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.parent_id.is_(None).desc(), Category.sort_order, Category.id)
        .all()
    )
    # Build id→name map for parent resolution
    cat_id_name = {c.id: c.name for c in all_cats}

    categories_export = []
    for c in all_cats:
        categories_export.append({
            "name": c.name,
            "parent_name": cat_id_name.get(c.parent_id) if c.parent_id else None,
            "color": c.color,
            "is_income": c.is_income,
            "sort_order": c.sort_order,
            "exclude_from_budget": c.exclude_from_budget,
            "exclude_from_totals": c.exclude_from_totals,
            "is_archived": c.is_archived,
        })

    # Tags
    tags_export = [
        {"name": t.name, "color": t.color, "is_archived": t.is_archived}
        for t in db.query(Tag).filter(Tag.user_id == user.id).order_by(Tag.name).all()
    ]

    # Rules (store category/tag by name, not ID)
    rules_export = []
    for r in db.query(Rule).filter(Rule.user_id == user.id).order_by(Rule.id).all():
        rules_export.append({
            "name": r.name,
            "is_active": r.is_active,
            "match_field": r.match_field,
            "match_type": r.match_type,
            "match_value": r.match_value,
            "amount_min": r.amount_min,
            "amount_max": r.amount_max,
            "assign_category_name": r.assign_category.name if r.assign_category else None,
            "assign_tag_name": r.assign_tag.name if r.assign_tag else None,
        })

    # Recurring transactions
    recurring_export = []
    for rt in (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user.id)
        .order_by(RecurringTransaction.id)
        .all()
    ):
        recurring_export.append({
            "name": rt.name,
            "amount_expected": rt.amount_expected,
            "frequency": rt.frequency,
            "category_name": rt.category.name if rt.category else None,
            "counterparty": rt.counterparty,
            "description_match": rt.description_match,
            "is_active": rt.is_active,
            "start_date": rt.start_date,
            "end_date": rt.end_date,
            "active_months": rt.active_months,
        })

    # Budgets (recent 12 months to keep export compact but useful)
    budgets_export = []
    for b in db.query(Budget).filter(Budget.user_id == user.id).order_by(Budget.year, Budget.month, Budget.id).all():
        cat = db.query(Category).filter(Category.id == b.category_id).first()
        budgets_export.append({
            "year": b.year,
            "month": b.month,
            "category_name": cat.name if cat else None,
            "amount": b.amount,
        })

    payload = {
        "version": 1,
        "categories": categories_export,
        "tags": tags_export,
        "rules": rules_export,
        "recurring": recurring_export,
        "budgets": budgets_export,
    }

    json_bytes = json.dumps(payload, default=_decimal_default, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=checkthepockets-export.json"},
    )


@router.post("/import/preview")
async def import_preview(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except Exception:
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "import_error": "Ongeldig JSON-bestand."},
        )

    if data.get("version") != 1:
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "import_error": "Onbekende versie van het exportbestand."},
        )

    counts = {
        "categories": len(data.get("categories", [])),
        "tags": len(data.get("tags", [])),
        "rules": len(data.get("rules", [])),
        "recurring": len(data.get("recurring", [])),
        "budgets": len(data.get("budgets", [])),
    }

    # Pass JSON as hidden field so confirm can use it without a session
    raw_json = content.decode("utf-8")

    return templates.TemplateResponse(
        "settings/import_preview.html",
        {
            "request": request,
            "user": user,
            "counts": counts,
            "raw_json": raw_json,
        },
    )


@router.post("/import/confirm")
async def import_confirm(
    request: Request,
    raw_json: str = Form(...),
    strategy: str = Form("overwrite"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    skip_existing = strategy == "skip"

    try:
        data = json.loads(raw_json)
    except Exception:
        return RedirectResponse("/settings?error=json", status_code=302)

    stats = {"categories": 0, "tags": 0, "rules": 0, "recurring": 0, "budgets": 0, "skipped": 0}

    # --- Categories ---
    # Build local name→id map as we upsert (parents first)
    cat_name_to_id = {
        c.name: c.id
        for c in db.query(Category).filter(Category.user_id == user.id).all()
    }

    for cat in data.get("categories", []):
        name = cat.get("name", "").strip()
        if not name:
            continue
        parent_id = None
        if cat.get("parent_name"):
            parent_id = cat_name_to_id.get(cat["parent_name"])

        existing = db.query(Category).filter(
            Category.user_id == user.id, Category.name == name
        ).first()
        if existing:
            if skip_existing:
                cat_name_to_id[name] = existing.id
                stats["skipped"] += 1
                continue
            existing.color = cat.get("color") or existing.color
            existing.is_income = cat.get("is_income", existing.is_income)
            existing.sort_order = cat.get("sort_order", existing.sort_order)
            existing.exclude_from_budget = cat.get("exclude_from_budget", existing.exclude_from_budget)
            existing.exclude_from_totals = cat.get("exclude_from_totals", existing.exclude_from_totals)
            existing.is_archived = cat.get("is_archived", existing.is_archived)
            if parent_id is not None:
                existing.parent_id = parent_id
            db.flush()
            cat_name_to_id[name] = existing.id
        else:
            new_cat = Category(
                user_id=user.id,
                name=name,
                parent_id=parent_id,
                color=cat.get("color"),
                is_income=cat.get("is_income", 0),
                sort_order=cat.get("sort_order", 0),
                exclude_from_budget=cat.get("exclude_from_budget", 0),
                exclude_from_totals=cat.get("exclude_from_totals", 0),
                is_archived=cat.get("is_archived", 0),
            )
            db.add(new_cat)
            db.flush()
            cat_name_to_id[name] = new_cat.id
            stats["categories"] += 1

    db.commit()

    # Rebuild full cat_name_to_id after commit
    cat_name_to_id = {
        c.name: c.id
        for c in db.query(Category).filter(Category.user_id == user.id).all()
    }

    # --- Tags ---
    tag_name_to_id = {
        t.name: t.id
        for t in db.query(Tag).filter(Tag.user_id == user.id).all()
    }

    for tag in data.get("tags", []):
        name = tag.get("name", "").strip()
        if not name:
            continue
        existing = db.query(Tag).filter(Tag.user_id == user.id, Tag.name == name).first()
        if existing:
            if skip_existing:
                tag_name_to_id[name] = existing.id
                stats["skipped"] += 1
                continue
            existing.color = tag.get("color") or existing.color
            existing.is_archived = tag.get("is_archived", existing.is_archived)
            db.flush()
            tag_name_to_id[name] = existing.id
        else:
            new_tag = Tag(
                user_id=user.id,
                name=name,
                color=tag.get("color"),
                is_archived=tag.get("is_archived", 0),
            )
            db.add(new_tag)
            db.flush()
            tag_name_to_id[name] = new_tag.id
            stats["tags"] += 1

    db.commit()

    # --- Rules ---
    for rule in data.get("rules", []):
        name = rule.get("name", "").strip()
        if not name:
            continue
        cat_id = cat_name_to_id.get(rule.get("assign_category_name")) if rule.get("assign_category_name") else None
        tag_id = tag_name_to_id.get(rule.get("assign_tag_name")) if rule.get("assign_tag_name") else None

        existing = db.query(Rule).filter(
            Rule.user_id == user.id,
            Rule.name == name,
            Rule.match_field == rule.get("match_field", ""),
            Rule.match_value == rule.get("match_value", ""),
        ).first()

        if existing:
            if skip_existing:
                stats["skipped"] += 1
                continue
            existing.match_type = rule.get("match_type", existing.match_type)
            existing.is_active = rule.get("is_active", existing.is_active)
            existing.assign_category_id = cat_id
            existing.assign_tag_id = tag_id
            amount_min = rule.get("amount_min")
            amount_max = rule.get("amount_max")
            existing.amount_min = Decimal(str(amount_min)) if amount_min is not None else None
            existing.amount_max = Decimal(str(amount_max)) if amount_max is not None else None
        else:
            amount_min = rule.get("amount_min")
            amount_max = rule.get("amount_max")
            new_rule = Rule(
                user_id=user.id,
                name=name,
                is_active=rule.get("is_active", 1),
                match_field=rule.get("match_field", "description"),
                match_type=rule.get("match_type", "contains"),
                match_value=rule.get("match_value", ""),
                amount_min=Decimal(str(amount_min)) if amount_min is not None else None,
                amount_max=Decimal(str(amount_max)) if amount_max is not None else None,
                assign_category_id=cat_id,
                assign_tag_id=tag_id,
            )
            db.add(new_rule)
            stats["rules"] += 1

    db.commit()

    # --- Recurring transactions ---
    for rt in data.get("recurring", []):
        name = rt.get("name", "").strip()
        if not name:
            continue
        cat_id = cat_name_to_id.get(rt.get("category_name")) if rt.get("category_name") else None

        existing = db.query(RecurringTransaction).filter(
            RecurringTransaction.user_id == user.id,
            RecurringTransaction.name == name,
        ).first()

        start_date = None
        end_date = None
        if rt.get("start_date"):
            try:
                start_date = date.fromisoformat(rt["start_date"])
            except Exception:
                pass
        if rt.get("end_date"):
            try:
                end_date = date.fromisoformat(rt["end_date"])
            except Exception:
                pass

        if existing:
            if skip_existing:
                stats["skipped"] += 1
                continue
            existing.amount_expected = Decimal(str(rt.get("amount_expected", existing.amount_expected)))
            existing.frequency = rt.get("frequency", existing.frequency)
            existing.category_id = cat_id
            existing.counterparty = rt.get("counterparty", existing.counterparty)
            existing.description_match = rt.get("description_match", existing.description_match)
            existing.is_active = rt.get("is_active", existing.is_active)
            existing.start_date = start_date
            existing.end_date = end_date
            existing.active_months = rt.get("active_months", existing.active_months)
        else:
            new_rt = RecurringTransaction(
                user_id=user.id,
                name=name,
                amount_expected=Decimal(str(rt.get("amount_expected", "0"))),
                frequency=rt.get("frequency", "monthly"),
                category_id=cat_id,
                counterparty=rt.get("counterparty"),
                description_match=rt.get("description_match"),
                is_active=rt.get("is_active", 1),
                start_date=start_date,
                end_date=end_date,
                active_months=rt.get("active_months"),
            )
            db.add(new_rt)
            stats["recurring"] += 1

    db.commit()

    # --- Budgets ---
    for b in data.get("budgets", []):
        cat_name = b.get("category_name")
        if not cat_name:
            continue
        cat_id = cat_name_to_id.get(cat_name)
        if not cat_id:
            continue
        year = b.get("year")
        month = b.get("month")
        if not year or not month:
            continue

        existing = db.query(Budget).filter(
            Budget.user_id == user.id,
            Budget.category_id == cat_id,
            Budget.year == year,
            Budget.month == month,
        ).first()

        amount = Decimal(str(b.get("amount", "0")))
        if existing:
            if skip_existing:
                stats["skipped"] += 1
                continue
            existing.amount = amount
        else:
            db.add(Budget(
                user_id=user.id,
                category_id=cat_id,
                year=year,
                month=month,
                amount=amount,
            ))
            stats["budgets"] += 1

    db.commit()

    msg = (
        f"Import voltooid: {stats['categories']} categorie(ën), "
        f"{stats['tags']} tag(s), {stats['rules']} regel(s), "
        f"{stats['recurring']} terugkerend, {stats['budgets']} budget(ten) nieuw toegevoegd."
    )
    if stats["skipped"]:
        msg += f" {stats['skipped']} bestaande item(s) overgeslagen."

    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user, "import_success": msg},
    )
