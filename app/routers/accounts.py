import json
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Account, AccountGroup, BankConnection, Transaction, SavingsPlan, Category, Rule, Person,
)
from app.account_groups import delete_empty_groups, group_label, set_account_group
from app.account_merge import merge_accounts, plan_merge
from app.auth import require_login
from app.ownership import get_owned_or_404
from app.template_config import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_merged(value: str | None) -> tuple[int, int] | None:
    try:
        moved, dup = (value or "").split("-")
        return int(moved), int(dup)
    except ValueError:
        return None


@router.get("/accounts")
def accounts_list(request: Request, merged: str | None = None, db: Session = Depends(get_db)):
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

    # Bouw lookup external_uid → BankConnection zodat we per rekening kunnen
    # tonen of deze via de bankkoppeling synchroniseert (en wanneer dat voor
    # het laatst gebeurde) of alleen via CSV-import is gevuld.
    connections = (
        db.query(BankConnection)
        .filter(
            BankConnection.user_id == user.id,
            BankConnection.status == "active",
        )
        .all()
    )
    bank_info_by_account_id: dict[int, dict] = {}
    # Twee lookups: primair op stabiele Enable-Banking uid, secundair op
    # (bank, iban). De IBAN-fallback dekt accounts die ooit via CSV zijn
    # aangemaakt vóór een latere bankkoppeling — die hebben external_uid=NULL
    # maar horen wel bij een actieve connection.
    uid_to_conn: dict[str, BankConnection] = {}
    iban_to_conn: dict[tuple[str, str], BankConnection] = {}
    for conn in connections:
        try:
            stored = json.loads(conn.accounts_json or "[]")
        except (ValueError, TypeError):
            stored = []
        bank_key = (conn.bank_name or "").lower().replace(" ", "_")
        for entry in stored:
            if not isinstance(entry, dict):
                continue
            uid = entry.get("uid")
            if uid:
                uid_to_conn[uid] = conn
            iban = (entry.get("iban") or "").replace(" ", "").upper()
            if iban and bank_key:
                iban_to_conn[(bank_key, iban)] = conn

    for acc in accounts:
        conn = None
        match_reason = None
        if acc.external_uid:
            conn = uid_to_conn.get(acc.external_uid)
            if conn:
                match_reason = "uid"
        if conn is None and acc.iban:
            iban_key = acc.iban.replace(" ", "").upper()
            conn = iban_to_conn.get(((acc.bank or "").lower(), iban_key))
            if conn:
                match_reason = "iban_fallback"
        if conn:
            bank_info_by_account_id[acc.id] = {
                "is_linked": True,
                "connection_id": conn.id,
                "connection_name": conn.display_name or conn.bank_name,
                "last_synced_at": conn.last_synced_at,
                "match_reason": match_reason,
                "missing_uid": match_reason == "iban_fallback",
            }
        else:
            bank_info_by_account_id[acc.id] = {
                "is_linked": False,
                "connection_id": None,
                "connection_name": None,
                "last_synced_at": None,
                "match_reason": None,
                "missing_uid": False,
            }

    # Datum laatste echte transactie per account — handig als referentie voor
    # CSV-import-rekeningen (bankkoppelingen tonen de sync-tijd, maar voor
    # handmatige imports is "wat zit er in de DB" een betere proxy).
    latest_tx_by_account_id: dict[int, object] = {}
    rows = (
        db.query(Transaction.account_id, func.max(Transaction.date))
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == user.id,
            Transaction.is_projected == 0,
        )
        .group_by(Transaction.account_id)
        .all()
    )
    for acc_id, max_date in rows:
        if acc_id is not None and max_date is not None:
            latest_tx_by_account_id[acc_id] = max_date

    return templates.TemplateResponse(
        request,
        "accounts/list.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "persons": persons,
            "group_choices": [
                (g.id, group_label(g))
                for g in db.query(AccountGroup).filter(AccountGroup.user_id == user.id).order_by(AccountGroup.name).all()
                if g.accounts
            ],
            "bank_info_by_account_id": bank_info_by_account_id,
            "latest_tx_by_account_id": latest_tx_by_account_id,
            "merged": _parse_merged(merged),
        },
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


@router.post("/accounts/{account_id}/group")
def set_group(
    account_id: int,
    request: Request,
    group_id: str = Form(""),
    db: Session = Depends(get_db),
):
    """Zet een rekening in een bestaande groep, of ("nieuw") in een eigen groep."""
    user = require_login(request, db)
    account = get_owned_or_404(db, Account, account_id, user.id)
    try:
        target = int(group_id) if group_id.strip().isdigit() else None
        set_account_group(db, account, target)
    except ValueError:
        db.rollback()
        return RedirectResponse("/accounts", status_code=302)
    db.commit()
    return RedirectResponse("/accounts", status_code=302)


@router.post("/accounts/groups/{group_id}/rename")
def rename_group(group_id: int, request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = require_login(request, db)
    group = get_owned_or_404(db, AccountGroup, group_id, user.id)
    name = " ".join(name.split())
    if name:
        group.name = name[:255]
        db.commit()
    return RedirectResponse("/accounts", status_code=302)


@router.post("/accounts/{account_id}/update")
def update_account(
    account_id: int,
    request: Request,
    name: str = Form(...),
    kind: str = Form(""),
    db: Session = Depends(get_db),
):
    """Rename an account and set whether it is a payment or savings account."""
    user = require_login(request, db)
    account = get_owned_or_404(db, Account, account_id, user.id)
    name = " ".join(name.split())
    if name:
        account.name = name[:255]
        if kind in ("payment", "savings"):
            account.kind = kind
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
        db.flush()
        delete_empty_groups(db, user.id)
        db.commit()
    return RedirectResponse("/accounts", status_code=302)


def _own_account(db: Session, user_id: int, account_id: int | None) -> Account | None:
    if account_id is None:
        return None
    return db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()


@router.get("/accounts/{account_id}/merge")
def merge_account_page(
    account_id: int,
    request: Request,
    target_id: int | None = None,
    db: Session = Depends(get_db),
    error: str | None = None,
):
    """Choose a target account and preview what merging would do."""
    user = require_login(request, db)
    source = get_owned_or_404(db, Account, account_id, user.id)
    others = (
        db.query(Account)
        .filter(Account.user_id == user.id, Account.id != source.id)
        .order_by(Account.name)
        .all()
    )
    target = _own_account(db, user.id, target_id)
    if target is not None and target.id == source.id:
        target = None
    plan = plan_merge(db, source, target) if target else None
    return templates.TemplateResponse(
        request,
        "accounts/merge.html",
        {
            "request": request, "user": user, "source": source, "others": others,
            "target": target, "plan": plan, "error": error,
            "move_count": len(plan.move) if plan else 0,
            "duplicate_count": len(plan.duplicates) if plan else 0,
        },
    )


@router.post("/accounts/{account_id}/merge")
def merge_account(
    account_id: int,
    request: Request,
    target_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    source = get_owned_or_404(db, Account, account_id, user.id)
    target = get_owned_or_404(db, Account, target_id, user.id)
    if source.id == target.id:
        return RedirectResponse("/accounts", status_code=303)
    try:
        result = merge_accounts(db, source, target)
        db.flush()
        delete_empty_groups(db, user.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Samenvoegen van rekening %s in %s mislukt", account_id, target_id)
        return merge_account_page(
            account_id, request, target_id=target_id, db=db,
            error="Samenvoegen is niet gelukt. Er is niets gewijzigd; zie de serverlog voor de oorzaak.",
        )
    logger.info(
        "Account %s samengevoegd in %s: %d verplaatst, %d dubbel samengevoegd",
        account_id, target.id, result.moved, result.merged_duplicates,
    )
    return RedirectResponse(f"/accounts?merged={result.moved}-{result.merged_duplicates}", status_code=302)
