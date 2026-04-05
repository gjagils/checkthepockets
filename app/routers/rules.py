from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from collections import defaultdict
from decimal import Decimal

from app.database import get_db
from app.models import Rule, Category, Tag, Transaction, Account, RuleSuggestion
from app.auth import require_login
from app.rules_engine import apply_rules_to_all, apply_single_rule, preview_single_rule, suggest_rules
from app.template_config import templates

router = APIRouter()

MATCH_FIELDS = {
    "description": "Omschrijving",
    "counterparty": "Tegenpartij",
    "counterparty_iban": "IBAN tegenpartij",
}

MATCH_TYPES = {
    "contains": "Bevat",
    "exact": "Is exact",
    "starts_with": "Begint met",
}


@router.get("/rules")
def rules_list(request: Request, from_tx: int = Query(None), db: Session = Depends(get_db)):
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
    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    suggestions = suggest_rules(db, user.id)

    from app.ai_suggest import ai_available
    show_ai_suggest = ai_available()

    rule_suggestions = (
        db.query(RuleSuggestion)
        .filter(RuleSuggestion.user_id == user.id)
        .order_by(RuleSuggestion.uncat_count.desc())
        .all()
    )
    analyze_status = request.query_params.get("analyze", "")

    # Build subcategories list for the suggestion dropdowns
    sub_categories = []
    for cat in categories:
        if cat.parent_id:
            parent = next((c for c in categories if c.id == cat.parent_id), None)
            sub_categories.append({"id": cat.id, "name": cat.name, "parent_name": parent.name if parent else ""})

    prefill = None
    if from_tx:
        tx = (
            db.query(Transaction)
            .join(Account)
            .filter(Transaction.id == from_tx, Account.user_id == user.id)
            .first()
        )
        if tx:
            prefill = {
                "name": tx.counterparty or tx.description or "",
                "match_field": "description",
                "match_type": "contains",
                "match_value": tx.description or tx.counterparty or "",
                "assign_category_id": tx.category_id or "",
                "tx_display": f"{tx.counterparty or tx.description or '?'}  ·  €{tx.amount}",
            }

    return templates.TemplateResponse(
        "rules/list.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "categories": categories,
            "tags": tags,
            "accounts": accounts,
            "suggestions": suggestions,
            "match_fields": MATCH_FIELDS,
            "match_types": MATCH_TYPES,
            "prefill": prefill,
            "show_ai_suggest": show_ai_suggest,
            "rule_suggestions": rule_suggestions,
            "sub_categories": sub_categories,
            "analyze_status": analyze_status,
        },
    )


@router.post("/rules/analyze")
def analyze_rules(request: Request, db: Session = Depends(get_db)):
    """Analyze all transactions and suggest rules based on patterns."""
    user = require_login(request, db)

    from app.ai_suggest import parse_description, suggest_rules_bulk, ai_available

    # Fetch all non-excluded, non-projected transactions
    all_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.is_excluded == 0, Transaction.is_projected == 0)
        .all()
    )

    # Group by extracted merchant
    groups = defaultdict(lambda: {"txs": [], "uncat": 0, "cat": 0, "descs": [], "cat_votes": defaultdict(int)})
    for tx in all_txs:
        desc = tx.description or ""
        cp = tx.counterparty or ""
        parsed = parse_description(desc)
        merchant = parsed.get("merchant", cp or desc).strip()
        if not merchant:
            continue

        key = merchant.lower()
        groups[key]["txs"].append(tx)
        groups[key]["merchant"] = merchant
        if len(groups[key]["descs"]) < 3:
            groups[key]["descs"].append(desc[:120])
        if tx.category_id:
            groups[key]["cat"] += 1
            groups[key]["cat_votes"][tx.category_id] += 1
        else:
            groups[key]["uncat"] += 1

    # Filter: minimum 2 transactions, sort by uncat count
    # Build candidate list with most-voted category
    cat_map_all = {c.id: c for c in db.query(Category).filter(Category.user_id == user.id).all()}
    candidates = []
    for g in groups.values():
        if len(g["txs"]) < 2:
            continue
        top_cat_id = max(g["cat_votes"], key=g["cat_votes"].get) if g["cat_votes"] else None
        top_cat = cat_map_all.get(top_cat_id) if top_cat_id else None
        candidates.append({
            "merchant": g["merchant"],
            "match_value": g["merchant"],
            "uncat_count": g["uncat"],
            "cat_count": g["cat"],
            "sample_descriptions": g["descs"],
            "top_category_id": top_cat_id,
            "top_category_name": top_cat.name if top_cat else None,
        })
    candidates.sort(key=lambda c: c["uncat_count"], reverse=True)

    # Filter out merchants that already have a rule
    existing_rules = db.query(Rule).filter(Rule.user_id == user.id).all()
    existing_values = {r.match_value.lower() for r in existing_rules}
    candidates = [c for c in candidates if c["match_value"].lower() not in existing_values]

    if not candidates:
        return RedirectResponse("/rules?analyze=empty", status_code=302)

    # Build categories list with parent info for AI
    all_cats = db.query(Category).filter(Category.user_id == user.id).order_by(Category.name).all()
    cat_map = {c.id: c for c in all_cats}
    categories_for_ai = []
    for c in all_cats:
        parent_name = cat_map[c.parent_id].name if c.parent_id and c.parent_id in cat_map else None
        categories_for_ai.append({"id": c.id, "name": c.name, "parent_name": parent_name})

    # AI enrichment
    ai_results = None
    ai_error = False
    if ai_available():
        ai_results = suggest_rules_bulk(candidates[:25], categories_for_ai)
        if ai_results is None:
            ai_error = True

    # Clear old suggestions and write new ones
    db.query(RuleSuggestion).filter(RuleSuggestion.user_id == user.id).delete()

    if ai_results:
        # Match AI results back to candidates by match_value
        candidate_map = {c["match_value"].lower(): c for c in candidates}
        for ai in ai_results:
            mv = (ai.get("match_value") or "").lower()
            cand = candidate_map.get(mv)
            if not cand:
                for k, v in candidate_map.items():
                    if mv in k or k in mv:
                        cand = v
                        break
            db.add(RuleSuggestion(
                user_id=user.id,
                match_value=ai.get("match_value", mv),
                match_field=ai.get("match_field", "description"),
                counterparty_clean=ai.get("counterparty_clean"),
                category_id=ai.get("category_id"),
                category_name=ai.get("category_name"),
                reasoning=ai.get("reasoning"),
                uncat_count=cand["uncat_count"] if cand else 0,
                cat_count=cand["cat_count"] if cand else 0,
            ))
    else:
        # Fallback: use raw candidates WITH most-voted category from transaction data
        for c in candidates[:25]:
            db.add(RuleSuggestion(
                user_id=user.id,
                match_value=c["match_value"],
                match_field="description",
                counterparty_clean=c["merchant"],
                category_id=c.get("top_category_id"),
                category_name=c.get("top_category_name"),
                reasoning=f"{c['uncat_count'] + c['cat_count']}x gevonden" + (
                    " (AI niet beschikbaar)" if ai_error else ""
                ),
                uncat_count=c["uncat_count"],
                cat_count=c["cat_count"],
            ))

    db.commit()
    status = "done" if not ai_error else "done_no_ai"
    return RedirectResponse(f"/rules?analyze={status}", status_code=302)


@router.post("/rules/suggestion/{suggestion_id}/accept")
async def accept_rule_suggestion(
    suggestion_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept a rule suggestion — create rule and optionally apply to existing transactions."""
    user = require_login(request, db)
    form = await request.form()

    s = db.query(RuleSuggestion).filter(
        RuleSuggestion.id == suggestion_id, RuleSuggestion.user_id == user.id
    ).first()
    if not s:
        return RedirectResponse("/rules", status_code=302)

    # Read editable fields from form (user may have changed them)
    match_value = (form.get("match_value") or s.match_value).strip()
    counterparty_clean = (form.get("counterparty_clean") or s.counterparty_clean or "").strip()
    category_id_raw = (form.get("category_id") or "").strip()
    category_id = int(category_id_raw) if category_id_raw else s.category_id
    apply_existing = form.get("apply_existing") == "1"

    # Validate category ownership
    if category_id:
        cat = db.query(Category).filter(Category.id == category_id, Category.user_id == user.id).first()
        if not cat:
            category_id = None

    # Create the rule
    rule = Rule(
        user_id=user.id,
        name=f"{counterparty_clean or match_value}",
        match_field="description",
        match_type="contains",
        match_value=match_value,
        assign_category_id=category_id,
        action_rename_counterparty=counterparty_clean or None,
        action_set_reviewed=1,
    )
    db.add(rule)
    db.flush()

    # Apply to transactions
    applied = 0
    all_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.is_excluded == 0, Transaction.is_projected == 0)
        .all()
    )
    for tx in all_txs:
        desc = (tx.description or "").lower()
        cp = (tx.counterparty or "").lower()
        if match_value.lower() not in desc and match_value.lower() not in cp:
            continue
        # Skip already categorized unless apply_existing is checked
        if tx.category_id and not apply_existing:
            continue
        if category_id:
            tx.category_id = category_id
        if counterparty_clean:
            tx.counterparty = counterparty_clean
        tx.is_reviewed = 1
        applied += 1

    # Delete the suggestion
    db.delete(s)
    db.commit()

    return RedirectResponse(f"/rules?applied={applied}", status_code=302)


@router.post("/rules/suggestion/{suggestion_id}/dismiss")
def dismiss_rule_suggestion(suggestion_id: int, request: Request, db: Session = Depends(get_db)):
    """Dismiss a rule suggestion."""
    user = require_login(request, db)
    s = db.query(RuleSuggestion).filter(
        RuleSuggestion.id == suggestion_id, RuleSuggestion.user_id == user.id
    ).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/suggestions/clear")
def clear_rule_suggestions(request: Request, db: Session = Depends(get_db)):
    """Delete all rule suggestions for the current user."""
    user = require_login(request, db)
    db.query(RuleSuggestion).filter(RuleSuggestion.user_id == user.id).delete()
    db.commit()
    return RedirectResponse("/rules", status_code=302)


@router.post("/rules/suggest")
async def suggest_rule_endpoint(request: Request, db: Session = Depends(get_db)):
    """AI-powered rule suggestion from a transaction description."""
    user = require_login(request, db)
    form = await request.form()

    transaction_id = (form.get("transaction_id") or "").strip()
    description = (form.get("description") or "").strip()
    counterparty = (form.get("counterparty") or "").strip()

    # If transaction_id is given, look up the transaction
    if transaction_id:
        tx = (
            db.query(Transaction)
            .join(Account)
            .filter(Transaction.id == int(transaction_id), Account.user_id == user.id)
            .first()
        )
        if tx:
            description = tx.description or ""
            counterparty = tx.counterparty or ""

    if not description and not counterparty:
        return JSONResponse({"suggestion": None, "error": "Geen beschrijving opgegeven."})

    categories = [
        {"id": c.id, "name": c.name}
        for c in db.query(Category).filter(Category.user_id == user.id).order_by(Category.name).all()
    ]

    from app.ai_suggest import suggest_rule, parse_description, ai_available

    # Always do regex parsing first
    parsed = parse_description(description)

    if not ai_available():
        return JSONResponse({"suggestion": {
            "match_value": parsed.get("merchant", ""),
            "match_field": "description",
            "counterparty_clean": parsed.get("merchant", ""),
            "category_id": None,
            "category_name": None,
            "reasoning": "AI-suggesties niet beschikbaar (ANTHROPIC_API_KEY niet ingesteld). "
                         "Regex-extractie: " + parsed.get("type", "unknown"),
        }})

    result = suggest_rule(description, counterparty, categories)
    if not result:
        # Fallback to regex only
        return JSONResponse({"suggestion": {
            "match_value": parsed.get("merchant", ""),
            "match_field": "description",
            "counterparty_clean": parsed.get("merchant", ""),
            "category_id": None,
            "category_name": None,
            "reasoning": "AI-suggestie mislukt; alleen regex-extractie beschikbaar.",
        }})

    return JSONResponse({"suggestion": result})


@router.post("/rules")
def create_rule(
    request: Request,
    name: str = Form(...),
    match_field: str = Form(...),
    match_type: str = Form(...),
    match_value: str = Form(...),
    amount_min: str = Form(""),
    amount_max: str = Form(""),
    condition_account_id: str = Form(""),
    assign_category_id: str = Form(""),
    assign_tag_id: str = Form(""),
    action_rename_counterparty: str = Form(""),
    action_set_reviewed: str = Form(""),
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

    # Parse optional IDs
    cat_id = int(assign_category_id) if assign_category_id.strip() else None
    tag_id = int(assign_tag_id) if assign_tag_id.strip() else None
    acc_id = int(condition_account_id) if condition_account_id.strip() else None

    # Validate ownership
    if cat_id:
        cat = db.query(Category).filter(Category.id == cat_id, Category.user_id == user.id).first()
        if not cat:
            cat_id = None
    if tag_id:
        tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
        if not tag:
            tag_id = None
    if acc_id:
        acc = db.query(Account).filter(Account.id == acc_id, Account.user_id == user.id).first()
        if not acc:
            acc_id = None

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
        condition_account_id=acc_id,
        assign_category_id=cat_id,
        assign_tag_id=tag_id,
        action_rename_counterparty=action_rename_counterparty.strip() or None,
        action_set_reviewed=1 if action_set_reviewed else 0,
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
    condition_account_id: str = Form(""),
    assign_category_id: str = Form(""),
    assign_tag_id: str = Form(""),
    action_rename_counterparty: str = Form(""),
    action_set_reviewed: str = Form(""),
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

    # Parse optional IDs
    cat_id = int(assign_category_id) if assign_category_id.strip() else None
    tag_id = int(assign_tag_id) if assign_tag_id.strip() else None
    acc_id = int(condition_account_id) if condition_account_id.strip() else None

    if cat_id:
        cat = db.query(Category).filter(Category.id == cat_id, Category.user_id == user.id).first()
        rule.assign_category_id = cat.id if cat else None
    else:
        rule.assign_category_id = None

    if tag_id:
        tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user.id).first()
        rule.assign_tag_id = tag.id if tag else None
    else:
        rule.assign_tag_id = None

    if acc_id:
        acc = db.query(Account).filter(Account.id == acc_id, Account.user_id == user.id).first()
        rule.condition_account_id = acc.id if acc else None
    else:
        rule.condition_account_id = None

    rule.action_rename_counterparty = action_rename_counterparty.strip() or None
    rule.action_set_reviewed = 1 if action_set_reviewed else 0

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


@router.get("/rules/{rule_id}/preview")
def preview_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    transactions = preview_single_rule(db, user.id, rule_id)
    return JSONResponse({"transactions": transactions})


@router.post("/rules/{rule_id}/apply")
def apply_one_rule(
    rule_id: int,
    request: Request,
    only_uncategorized: str = Form(""),
    transaction_ids: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    # If specific transaction IDs were provided (from preview modal), use those
    parsed_ids = None
    if transaction_ids.strip():
        parsed_ids = [int(x) for x in transaction_ids.split(",") if x.strip().isdigit()]

    affected = apply_single_rule(
        db, user.id, rule_id,
        only_uncategorized=bool(only_uncategorized),
        transaction_ids=parsed_ids,
    )
    return RedirectResponse(f"/rules?applied={affected}", status_code=302)


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
