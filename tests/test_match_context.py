"""ACT-45b: terugkerende posten matchen met één query per periode in plaats van twee per item."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event

from app import clock
from app.auth import create_session_cookie, hash_password
from app.database import engine
from app.main import app
from app.models import Account, RecurringTransaction, Transaction, User
from app.recurring_schedule import get_period_range
from app.recurring_service import MatchContext, find_matching_transaction, sync_projected_transactions


@contextmanager
def transaction_selects():
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM transactions" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _world(db, items):
    today = clock.today_nl()
    user = User(username=f"match-user-{items}", password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="A", bank="x")
    db.add(account)
    db.flush()
    db.add(Transaction(account_id=account.id, date=date(today.year - 1, 1, 15), amount=Decimal("-1"),
                       description="oud", import_hash="old"))
    recurring = []
    for i in range(items):
        item = RecurringTransaction(user_id=user.id, account_id=account.id, name=f"Abonnement {i}",
                                    amount_expected=Decimal("-10"), frequency="monthly", is_active=1,
                                    counterparty=f"Shop{i}", start_date=date(today.year - 1, 1, 1))
        db.add(item)
        recurring.append(item)
    db.flush()
    for i, item in enumerate(recurring):
        if i % 3 == 0:        # gekoppeld
            db.add(Transaction(account_id=account.id, date=today.replace(day=1), amount=Decimal("-10"),
                               description="x", counterparty="anders", import_hash=f"l{i}", recurring_id=item.id))
        elif i % 3 == 1:      # alleen op tegenpartij te matchen
            db.add(Transaction(account_id=account.id, date=today.replace(day=2), amount=Decimal("-10"),
                               description="x", counterparty=f"Betaling SHOP{i} Amsterdam", import_hash=f"c{i}"))
        # i % 3 == 2: geen match
    db.commit()
    return user, account, recurring, today


def _naive(db, user_id, item, start, end):
    """De oorspronkelijke aanpak: eerst gekoppeld, dan op tegenpartij/omschrijving, met eigen queries."""
    base = (db.query(Transaction).join(Account)
            .filter(Account.user_id == user_id, Transaction.date >= start, Transaction.date <= end,
                    Transaction.is_excluded == 0, Transaction.is_projected == 0)
            .order_by(Transaction.date.desc(), Transaction.id.desc()).all())
    for tx in base:
        if tx.recurring_id == item.id:
            return tx
    cp = (item.counterparty or "").lower()
    for tx in base:
        if cp and (cp in (tx.counterparty or "").lower() or cp in (tx.description or "").lower()):
            return tx
    return None


def test_context_finds_the_same_matches_as_the_naive_approach(db):
    user, account, items, today = _world(db, 12)
    start, end = get_period_range("monthly", today)
    ctx = MatchContext(db, user.id)
    for item in items:
        assert ctx.find(item, start, end) == _naive(db, user.id, item, start, end)
        assert find_matching_transaction(db, user.id, item, start, end) == ctx.find(item, start, end)
    matched = [item for item in items if ctx.find(item, start, end)]
    assert len(matched) == 8                                         # 4 gekoppeld + 4 op tegenpartij


def test_matching_many_items_loads_the_period_once(db):
    user, account, items, today = _world(db, 15)
    start, end = get_period_range("monthly", today)
    ctx = MatchContext(db, user.id)
    with transaction_selects() as queries:
        for item in items:
            ctx.find(item, start, end)
    assert len(queries) == 1                                         # was 2 per item = 30


def test_projection_sync_query_count_does_not_grow_with_the_number_of_items(db):
    user_small, _a, _items, today = _world(db, 4)
    with transaction_selects() as small:
        sync_projected_transactions(user_small.id, today.year, today.month, db)
    user_big, _b, _items2, _t = _world(db, 20)
    with transaction_selects() as big:
        sync_projected_transactions(user_big.id, today.year, today.month, db)
    # De sync zoekt per item nog naar de eigen projectie (op hash), maar het matchen zelf kost 1 query.
    match_queries = [q for q in big if "transactions.is_projected = ?" in q and "transactions.date >=" in q]
    assert len(match_queries) == 1


def test_recurring_page_renders_with_a_bounded_number_of_transaction_queries(db):
    user, account, items, today = _world(db, 20)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    with transaction_selects() as queries:
        response = client.get("/recurring")
    assert response.status_code == 200
    assert len(queries) <= 35, len(queries)                          # gemeten: 103 -> 25 bij 20 items (rest: opzoeking per item op hash)
