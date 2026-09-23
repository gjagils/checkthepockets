"""Yearly wealth forecast calculations, grouped by person.

The forecast is deliberately independent from HTTP and templates.  It models
the value at the *start* of every month, so a saved plan and the screen can use
the exact same figures.  Historic portfolio months prefer stored price
snapshots; future months grow from the last known price and contribution.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.capital_dashboard import _plan_effective_start, _plan_monthly_deltas
from app.models import (
    Account,
    Person,
    PortfolioAsset,
    PortfolioHolding,
    PortfolioPriceSnapshot,
    SavingsLine,
    SavingsPlan,
    Transaction,
    WealthAdjustment,
)


SELL_FACTOR = Decimal("0.982")
ZERO = Decimal("0")


def _month_start(year: int, month: int) -> datetime.date:
    return datetime.date(year, month, 1)


def _latest_balance_before(
    db: Session, account_id: int, before: datetime.date,
) -> Decimal | None:
    """Return the latest imported balance strictly before a month start."""
    row = (
        db.query(Transaction.balance_after)
        .filter(
            Transaction.account_id == account_id,
            Transaction.date < before,
            Transaction.balance_after.isnot(None),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .first()
    )
    return row[0] if row else None


def _plan_balance_at_start(
    db: Session, plan: SavingsPlan, month: int,
) -> Decimal:
    """Plan balance at the start of ``month`` (so month 1 is its start)."""
    balance = _plan_effective_start(db, plan)
    deltas = _plan_monthly_deltas(plan)
    for prior_month in range(1, month):
        balance += deltas[prior_month]
    return balance


def _asset_prices_by_month(
    db: Session, assets: list[PortfolioAsset], year: int,
) -> dict[tuple[int, int], Decimal]:
    snapshots = (
        db.query(PortfolioPriceSnapshot)
        .filter(
            PortfolioPriceSnapshot.asset_id.in_([asset.id for asset in assets] or [-1]),
            PortfolioPriceSnapshot.year == year,
        )
        .all()
    )
    return {(row.asset_id, row.month): row.price_eur for row in snapshots}


def build_wealth_forecast(
    db: Session,
    user_id: int,
    year: int,
    today: datetime.date | None = None,
) -> dict:
    """Calculate wealth at the start of January through December.

    Values are net sale values.  Each portfolio asset is valued per person as
    ``quantity × price × 0.982``.  Historical months use a saved snapshot when
    present.  From the current month onwards, the last known price grows every
    month and the holding's euro contribution is added before that growth.
    Savings use imported balances for past months when they exist, otherwise
    the savings-plan balance; shared accounts are split equally among owners.
    """
    today = today or datetime.date.today()
    persons = (
        db.query(Person).filter(Person.user_id == user_id)
        .order_by(Person.sort_order, Person.name).all()
    )
    assets = (
        db.query(PortfolioAsset).filter(PortfolioAsset.user_id == user_id)
        .order_by(PortfolioAsset.name).all()
    )
    holdings = (
        db.query(PortfolioHolding).filter(PortfolioHolding.user_id == user_id).all()
    )
    accounts = (
        db.query(Account).options(joinedload(Account.owners))
        .filter(Account.user_id == user_id).all()
    )
    plans = (
        db.query(SavingsPlan)
        .options(joinedload(SavingsPlan.lines).joinedload(SavingsLine.entries))
        .filter(SavingsPlan.user_id == user_id, SavingsPlan.year == year).all()
    )
    plans_by_account = {plan.account_id: plan for plan in plans}
    assets_by_id = {asset.id: asset for asset in assets}
    prices = _asset_prices_by_month(db, assets, year)
    adjustments = {
        (row.asset_id, row.person_id, row.month): row.amount
        for row in db.query(WealthAdjustment).filter(
            WealthAdjustment.user_id == user_id, WealthAdjustment.year == year,
        ).all()
    }

    per_person = {
        person.id: {month: {"portfolio": ZERO, "savings": ZERO, "total": ZERO}
                    for month in range(1, 13)}
        for person in persons
    }
    asset_values = defaultdict(lambda: defaultdict(lambda: ZERO))

    # Portfolio assets are always personal holdings.  We use a saved snapshot
    # for a historic month; missing snapshots use the current price.  Future
    # values continue from the preceding value, matching the spreadsheet rule
    # `(previous + monthly contribution) × growth`.
    holdings_by_asset: dict[int, list[PortfolioHolding]] = defaultdict(list)
    for holding in holdings:
        holdings_by_asset[holding.asset_id].append(holding)

    for asset in assets:
        growth = Decimal("1") + (asset.monthly_growth_pct or ZERO) / Decimal("100")
        current_price = asset.current_price_eur or ZERO
        previous_values: dict[int, Decimal] = {}
        for month in range(1, 13):
            historic = (year, month) <= (today.year, today.month)
            snapshot_price = prices.get((asset.id, month))
            for holding in holdings_by_asset.get(asset.id, []):
                person_id = holding.person_id
                quantity = holding.quantity or ZERO
                contribution = holding.monthly_contribution_eur or ZERO
                if historic:
                    price = snapshot_price if snapshot_price is not None else current_price
                    value = quantity * price * SELL_FACTOR + adjustments.get((asset.id, person_id, month), ZERO)
                elif person_id in previous_values:
                    value = (previous_values[person_id] + contribution + adjustments.get((asset.id, person_id, month), ZERO)) * growth
                else:
                    value = quantity * current_price * SELL_FACTOR + adjustments.get((asset.id, person_id, month), ZERO)
                previous_values[person_id] = value
                asset_values[person_id][month] += value

    for person_id, months in asset_values.items():
        if person_id not in per_person:
            continue
        for month, value in months.items():
            per_person[person_id][month]["portfolio"] += value

    # A savings account belongs to one or more people.  Imported balances are
    # actual history; the savings plan is the forecast and fallback.
    for account in accounts:
        if not account.owners:
            continue
        plan = plans_by_account.get(account.id)
        share = Decimal("1") / Decimal(len(account.owners))
        for month in range(1, 13):
            start = _month_start(year, month)
            historic = start <= today
            actual = _latest_balance_before(db, account.id, start) if historic else None
            if actual is not None:
                balance = actual
            elif plan is not None:
                balance = _plan_balance_at_start(db, plan, month)
            else:
                balance = ZERO
            for owner in account.owners:
                if owner.id in per_person:
                    per_person[owner.id][month]["savings"] += balance * share

    for person_months in per_person.values():
        for values in person_months.values():
            values["total"] = values["portfolio"] + values["savings"]

    together = {
        month: {
            key: sum((per_person[person.id][month][key] for person in persons), ZERO)
            for key in ("portfolio", "savings", "total")
        }
        for month in range(1, 13)
    }
    return {
        "year": year,
        "months": [_month_start(year, month) for month in range(1, 13)],
        "persons": persons,
        "per_person": per_person,
        "together": together,
    }
