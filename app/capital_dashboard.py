"""Aggregatie-logica voor het kapitaal-dashboard (sparen + beleggen per persoon).

Bouwt een data-model dat door de `/portfolio/dashboard` route aan de template
wordt doorgegeven. Kern: per persoon (en als aggregaat "Samen") een huidige
waarde + 12-maanden projectie die spaar-forecast en beleggings-projectie
combineert op één tijdlijn.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Account,
    Person,
    PortfolioAsset,
    PortfolioHolding,
    SavingsLine,
    SavingsPlan,
)


MONTH_LABELS_NL = [
    "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]

PROJECTION_MONTHS_AHEAD = 12


def _plan_monthly_deltas(plan: SavingsPlan) -> list[Decimal]:
    """Netto maand-delta (inkomsten − uitgaven) per maand 1..12 voor één plan.

    Lege/None-entries tellen als 0. Gebaseerd op forecast-bedragen — we doen
    bewust geen transactie-lookup hier: het dashboard toont *plan*-gebaseerde
    projectie, niet een achteraf-analyse.
    """
    deltas = [Decimal("0")] * 13  # index 0 unused; 1..12 zijn de maanden
    for line in plan.lines:
        is_income = bool(line.is_income)
        for entry in line.entries:
            if entry.amount is None:
                continue
            amount = abs(entry.amount)
            if is_income:
                deltas[entry.month] += amount
            else:
                deltas[entry.month] -= amount
    return deltas


def _plan_december_balance(plan: SavingsPlan) -> Decimal:
    """Eindsaldo van een plan (december) op basis van forecast-deltas."""
    balance = plan.starting_balance or Decimal("0")
    for d in _plan_monthly_deltas(plan)[1:]:
        balance += d
    return balance


def _plan_effective_start(db: Session, plan: SavingsPlan) -> Decimal:
    """Effectief startsaldo: propageer eindsaldo van bronplan als gekoppeld."""
    if plan.source_plan_id:
        src = (
            db.query(SavingsPlan)
            .options(joinedload(SavingsPlan.lines).joinedload(SavingsLine.entries))
            .filter(SavingsPlan.id == plan.source_plan_id)
            .first()
        )
        if src:
            return _plan_december_balance(src)
    return plan.starting_balance or Decimal("0")


def _fetch_plans(db: Session, user_id: int, years: set[int]) -> dict[tuple[int, int], SavingsPlan]:
    if not years:
        return {}
    plans = (
        db.query(SavingsPlan)
        .options(joinedload(SavingsPlan.lines).joinedload(SavingsLine.entries))
        .filter(SavingsPlan.user_id == user_id, SavingsPlan.year.in_(years))
        .all()
    )
    return {(p.account_id, p.year): p for p in plans}


def _build_labels(today: datetime.date, months_ahead: int) -> list[str]:
    """Label-strings: huidige maand + `months_ahead` toekomstige maanden.

    Over de jaargrens komt een jaar-suffix ('25/'26), zodat de x-as leesbaar
    blijft bij cross-year projecties.
    """
    labels = []
    for step in range(months_ahead + 1):
        month_idx = today.month + step
        year_offset = (month_idx - 1) // 12
        m = ((month_idx - 1) % 12) + 1
        base = MONTH_LABELS_NL[m - 1]
        if year_offset == 0:
            labels.append(base)
        else:
            suffix = str(today.year + year_offset)[-2:]
            labels.append(f"{base} '{suffix}")
    return labels


def _savings_timeline_for_account(
    plans_map: dict[tuple[int, int], SavingsPlan],
    plan_starts: dict[tuple[int, int], Decimal],
    plan_deltas: dict[tuple[int, int], list[Decimal]],
    account_id: int,
    today: datetime.date,
    months_ahead: int,
) -> list[Decimal]:
    """Bouwt een lijst van saldo's voor account_id: [today, +1m, +2m, ... +Nm].

    - Voor de huidige maand: startsaldo + deltas jan..current_month.
    - Voor vooruit: stap-voor-stap de delta van die kalendermaand optellen.
    - Wrap-around naar volgend jaar werkt als er een plan voor dat jaar bestaat;
      anders blijft saldo vlak (geen extra delta).
    """
    current_year = today.year
    current_month = today.month

    cy_key = (account_id, current_year)
    cy_plan = plans_map.get(cy_key)

    if cy_plan:
        balance = plan_starts[cy_key]
        for m in range(1, current_month + 1):
            balance += plan_deltas[cy_key][m]
    else:
        balance = Decimal("0")
    timeline: list[Decimal] = [balance]

    for step in range(1, months_ahead + 1):
        month_idx = current_month + step
        year_offset = (month_idx - 1) // 12
        m = ((month_idx - 1) % 12) + 1
        year = current_year + year_offset
        key = (account_id, year)
        if key in plan_deltas:
            balance += plan_deltas[key][m]
        timeline.append(balance)

    return timeline


def _portfolio_timeline_for_holding(
    qty: Decimal,
    price: Decimal,
    contribution: Decimal,
    monthly_growth_pct: Decimal,
    months_ahead: int,
) -> list[Decimal]:
    """Tijdlijn van huidige waarde + `months_ahead` stappen van simulatie.

    Formule per stap: value = (value + contribution) * (1 + growth/100).
    Dit is hetzelfde patroon als /portfolio gebruikt voor de projectie.
    """
    growth_factor = Decimal("1") + (monthly_growth_pct or Decimal("0")) / Decimal("100")
    value = qty * price
    timeline = [value]
    for _ in range(months_ahead):
        value = (value + contribution) * growth_factor
        timeline.append(value)
    return timeline


def build_capital_dashboard(
    db: Session,
    user_id: int,
    today: datetime.date | None = None,
    months_ahead: int = PROJECTION_MONTHS_AHEAD,
) -> dict:
    """Bouw het data-model voor het kapitaal-dashboard.

    Return-structuur:
        {
            "persons": [Person],
            "labels": [str],                 # lengte = months_ahead + 1
            "series_per_person": {pid: [float]},   # zelfde lengte
            "series_samen": [float],
            "current_totals": {pid: {savings, portfolio_gross, portfolio_net,
                                      total_gross, total_net}},
            "samen_totals": {savings, portfolio_gross, portfolio_net,
                              total_gross, total_net},
            "savings_breakdown": [...],
            "portfolio_breakdown": [...],
        }
    """
    if today is None:
        today = datetime.date.today()

    persons = (
        db.query(Person)
        .filter(Person.user_id == user_id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    person_ids = [p.id for p in persons]
    person_name_by_id = {p.id: p.name for p in persons}

    # ── Sparen ───────────────────────────────────────────────────────
    accounts = (
        db.query(Account)
        .options(joinedload(Account.owners))
        .filter(Account.user_id == user_id)
        .all()
    )

    needed_years = {today.year}
    if today.month + months_ahead > 12:
        needed_years.add(today.year + 1)

    plans_map = _fetch_plans(db, user_id, needed_years)
    plan_starts: dict[tuple[int, int], Decimal] = {}
    plan_deltas: dict[tuple[int, int], list[Decimal]] = {}
    for key, plan in plans_map.items():
        plan_starts[key] = _plan_effective_start(db, plan)
        plan_deltas[key] = _plan_monthly_deltas(plan)

    savings_timeline_by_person: dict[int, list[Decimal]] = {
        pid: [Decimal("0")] * (months_ahead + 1) for pid in person_ids
    }
    savings_breakdown = []

    for acc in accounts:
        owners = list(acc.owners)
        if not owners:
            continue
        share = Decimal("1") / Decimal(len(owners))

        timeline = _savings_timeline_for_account(
            plans_map, plan_starts, plan_deltas, acc.id, today, months_ahead,
        )

        owner_entries = []
        for p in owners:
            person_timeline = [t * share for t in timeline]
            target = savings_timeline_by_person.setdefault(
                p.id, [Decimal("0")] * (months_ahead + 1),
            )
            for i, v in enumerate(person_timeline):
                target[i] += v
            owner_entries.append({
                "person_id": p.id,
                "person_name": p.name,
                "share": float(share),
                "current": person_timeline[0],
                "projected": person_timeline[-1],
            })

        savings_breakdown.append({
            "account_id": acc.id,
            "name": acc.name,
            "has_plan": (acc.id, today.year) in plans_map,
            "current_total": timeline[0],
            "projected_total": timeline[-1],
            "owners": owner_entries,
        })

    # ── Beleggen ─────────────────────────────────────────────────────
    assets = (
        db.query(PortfolioAsset)
        .filter(PortfolioAsset.user_id == user_id)
        .order_by(PortfolioAsset.asset_class, PortfolioAsset.name)
        .all()
    )
    holdings = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user_id)
        .all()
    )
    holdings_by_key = {(h.asset_id, h.person_id): h for h in holdings}

    portfolio_timeline_by_person: dict[int, list[Decimal]] = {
        pid: [Decimal("0")] * (months_ahead + 1) for pid in person_ids
    }
    portfolio_net_current_by_person: dict[int, Decimal] = {
        pid: Decimal("0") for pid in person_ids
    }
    portfolio_breakdown = []

    for asset in assets:
        price = asset.current_price_eur or Decimal("0")
        growth = asset.monthly_growth_pct or Decimal("0")
        fee_pct = asset.cashout_fee_pct or Decimal("0")
        fee_fixed = asset.cashout_fee_fixed_eur or Decimal("0")

        asset_total_per_step = [Decimal("0")] * (months_ahead + 1)
        owner_entries = []

        for p in persons:
            h = holdings_by_key.get((asset.id, p.id))
            if h is None:
                continue
            qty = h.quantity or Decimal("0")
            contribution = h.monthly_contribution_eur or Decimal("0")
            if qty == 0 and contribution == 0:
                continue

            timeline = _portfolio_timeline_for_holding(
                qty, price, contribution, growth, months_ahead,
            )
            target = portfolio_timeline_by_person.setdefault(
                p.id, [Decimal("0")] * (months_ahead + 1),
            )
            for i, v in enumerate(timeline):
                target[i] += v
                asset_total_per_step[i] += v

            owner_entries.append({
                "person_id": p.id,
                "person_name": p.name,
                "quantity": qty,
                "contribution": contribution,
                "value": timeline[0],
                "projected": timeline[-1],
            })

        asset_gross_now = asset_total_per_step[0]
        if asset_gross_now > 0:
            net_now = asset_gross_now - (asset_gross_now * fee_pct / Decimal("100")) - fee_fixed
            if net_now < 0:
                net_now = Decimal("0")
        else:
            net_now = Decimal("0")

        for entry in owner_entries:
            if asset_gross_now > 0:
                share = entry["value"] / asset_gross_now
                entry_net = net_now * share
            else:
                entry_net = Decimal("0")
            entry["net_value"] = entry_net
            portfolio_net_current_by_person[entry["person_id"]] = (
                portfolio_net_current_by_person.get(entry["person_id"], Decimal("0")) + entry_net
            )

        if owner_entries:
            portfolio_breakdown.append({
                "asset_id": asset.id,
                "name": asset.name,
                "asset_class": asset.asset_class,
                "unit": asset.unit,
                "owners": owner_entries,
                "current_gross": asset_gross_now,
                "current_net": net_now,
                "projected_gross": asset_total_per_step[-1],
            })

    # ── Combineer tot een tijdserie per persoon + Samen ──────────────
    series_per_person: dict[int, list[float]] = {}
    series_samen_decimal = [Decimal("0")] * (months_ahead + 1)

    for p in persons:
        sav = savings_timeline_by_person.get(p.id, [Decimal("0")] * (months_ahead + 1))
        pf = portfolio_timeline_by_person.get(p.id, [Decimal("0")] * (months_ahead + 1))
        combined = [sav[i] + pf[i] for i in range(months_ahead + 1)]
        series_per_person[p.id] = [float(round(v, 2)) for v in combined]
        for i, v in enumerate(combined):
            series_samen_decimal[i] += v

    series_samen = [float(round(v, 2)) for v in series_samen_decimal]

    # ── Current totals (per persoon + Samen) ─────────────────────────
    current_totals = {}
    samen_savings = Decimal("0")
    samen_gross = Decimal("0")
    samen_net = Decimal("0")
    for p in persons:
        s = savings_timeline_by_person.get(p.id, [Decimal("0")])[0]
        gr = portfolio_timeline_by_person.get(p.id, [Decimal("0")])[0]
        ne = portfolio_net_current_by_person.get(p.id, Decimal("0"))
        current_totals[p.id] = {
            "savings": s,
            "portfolio_gross": gr,
            "portfolio_net": ne,
            "total_gross": s + gr,
            "total_net": s + ne,
        }
        samen_savings += s
        samen_gross += gr
        samen_net += ne

    samen_totals = {
        "savings": samen_savings,
        "portfolio_gross": samen_gross,
        "portfolio_net": samen_net,
        "total_gross": samen_savings + samen_gross,
        "total_net": samen_savings + samen_net,
    }

    return {
        "persons": persons,
        "person_name_by_id": person_name_by_id,
        "labels": _build_labels(today, months_ahead),
        "series_per_person": series_per_person,
        "series_samen": series_samen,
        "current_totals": current_totals,
        "samen_totals": samen_totals,
        "savings_breakdown": savings_breakdown,
        "portfolio_breakdown": portfolio_breakdown,
        "months_ahead": months_ahead,
    }
