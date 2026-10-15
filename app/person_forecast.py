"""Verwachting per persoon: betaalrekeningen (terugkerende posten) en vermogen.

Rekenkern zonder HTTP of templates (ACT-53). Het saldo op betaalrekeningen loopt
vanaf het laatst bekende saldo door met de terugkerende posten die in de
betreffende maand actief zijn (dezelfde regel als de projecties in de app).
Gedeelde rekeningen worden gelijk over de eigenaren verdeeld, zoals in de
vermogensprognose (ACT-28). Het vermogen komt uit ``build_wealth_forecast``.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app import clock
from app.bank_sync import normalize_iban
from app.models import Account, Person, RecurringTransaction, Transaction
from app.recurring_schedule import is_active_in_month
from app.wealth_forecast import ZERO, build_wealth_forecast

MAX_YEARS = 20


def add_months(day: datetime.date, months: int) -> datetime.date:
    """Eerste van de maand, ``months`` maanden na de maand van ``day``."""
    index = day.year * 12 + (day.month - 1) + months
    return datetime.date(index // 12, index % 12 + 1, 1)


def birthday_at_age(birthdate: datetime.date, age: int) -> datetime.date:
    try:
        return birthdate.replace(year=birthdate.year + age)
    except ValueError:  # 29 februari
        return datetime.date(birthdate.year + age, 3, 1)


def months_until(target: datetime.date, today: datetime.date) -> int:
    """Hele maanden van de huidige maand tot de maand van ``target`` (min. 0)."""
    return max(0, (target.year - today.year) * 12 + target.month - today.month)


def _latest_balance(db: Session, account_id: int) -> Decimal | None:
    row = (
        db.query(Transaction.balance_after)
        .filter(
            Transaction.account_id == account_id,
            Transaction.is_projected == 0,
            Transaction.balance_after.isnot(None),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .first()
    )
    return row[0] if row else None


def _savings_targets(accounts: list[Account]) -> tuple[set[str], list[str]]:
    ibans = {normalize_iban(a.iban) for a in accounts if a.kind == "savings" and a.iban}
    names = [a.name.lower() for a in accounts if a.kind == "savings" and a.name]
    return {i for i in ibans if i}, names


def is_savings_transfer(item: RecurringTransaction, savings_ibans: set[str], savings_names: list[str]) -> bool:
    """Een terugkerende post richting een eigen spaarrekening (op IBAN of naam)."""
    haystack = " ".join(filter(None, [item.counterparty, item.name, item.description_match])).lower()
    compact = "".join(haystack.split()).upper()
    if any(iban in compact for iban in savings_ibans):
        return True
    return any(name and name in haystack for name in savings_names)


def _wealth_series(db: Session, user_id: int, person_id: int, first: datetime.date, last: datetime.date,
                   today: datetime.date) -> dict[datetime.date, dict[str, Decimal]]:
    """Vermogen per maandbegin voor één persoon tussen ``first`` en ``last``."""
    series: dict[datetime.date, dict[str, Decimal]] = {}
    for year in range(first.year, last.year + 1):
        data = build_wealth_forecast(db, user_id, year, today=today)
        values = data["per_person"].get(person_id)
        if not values:
            continue
        for month, day in enumerate(data["months"], start=1):
            if first <= day <= last:
                series[day] = values[month]
    return series


def build_person_forecast(db: Session, user_id: int, person_id: int, months: int,
                          today: datetime.date | None = None) -> dict | None:
    """Verwachting voor ``months`` maanden vooruit (vanaf de volgende maand)."""
    today = today or clock.today_nl()
    person = db.query(Person).filter(Person.id == person_id, Person.user_id == user_id).first()
    if not person:
        return None
    months = max(1, min(months, MAX_YEARS * 12))

    all_accounts = (
        db.query(Account).options(joinedload(Account.owners)).filter(Account.user_id == user_id).all()
    )
    mine = [a for a in all_accounts if any(o.id == person.id for o in a.owners)]
    payment = [a for a in mine if a.kind != "savings"]
    shares = {a.id: Decimal(1) / Decimal(len(a.owners)) for a in payment}
    savings_ibans, savings_names = _savings_targets(all_accounts)

    account_rows = []
    balance_known = True
    start_balance = ZERO
    for account in payment:
        balance = _latest_balance(db, account.id)
        if balance is None:
            balance_known = False
        share = shares[account.id]
        account_rows.append({"id": account.id, "name": account.name, "share": share,
                             "balance": balance, "owned_balance": (balance or ZERO) * share})
        start_balance += (balance or ZERO) * share

    items = (
        db.query(RecurringTransaction)
        .filter(RecurringTransaction.user_id == user_id, RecurringTransaction.is_active == 1,
                RecurringTransaction.account_id.in_([a.id for a in payment] or [-1]))
        .all()
    )

    first = add_months(today, 1)
    last = add_months(today, months)
    wealth = _wealth_series(db, user_id, person.id, first, last, today)

    rows = []
    balance = start_balance
    min_balance, min_month = None, None
    for offset in range(1, months + 1):
        day = add_months(today, offset)
        income = expenses = to_savings = ZERO
        for item in items:
            if not is_active_in_month(item, day.year, day.month):
                continue
            amount = Decimal(item.amount_expected) * shares[item.account_id]
            if amount >= 0:
                income += amount
            elif is_savings_transfer(item, savings_ibans, savings_names):
                to_savings += amount
            else:
                expenses += amount
        net = income + expenses + to_savings
        balance += net
        if min_balance is None or balance < min_balance:
            min_balance, min_month = balance, day
        rows.append({"month": day, "income": income, "expenses": expenses, "to_savings": to_savings,
                     "net": net, "balance": balance,
                     "wealth": wealth.get(day, {"portfolio": ZERO, "savings": ZERO, "total": ZERO})})

    return {
        "person": person, "months": months, "rows": rows, "accounts": account_rows,
        "start_balance": start_balance, "balance_known": balance_known,
        "min_balance": min_balance, "min_month": min_month,
        "milestone": build_milestone(db, user_id, person, 18, today),
    }


def build_milestone(db: Session, user_id: int, person: Person, age: int,
                    today: datetime.date) -> dict | None:
    """Verwacht vermogen op de ``age``e verjaardag (alleen voor personen met geboortedatum)."""
    if not person.birthdate:
        return None
    birthday = birthday_at_age(person.birthdate, age)
    if birthday < today:
        return {"age": age, "date": birthday, "reached": True, "months_left": 0, "wealth": None}
    target = datetime.date(birthday.year, birthday.month, 1)
    if (target.year - today.year) > MAX_YEARS:
        return {"age": age, "date": birthday, "reached": False,
                "months_left": months_until(target, today), "wealth": None}
    series = _wealth_series(db, user_id, person.id, add_months(today, 0), target, today)
    wealth = series.get(target)
    return {"age": age, "date": birthday, "reached": False,
            "months_left": months_until(target, today), "wealth": wealth}


__all__ = ["build_person_forecast", "build_milestone", "months_until"]
