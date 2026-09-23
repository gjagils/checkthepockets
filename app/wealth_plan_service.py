"""Persist and retrieve immutable yearly wealth-plan baselines."""
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models import User, WealthPlan, WealthPlanEntry
from app.wealth_forecast import build_wealth_forecast


class WealthPlanConfirmationRequired(ValueError):
    """Raised when a caller would overwrite an existing yearly plan."""


def capture_wealth_plan(
    db: Session,
    user_id: int,
    year: int,
    *,
    today: datetime.date | None = None,
    automatic: bool = False,
    replace: bool = False,
) -> WealthPlan:
    """Freeze the current forecast for ``year``.

    A year can only have one baseline.  A manual replacement requires
    ``replace=True``; callers should only pass it after an explicit UI
    confirmation.  The captured entries are values, never live references, so
    later holding, price or savings-plan edits cannot move the baseline.
    """
    plan = (
        db.query(WealthPlan)
        .options(joinedload(WealthPlan.entries))
        .filter(WealthPlan.user_id == user_id, WealthPlan.year == year)
        .first()
    )
    if plan is not None and not replace:
        if automatic:
            return plan
        raise WealthPlanConfirmationRequired("Plan voor dit jaar bestaat al")
    if plan is None:
        plan = WealthPlan(user_id=user_id, year=year, captured_automatically=int(automatic))
        db.add(plan)
        db.flush()
    else:
        plan.entries.clear()
        plan.captured_at = datetime.datetime.utcnow()
        plan.captured_automatically = int(automatic)
        db.flush()

    forecast = build_wealth_forecast(db, user_id, year, today=today)
    for person in forecast["persons"]:
        for month in range(1, 13):
            value = forecast["per_person"][person.id][month]
            db.add(WealthPlanEntry(
                plan_id=plan.id,
                person_id=person.id,
                month=month,
                portfolio_amount=Decimal(value["portfolio"]).quantize(Decimal("0.01")),
                savings_amount=Decimal(value["savings"]).quantize(Decimal("0.01")),
                total_amount=Decimal(value["total"]).quantize(Decimal("0.01")),
            ))
    db.flush()
    return plan


def get_wealth_plan_entries(db: Session, user_id: int, year: int) -> dict[tuple[int, int], WealthPlanEntry]:
    """Return a user's frozen values by ``(person_id, month)``."""
    rows = (
        db.query(WealthPlanEntry)
        .join(WealthPlan)
        .filter(WealthPlan.user_id == user_id, WealthPlan.year == year)
        .all()
    )
    return {(row.person_id, row.month): row for row in rows}


def capture_january_wealth_plans(db: Session, today: datetime.date | None = None) -> int:
    """Create missing baselines on 1 January; safe to call more than once."""
    today = today or datetime.date.today()
    if (today.month, today.day) != (1, 1):
        return 0
    captured = 0
    for user_id, in db.query(User.id).all():
        existing = db.query(WealthPlan.id).filter(
            WealthPlan.user_id == user_id, WealthPlan.year == today.year,
        ).first()
        if existing is None:
            capture_wealth_plan(db, user_id, today.year, today=today, automatic=True)
            captured += 1
    db.commit()
    return captured
