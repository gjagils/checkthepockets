import datetime
import secrets

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.database import get_db
from app.models import User, AuthToken, Account, Transaction
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
