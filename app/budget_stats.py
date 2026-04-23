"""Gedeelde helpers voor budget-statistieken.

Gebruikt door zowel de budget-overzichtspagina als de hypotheek-scenario
detail-pagina, zodat beide dezelfde definitie van "gemiddelde uitgave"
hanteren.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction


def _previous_months(ref_year: int, ref_month: int, count: int) -> list[tuple[int, int]]:
    """Returnt een lijst met (year, month) voor de ``count`` maanden
    voorafgaand aan (ref_year, ref_month). Exclusief de referentiemaand zelf.

    Voorbeeld (ref=2026-04, count=3): [(2026,1), (2026,2), (2026,3)].
    """
    out: list[tuple[int, int]] = []
    y, m = ref_year, ref_month
    for _ in range(count):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        out.append((y, m))
    return list(reversed(out))


def category_spending_average(
    db: Session,
    *,
    user_id: int,
    ref_year: int,
    ref_month: int,
    months: int = 3,
    account_id: int | None = None,
) -> dict[int, Decimal]:
    """Geeft per categorie het gemiddelde uitgegeven bedrag over de laatste
    ``months`` volle maanden vóór (ref_year, ref_month).

    * Alleen expense-transacties (``amount < 0``), geëxcludeerde + interne
      transfers gefilterd.
    * Categorieën met ``exclude_from_budget = 1`` vallen weg.
    * Retourneert absolute waarden (positief).
    * Ontbrekende categorieën komen simpelweg niet in de dict; caller
      interpreteert dan als € 0 gemiddeld.
    """
    if months <= 0:
        return {}

    ym_pairs = _previous_months(ref_year, ref_month, months)

    # Bouw een OR-filter op (year, month) combinaties — simpelweg één ORM-
    # query met in_() op een samengestelde sleutel gaat niet, dus we
    # filteren op year/month met meerdere OR's via `or_`.
    from sqlalchemy import or_

    conditions = [
        (func.extract("year", Transaction.date) == y)
        & (func.extract("month", Transaction.date) == m)
        for (y, m) in ym_pairs
    ]
    if not conditions:
        return {}

    q = (
        db.query(
            Category.id.label("cat_id"),
            func.sum(Transaction.amount).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == user_id,
            or_(*conditions),
            Transaction.amount < 0,
            Transaction.is_excluded == 0,
            Transaction.transfer_id.is_(None),
            Category.exclude_from_budget == 0,
        )
    )
    if account_id:
        q = q.filter(Transaction.account_id == account_id)

    rows = q.group_by(Category.id).all()
    divisor = Decimal(str(months))
    return {
        row.cat_id: (abs(Decimal(str(row.total))) / divisor).quantize(
            Decimal("0.01")
        )
        for row in rows
    }
