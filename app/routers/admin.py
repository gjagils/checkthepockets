import datetime
import secrets

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.database import get_db
from app.models import User, AuthToken, Account, Transaction, SchedulerRunLog
from app.auth import require_login
from app.config import SUPER_ADMIN_USERNAME
from app.email_service import send_invite_email
from app.crypto import encrypt_existing_transactions, encryption_enabled
from app.template_config import templates

router = APIRouter(prefix="/admin")


def _require_admin(request: Request, db: Session):
    """Like require_login, but also checks is_admin == 1."""
    user = require_login(request, db)
    if not user.is_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Geen toegang")
    return user


# ──────────────────────────────────────────────────────────────────────────────
# User management
# ──────────────────────────────────────────────────────────────────────────────

def _user_stats(db: Session, users: list) -> dict:
    """Return {user_id: {"tx_count": int, "account_count": int}} for all given users."""
    user_ids = [u.id for u in users]
    # Account counts
    acc_counts = {row[0]: row[1] for row in db.query(Account.user_id, func.count(Account.id))
                  .filter(Account.user_id.in_(user_ids)).group_by(Account.user_id).all()}
    # Transaction counts (via account join)
    tx_counts_raw = (
        db.query(Account.user_id, func.count(Transaction.id))
        .join(Transaction, Transaction.account_id == Account.id)
        .filter(Account.user_id.in_(user_ids))
        .group_by(Account.user_id)
        .all()
    )
    tx_counts = {row[0]: row[1] for row in tx_counts_raw}
    return {u.id: {"account_count": acc_counts.get(u.id, 0), "tx_count": tx_counts.get(u.id, 0)}
            for u in users}


@router.get("/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    users = db.query(User).order_by(User.created_at).all()
    stats = _user_stats(db, users)
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": admin, "users": users,
         "user_stats": stats, "encryption_enabled": encryption_enabled()},
    )


@router.post("/users/{user_id}/toggle-active")
def toggle_active(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != admin.id:
        # Super admin cannot be deactivated
        if SUPER_ADMIN_USERNAME and target.username == SUPER_ADMIN_USERNAME:
            return RedirectResponse("/admin/users", status_code=302)
        target.is_active = 0 if target.is_active else 1
        db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != admin.id:
        # Super admin cannot lose admin rights
        if SUPER_ADMIN_USERNAME and target.username == SUPER_ADMIN_USERNAME:
            return RedirectResponse("/admin/users", status_code=302)
        target.is_admin = 0 if target.is_admin else 1
        db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/email")
def admin_update_user_email(
    user_id: int,
    request: Request,
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    """Laat een admin het e-mailadres van een user (zichzelf of ander)
    wijzigen. Basis validatie via _clean_email in auth-module."""
    _require_admin(request, db)
    from app.routers.auth import _clean_email
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users", status_code=302)
    cleaned = _clean_email(email)
    if cleaned is None:
        return RedirectResponse("/admin/users?email_error=invalid", status_code=302)
    target.email = cleaned or None
    db.commit()
    return RedirectResponse("/admin/users?email_ok=1", status_code=302)


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != admin.id:
        # Super admin cannot be deleted
        if SUPER_ADMIN_USERNAME and target.username == SUPER_ADMIN_USERNAME:
            return RedirectResponse("/admin/users", status_code=302)
        db.delete(target)
        db.commit()
    return RedirectResponse("/admin/users", status_code=302)


# ──────────────────────────────────────────────────────────────────────────────
# Invite links
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/invite")
def create_invite(
    request: Request,
    invite_email: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, db)

    token = secrets.token_urlsafe(32)
    expires = datetime.datetime.utcnow() + datetime.timedelta(days=7)
    db.add(AuthToken(
        user_id=None,
        token=token,
        token_type="invite",
        expires_at=expires,
        email=invite_email.strip() or None,
    ))
    db.commit()

    if invite_email.strip():
        send_invite_email(invite_email.strip(), token, admin.username)

    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request, "user": admin, "users": users,
            "user_stats": _user_stats(db, users),
            "invite_link": f"/register?invite={token}",
            "encryption_enabled": encryption_enabled(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Encryption migration
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/encrypt-data")
def encrypt_data(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    count = encrypt_existing_transactions(db)
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request, "user": admin, "users": users,
            "user_stats": _user_stats(db, users),
            "encrypt_result": count,
            "encryption_enabled": encryption_enabled(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Demo-user seed (GJA-46) — idempotent aanmaken/resetten van een vaste
# demo-account zodat live demo's geen lege schermen tonen.
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/demo/seed")
def seed_demo(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    # Lokale import houdt de seed-module volledig optioneel bij CLI-start.
    from scripts.seed_demo_user import seed_demo_user

    result = seed_demo_user(db=db)
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request, "user": admin, "users": users,
            "user_stats": _user_stats(db, users),
            "demo_seed_result": result,
            "encryption_enabled": encryption_enabled(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Import batches — groepeer transacties per import-moment zodat een verkeerde
# import in één klik ongedaan gemaakt kan worden.
# ──────────────────────────────────────────────────────────────────────────────

def _list_import_batches(db: Session, limit: int = 200) -> list[dict]:
    """Groepeer transacties per account en created_at (afgerond op minuut)."""
    rows = (
        db.query(
            Transaction.account_id,
            Account.name.label("account_name"),
            Account.user_id,
            User.username.label("user_name"),
            func.date_trunc("minute", Transaction.created_at).label("batch"),
            func.count(Transaction.id).label("tx_count"),
            func.min(Transaction.date).label("first_date"),
            func.max(Transaction.date).label("last_date"),
            func.min(Transaction.created_at).label("created_from"),
            func.max(Transaction.created_at).label("created_to"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .join(User, User.id == Account.user_id)
        .group_by(
            Transaction.account_id,
            Account.name,
            Account.user_id,
            User.username,
            func.date_trunc("minute", Transaction.created_at),
        )
        .order_by(func.date_trunc("minute", Transaction.created_at).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "account_id": r.account_id,
            "account_name": r.account_name,
            "user_id": r.user_id,
            "user_name": r.user_name,
            "batch": r.batch,
            "tx_count": r.tx_count,
            "first_date": r.first_date,
            "last_date": r.last_date,
            "created_from": r.created_from,
            "created_to": r.created_to,
        }
        for r in rows
    ]


@router.get("/imports")
def admin_imports(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    batches = _list_import_batches(db)
    return templates.TemplateResponse(
        "admin/imports.html",
        {"request": request, "user": admin, "batches": batches},
    )


@router.post("/imports/delete")
def admin_imports_delete(
    request: Request,
    account_id: int = Form(...),
    created_from: str = Form(...),
    created_to: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    try:
        ts_from = datetime.datetime.fromisoformat(created_from)
        ts_to = datetime.datetime.fromisoformat(created_to)
    except ValueError:
        return RedirectResponse("/admin/imports", status_code=302)
    (
        db.query(Transaction)
        .filter(
            Transaction.account_id == account_id,
            Transaction.created_at >= ts_from,
            Transaction.created_at <= ts_to,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return RedirectResponse("/admin/imports", status_code=302)


# ──────────────────────────────────────────────────────────────────────────────
# Orphan transaction detector (GJA-39)
# ──────────────────────────────────────────────────────────────────────────────

def _iban_bank_hint(iban: str | None) -> str | None:
    """Raad de bank uit een IBAN (NL-focus): NLxxBUNQxxxx → 'bunq', ABNA → 'abn_amro',
    INGB → 'ing', RABO → 'rabo', etc. Return None als niet te achterhalen."""
    if not iban:
        return None
    clean = "".join(iban.split()).upper()
    if len(clean) < 8 or not clean.startswith("NL"):
        return None
    code = clean[4:8]
    return {
        "BUNQ": "bunq",
        "ABNA": "abn_amro",
        "INGB": "ing",
        "RABO": "rabo",
        "TRIO": "triodos",
        "KNAB": "knab",
        "SNSB": "sns",
        "ASNB": "asn",
        "RBRB": "regiobank",
    }.get(code)


_BANK_KEYWORDS_IN_TEXT = {
    "bunq": ["bunq"],
    "abn_amro": ["abn amro", "abnamro"],
    "ing": ["ing bank"],
    "rabo": ["rabobank"],
    "triodos": ["triodos"],
    "knab": ["knab bank"],
}


@router.get("/orphan-transactions")
def admin_orphan_transactions(request: Request, db: Session = Depends(get_db)):
    """Detecteer transacties die vermoedelijk op de verkeerde rekening staan.

    Twee signalen (OR):
      1. **IBAN-hint**: `counterparty_iban` hoort bij bank A maar de transactie
         staat op een rekening van bank B, terwijl de gebruiker óók een
         rekening bij bank A heeft. Sterk signaal van misroutering.
      2. **Tekst-hint**: de omschrijving/tegenpartij bevat een bank-naam
         (bv. "bunq Payday") die van een andere bank is dan de rekening
         waarop de transactie staat, en de gebruiker heeft óók een rekening
         bij die andere bank.

    Verdachte transacties worden per user aggregeerd — admin kan per rij
    doorklikken naar /transactions om te verplaatsen via de tx-actie-paneel
    "↪ Verplaats rekening"-knop (PR #92).
    """
    admin = _require_admin(request, db)

    # Alleen de eigen transacties van de admin voor nu (multi-user kan later
    # als het een issue wordt; vrijwel alle gebruikers zijn admin).
    accounts = db.query(Account).filter(Account.user_id == admin.id).all()
    accounts_by_bank: dict[str, list[Account]] = {}
    for acc in accounts:
        accounts_by_bank.setdefault(acc.bank, []).append(acc)
    user_banks = set(accounts_by_bank.keys())
    account_by_id = {a.id: a for a in accounts}

    # Laad alle transacties in één query (N-counts klein genoeg; we filteren
    # in Python vanwege encrypted counterparty/description velden).
    transactions = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == admin.id,
            Transaction.is_projected == 0,
        )
        .order_by(Transaction.date.desc())
        .all()
    )

    suspicious = []
    for tx in transactions:
        acc = account_by_id.get(tx.account_id)
        if acc is None:
            continue
        tx_bank = acc.bank

        reasons = []

        # Signaal 1: IBAN-hint
        cp_iban_bank = _iban_bank_hint(tx.counterparty_iban)
        if cp_iban_bank and cp_iban_bank != tx_bank and cp_iban_bank in user_banks:
            reasons.append(
                f"Tegenpartij-IBAN hoort bij {cp_iban_bank.upper()} "
                f"maar transactie staat op {tx_bank.upper()}"
            )

        # Signaal 2: tekst-hint in omschrijving of tegenpartij
        haystack = " ".join(filter(None, [
            (tx.description or "").lower(),
            (tx.counterparty or "").lower(),
        ]))
        if haystack:
            for bank_key, keywords in _BANK_KEYWORDS_IN_TEXT.items():
                if bank_key == tx_bank or bank_key not in user_banks:
                    continue
                if any(kw in haystack for kw in keywords):
                    reasons.append(
                        f"Omschrijving bevat '{bank_key}' "
                        f"maar transactie staat op {tx_bank.upper()}"
                    )
                    break  # één hit per tx voldoende

        if not reasons:
            continue

        # Suggereer de beste doel-rekening: eerst op IBAN-bank-hint, anders
        # pak de eerste account van de vermoedelijke bank.
        target_bank = cp_iban_bank
        if not target_bank:
            # Pak uit de tekst-hint
            for bank_key, keywords in _BANK_KEYWORDS_IN_TEXT.items():
                if bank_key != tx_bank and bank_key in user_banks:
                    if any(kw in haystack for kw in keywords):
                        target_bank = bank_key
                        break
        suggested = accounts_by_bank.get(target_bank, [None])[0] if target_bank else None

        suspicious.append({
            "tx": tx,
            "account": acc,
            "reasons": reasons,
            "suggested_account": suggested,
        })

    return templates.TemplateResponse(
        "admin/orphan_transactions.html",
        {
            "request": request,
            "user": admin,
            "suspicious": suspicious,
            "total_scanned": len(transactions),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler dashboard (LIN-42)
# ──────────────────────────────────────────────────────────────────────────────

def _scheduled_jobs_info():
    """Snapshot van APScheduler: ingeplande jobs + next-run + trigger-beschrijving.

    Draait defensief — een scheduler die niet is gestart retourneert gewoon [].
    """
    try:
        from app.scheduler import scheduler
        jobs = scheduler.get_jobs()
    except Exception:
        return []
    out = []
    for job in jobs:
        out.append({
            "id": job.id,
            "trigger": str(job.trigger),
            "next_run_time": getattr(job, "next_run_time", None),
            "name": getattr(job, "name", None) or job.id,
        })
    return out


@router.get("/scheduler")
def admin_scheduler(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    jobs = _scheduled_jobs_info()
    recent_runs = (
        db.query(SchedulerRunLog)
        .order_by(SchedulerRunLog.started_at.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse(
        "admin/scheduler.html",
        {
            "request": request,
            "user": admin,
            "jobs": jobs,
            "recent_runs": recent_runs,
        },
    )


_RUNNABLE_JOBS = {
    "weekly_digest": "app.scheduler._run_weekly_digests",
    "bank_sync": "app.scheduler._sync_all_bank_connections",
}


@router.post("/scheduler/run")
def admin_scheduler_run(
    request: Request,
    job_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Start een bekende job meteen. De `logged_job`-decorator zorgt voor een
    log-rij — ook bij een fout.
    """
    _require_admin(request, db)
    target = _RUNNABLE_JOBS.get(job_id)
    if not target:
        return RedirectResponse("/admin/scheduler?error=unknown_job", status_code=302)

    module_path, fn_name = target.rsplit(".", 1)
    import importlib
    try:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
        # Catch fouten zodat de UI niet breekt — de decorator bewaart de traceback
        # sowieso in de log-rij.
        try:
            fn()
        except Exception:
            pass
    except Exception:
        return RedirectResponse("/admin/scheduler?error=trigger_failed", status_code=302)

    return RedirectResponse("/admin/scheduler?flash=triggered", status_code=302)
