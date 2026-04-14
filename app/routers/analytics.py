import csv
import datetime
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import case, func, or_, and_

from app.database import get_db
from app.models import Account, Transaction, Category
from app.auth import require_login
from app.template_config import templates

router = APIRouter()

MONTH_NAMES_NL = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]


@router.get("/analytics")
def analytics(
    request: Request,
    year: int = Query(0),
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Base filter
    tx_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.transfer_id.is_(None),
    ]
    if account_id:
        tx_filter.append(Transaction.account_id == account_id)

    # Monthly income vs expenses trend (exclude_from_totals categories excluded)
    monthly_trend = (
        db.query(
            func.extract("month", Transaction.date).label("month"),
            func.sum(
                case(
                    (Transaction.amount > 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("income"),
            func.sum(
                case(
                    (Transaction.amount < 0, Transaction.amount),
                    else_=Decimal("0"),
                )
            ).label("expenses"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*tx_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .group_by(func.extract("month", Transaction.date))
        .order_by(func.extract("month", Transaction.date))
        .all()
    )

    trend_data = {}
    for row in monthly_trend:
        m = int(row.month)
        inc = row.income or Decimal("0")
        exp = row.expenses or Decimal("0")
        trend_data[m] = {
            "income": inc,
            "expenses": exp,
            "balance": inc + exp,
        }

    # Category spending per month (top 10 categories)
    cat_monthly = (
        db.query(
            Category.id,
            Category.name,
            func.extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*tx_filter, Transaction.amount < 0, Category.exclude_from_totals == 0)
        .group_by(Category.id, Category.name, func.extract("month", Transaction.date))
        .all()
    )

    # Aggregate by category
    cat_totals = {}
    cat_by_month = {}
    for row in cat_monthly:
        cid = row.id
        cname = row.name
        m = int(row.month)
        total = abs(row.total)

        if cid not in cat_totals:
            cat_totals[cid] = {"name": cname, "total": Decimal("0")}
            cat_by_month[cid] = {}
        cat_totals[cid]["total"] += total
        cat_by_month[cid][m] = total

    # Sort by total spending and take top 10
    top_cat_ids = sorted(cat_totals, key=lambda x: cat_totals[x]["total"], reverse=True)[:10]

    categories_trend = []
    for cid in top_cat_ids:
        monthly = {}
        for m in range(1, 13):
            monthly[m] = cat_by_month.get(cid, {}).get(m, Decimal("0"))
        categories_trend.append({
            "name": cat_totals[cid]["name"],
            "total": cat_totals[cid]["total"],
            "monthly": monthly,
        })

    # Find max monthly spend for bar scaling
    max_cat_monthly = Decimal("0")
    for cat in categories_trend:
        for m in range(1, 13):
            if cat["monthly"][m] > max_cat_monthly:
                max_cat_monthly = cat["monthly"][m]

    # Years for selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    return templates.TemplateResponse(
        "analytics/index.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "years": years,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "trend_data": trend_data,
            "categories_trend": categories_trend,
            "max_cat_monthly": max_cat_monthly,
            "months": MONTH_NAMES_NL,
        },
    )


@router.get("/analytics/stats")
def analytics_stats(
    request: Request,
    year: int = Query(0),
    month: int = Query(0),
    account_id: int = Query(0),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    today = datetime.date.today()
    current_year = year if year else today.year
    current_month = month  # 0 = full year

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id)
        .order_by(Account.name)
        .all()
    )

    # Base filter
    base_filter = [
        Account.user_id == user.id,
        func.extract("year", Transaction.date) == current_year,
        Transaction.is_excluded == 0,
        Transaction.transfer_id.is_(None),
        Transaction.is_projected == 0,
    ]
    if current_month:
        base_filter.append(func.extract("month", Transaction.date) == current_month)
    if account_id:
        base_filter.append(Transaction.account_id == account_id)

    # Top merchants by total spending (expenses only)
    # Note: counterparty is encrypted, so GROUP BY won't work — aggregate in Python
    merchant_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(*base_filter, Transaction.amount < 0)
        .all()
    )
    merchant_agg = {}
    for tx in merchant_txs:
        cp = (tx.counterparty or "").strip()
        if not cp:
            continue
        if cp not in merchant_agg:
            merchant_agg[cp] = {"total": Decimal("0"), "tx_count": 0}
        merchant_agg[cp]["total"] += tx.amount
        merchant_agg[cp]["tx_count"] += 1
    top_merchants_list = sorted(merchant_agg.items(), key=lambda x: x[1]["total"])[:15]

    class MerchantRow:
        def __init__(self, counterparty, total, tx_count):
            self.counterparty = counterparty
            self.total = total
            self.tx_count = tx_count

    top_merchants = [MerchantRow(cp, d["total"], d["tx_count"]) for cp, d in top_merchants_list]

    # Top categories by spending
    top_categories = (
        db.query(
            Category.name,
            Category.color,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .filter(*base_filter, Transaction.amount < 0, Category.exclude_from_totals == 0)
        .group_by(Category.id, Category.name, Category.color)
        .order_by(func.sum(Transaction.amount))
        .limit(10)
        .all()
    )

    # New counterparties this period (not seen before)
    # Note: counterparty is encrypted — must compare in Python
    if current_month:
        prev_txs = (
            db.query(Transaction)
            .join(Account)
            .filter(
                Account.user_id == user.id,
                func.extract("year", Transaction.date) == current_year,
                func.extract("month", Transaction.date) < current_month,
            )
            .all()
        )
    else:
        prev_txs = (
            db.query(Transaction)
            .join(Account)
            .filter(
                Account.user_id == user.id,
                func.extract("year", Transaction.date) < current_year,
            )
            .all()
        )
    seen_before_set = {(tx.counterparty or "").strip().lower() for tx in prev_txs if tx.counterparty}

    # Current period counterparties
    current_cp_agg = {}
    for tx in merchant_txs:  # reuse from top_merchants query above (all expense txs)
        cp = (tx.counterparty or "").strip()
        if not cp:
            continue
        cp_lower = cp.lower()
        if cp_lower in seen_before_set:
            continue
        if cp not in current_cp_agg:
            current_cp_agg[cp] = {"total": Decimal("0"), "tx_count": 0}
        current_cp_agg[cp]["total"] += tx.amount
        current_cp_agg[cp]["tx_count"] += 1

    # Also include positive (income) new counterparties
    income_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(*base_filter, Transaction.amount > 0)
        .all()
    )
    for tx in income_txs:
        cp = (tx.counterparty or "").strip()
        if not cp or cp.lower() in seen_before_set:
            continue
        if cp not in current_cp_agg:
            current_cp_agg[cp] = {"total": Decimal("0"), "tx_count": 0}
        current_cp_agg[cp]["total"] += tx.amount
        current_cp_agg[cp]["tx_count"] += 1

    new_counterparties_sorted = sorted(current_cp_agg.items(), key=lambda x: x[1]["tx_count"], reverse=True)[:10]

    new_counterparties = [
        {
            "counterparty": cp,
            "total": d["total"],
            "tx_count": d["tx_count"],
        }
        for cp, d in new_counterparties_sorted
    ]

    # Total income/expenses for context
    totals = (
        db.query(
            func.sum(case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))).label("income"),
            func.sum(case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))).label("expenses"),
            func.count(Transaction.id).label("tx_count"),
        )
        .join(Account)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(*base_filter)
        .filter(or_(Category.id.is_(None), Category.exclude_from_totals == 0))
        .first()
    )

    # Years selector
    tx_years = (
        db.query(func.extract("year", Transaction.date).label("yr"))
        .join(Account)
        .filter(Account.user_id == user.id)
        .distinct()
        .all()
    )
    years = sorted({int(r.yr) for r in tx_years} | {current_year})

    MONTH_NAMES_NL_FULL = {
        0: "Heel jaar",
        1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
        9: "September", 10: "Oktober", 11: "November", 12: "December",
    }

    return templates.TemplateResponse(
        "analytics/stats.html",
        {
            "request": request,
            "user": user,
            "current_year": current_year,
            "current_month": current_month,
            "years": years,
            "months_full": MONTH_NAMES_NL_FULL,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "top_merchants": top_merchants,
            "top_categories": top_categories,
            "new_counterparties": new_counterparties,
            "total_income": totals.income or Decimal("0"),
            "total_expenses": totals.expenses or Decimal("0"),
            "total_tx_count": totals.tx_count or 0,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Flexibele query-builder
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/analytics/query")
def analytics_query(
    request: Request,
    date_from: str = Query(""),
    date_to: str = Query(""),
    group_by: str = Query("category"),
    direction: str = Query("expense"),
    account_id: int = Query(0),
    fmt: str = Query(""),
    db: Session = Depends(get_db),
):
    from datetime import date as _date_type
    user = require_login(request, db)

    accounts = db.query(Account).filter(Account.user_id == user.id).order_by(Account.name).all()

    has_filter = bool(date_from or date_to or account_id)
    results = []
    grand_total = Decimal("0")

    if has_filter or True:  # always show form + results if submitted
        base_filter = [
            Account.user_id == user.id,
            Transaction.is_excluded == 0,
            Transaction.transfer_id.is_(None),
            Transaction.is_projected == 0,
        ]
        if date_from:
            try:
                base_filter.append(Transaction.date >= _date_type.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                base_filter.append(Transaction.date <= _date_type.fromisoformat(date_to))
            except ValueError:
                pass
        if account_id:
            base_filter.append(Transaction.account_id == account_id)
        if direction == "expense":
            base_filter.append(Transaction.amount < 0)
        elif direction == "income":
            base_filter.append(Transaction.amount > 0)

        NL_MONTHS_SHORT = ["", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                           "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]

        if group_by == "category":
            rows = (
                db.query(
                    Category.name.label("label"),
                    Category.color.label("color"),
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("tx_count"),
                )
                .join(Transaction, Transaction.category_id == Category.id)
                .join(Account, Account.id == Transaction.account_id)
                .filter(*base_filter, Category.exclude_from_totals == 0)
                .group_by(Category.id, Category.name, Category.color)
                .order_by(func.sum(Transaction.amount))
                .all()
            )
            results = [{"label": r.label, "color": r.color or "#888",
                        "total": r.total or Decimal("0"), "tx_count": r.tx_count} for r in rows]
            # Uncategorized
            uncat = db.query(
                func.sum(Transaction.amount), func.count(Transaction.id)
            ).join(Account).filter(*base_filter, Transaction.category_id.is_(None)).first()
            if uncat and uncat[0]:
                results.append({"label": "Zonder categorie", "color": "#ccc",
                                 "total": uncat[0], "tx_count": uncat[1] or 0})

        elif group_by == "counterparty":
            # Encrypted field — aggregate in Python
            all_txs = (
                db.query(Transaction)
                .join(Account)
                .filter(*base_filter)
                .all()
            )
            cp_agg = {}
            for tx in all_txs:
                cp = (tx.counterparty or "").strip() or "—"
                if cp not in cp_agg:
                    cp_agg[cp] = {"total": Decimal("0"), "tx_count": 0}
                cp_agg[cp]["total"] += tx.amount
                cp_agg[cp]["tx_count"] += 1
            sorted_cp = sorted(cp_agg.items(), key=lambda x: x[1]["total"])[:100]
            results = [{"label": cp, "color": "#888",
                        "total": d["total"], "tx_count": d["tx_count"]} for cp, d in sorted_cp]

        elif group_by == "month":
            rows = (
                db.query(
                    func.extract("year", Transaction.date).label("yr"),
                    func.extract("month", Transaction.date).label("mo"),
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("tx_count"),
                )
                .join(Account)
                .filter(*base_filter)
                .group_by(func.extract("year", Transaction.date), func.extract("month", Transaction.date))
                .order_by(func.extract("year", Transaction.date), func.extract("month", Transaction.date))
                .all()
            )
            results = [{"label": f"{NL_MONTHS_SHORT[int(r.mo)]} {int(r.yr)}",
                        "color": "#888", "total": r.total or Decimal("0"), "tx_count": r.tx_count}
                       for r in rows]

        grand_total = sum(abs(r["total"]) for r in results)

    # CSV download
    if fmt == "csv" and results:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Groep", "Totaal (€)", "Transacties", "% van totaal"])
        for r in results:
            pct = round(abs(r["total"]) / grand_total * 100, 1) if grand_total else 0
            writer.writerow([r["label"], str(abs(r["total"])), r["tx_count"], pct])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="query-export.csv"'},
        )

    return templates.TemplateResponse(
        "analytics/query.html",
        {
            "request": request, "user": user,
            "accounts": accounts,
            "current_account_id": account_id or None,
            "date_from": date_from,
            "date_to": date_to,
            "group_by": group_by,
            "direction": direction,
            "results": results,
            "grand_total": grand_total,
            "has_results": bool(results),
        },
    )
