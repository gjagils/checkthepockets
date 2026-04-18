"""Hypotheek-rekenmodule — alleen toegankelijk voor admins.

Fundering (GJA-25): overzicht van scenarios. Vervolg-issues voegen beheer toe
voor huishoud-instellingen, rente-tabel en scenario-CRUD.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import MortgageScenario
from app.template_config import templates

router = APIRouter(prefix="/hypotheek")


def _require_admin(request: Request, db: Session):
    """Admin-gated: non-admins krijgen 404 (bestaan van feature niet onthullen)."""
    user = require_login(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    return user


@router.get("")
def mortgage_index(request: Request, db: Session = Depends(get_db)):
    user = _require_admin(request, db)
    scenarios = (
        db.query(MortgageScenario)
        .filter(MortgageScenario.user_id == user.id, MortgageScenario.is_archived == 0)
        .order_by(MortgageScenario.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "mortgage/index.html",
        {"request": request, "user": user, "scenarios": scenarios},
    )
