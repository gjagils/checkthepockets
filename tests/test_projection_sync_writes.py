"""ACT-42c: pagina's die de projectie-sync aanroepen schrijven niets zolang alles al klopt."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event

from app import clock
from app.auth import create_session_cookie
from app.database import engine
from app.main import app
from app.models import Account, RecurringTransaction, Transaction, User
from app.recurring_service import sync_projected_transactions


@contextmanager
def count_writes():
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement.split()[0].upper() + " " + statement.split()[2 if statement.upper().startswith("INSERT") else 1])

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _world(db):
    today = clock.today_nl()
    user = User(username="proj-user", password_hash="x")
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Betaal", bank="abn_amro")
    db.add(account)
    db.flush()
    # Echte historie, zodat de maand niet "vóór de eerste transactie" valt.
    db.add(Transaction(account_id=account.id, date=date(today.year - 1, 1, 15), amount=Decimal("-5.00"),
                       description="oud", import_hash="old"))
    item = RecurringTransaction(user_id=user.id, account_id=account.id, name="Huur", amount_expected=Decimal("-900.00"),
                                frequency="monthly", is_active=1, start_date=date(today.year - 1, 1, 1))
    db.add(item)
    db.commit()
    return user, account, item, today


def test_a_second_sync_of_an_unchanged_month_writes_nothing(db):
    user, account, item, today = _world(db)
    sync_projected_transactions(user.id, today.year, today.month, db)
    assert db.query(Transaction).filter_by(is_projected=1).count() == 1

    with count_writes() as writes:
        sync_projected_transactions(user.id, today.year, today.month, db)
    assert writes == []


def test_a_changed_recurring_item_still_updates_its_projection(db):
    user, account, item, today = _world(db)
    sync_projected_transactions(user.id, today.year, today.month, db)

    item.amount_expected = Decimal("-950.00")
    db.commit()
    with count_writes() as writes:
        sync_projected_transactions(user.id, today.year, today.month, db)
    assert writes == ["UPDATE transactions"]
    db.expire_all()
    assert db.query(Transaction).filter_by(is_projected=1).one().amount == Decimal("-950.00")


def test_viewing_the_dashboard_twice_does_not_write_the_second_time(db):
    user, account, item, today = _world(db)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    assert client.get("/dashboard").status_code == 200              # eerste keer mag projecties aanmaken
    with count_writes() as writes:
        assert client.get("/dashboard").status_code == 200
    assert writes == []
