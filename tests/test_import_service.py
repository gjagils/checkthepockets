"""Regression tests for the shared import service (ACT-21)."""
import base64
import json
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.import_service import store_confirmed_csv_rows, store_parsed_transactions
from app.main import app
from app.models import Account, Category, ImportBatch, Rule, Transaction, User
from app.parsers.base import ParsedTransaction


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _user_with_accounts(db, username="import-user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.flush()
    first = Account(user_id=user.id, name="Betaal", bank="custom")
    second = Account(user_id=user.id, name="Spaar", bank="custom")
    db.add_all([first, second])
    db.flush()
    return user, first, second


def _groceries_rule(db, user):
    category = Category(user_id=user.id, name="Boodschappen")
    db.add(category)
    db.flush()
    rule = Rule(
        user_id=user.id, name="Supermarkt", is_active=1,
        match_field="counterparty", match_type="contains", match_value="Albert",
        assign_category_id=category.id,
    )
    db.add(rule)
    db.flush()
    return category, rule


def _csv_row(import_hash, **overrides):
    row = {
        "date": "2026-09-01", "amount": "-12.50", "currency": "EUR",
        "description": "Pinbetaling", "counterparty": "Albert Heijn",
        "counterparty_iban": None, "balance_after": "100.00",
        "import_hash": import_hash, "category_name": "",
    }
    row.update(overrides)
    return row


def test_parsed_transactions_are_unique_per_account_and_categorized(db):
    user, first, second = _user_with_accounts(db)
    category, rule = _groceries_rule(db, user)
    parsed = [
        ParsedTransaction(date=date(2026, 9, 1), amount=Decimal("-12.50"), currency="EUR",
                          description="Pinbetaling", counterparty="Albert Heijn"),
        ParsedTransaction(date=date(2026, 9, 2), amount=Decimal("-5.00"), currency="EUR",
                          description="Koffie", counterparty="Café"),
    ]

    result = store_parsed_transactions(db, first, parsed, [rule], import_batch_id=None)
    again = store_parsed_transactions(db, first, parsed, [rule])
    other_account = store_parsed_transactions(db, second, parsed[:1], [rule])

    assert (result.imported, result.skipped, result.auto_categorized) == (2, 0, 1)
    assert (again.imported, again.skipped) == (0, 2)
    assert other_account.imported == 1
    grocery = db.query(Transaction).filter_by(account_id=first.id, counterparty="Albert Heijn").one()
    assert grocery.category_id == category.id


def test_csv_rows_skip_duplicates_reject_invalid_and_keep_category_precedence(db):
    user, first, second = _user_with_accounts(db)
    rule_category, rule = _groceries_rule(db, user)
    csv_category = Category(user_id=user.id, name="Huishouden")
    db.add(csv_category)
    db.flush()
    categories = {c.name.lower(): c for c in db.query(Category).filter_by(user_id=user.id)}
    rows = [
        _csv_row("h-rule"),
        _csv_row("h-csv", category_name="  HUISHOUDEN "),
        _csv_row("h-plain", counterparty="Onbekend", balance_after=None),
        _csv_row("h-bad-date", date="31-02-2026"),
        _csv_row("h-bad-amount", amount="twaalf"),
    ]

    result = store_confirmed_csv_rows(db, first, rows, categories, [rule], import_batch_id=None)
    repeat = store_confirmed_csv_rows(db, first, rows, categories, [rule])
    other_account = store_confirmed_csv_rows(db, second, rows[:1], categories, [rule])

    assert (result.imported, result.skipped, result.rejected, result.auto_categorized) == (3, 0, 2, 2)
    # Invalid rows are never stored, so a repeat rejects them again.
    assert (repeat.imported, repeat.skipped, repeat.rejected) == (0, 3, 2)
    assert other_account.imported == 1
    stored = {tx.import_hash: tx for tx in db.query(Transaction).filter_by(account_id=first.id)}
    assert stored["h-rule"].category_id == rule_category.id
    assert stored["h-csv"].category_id == csv_category.id
    assert stored["h-plain"].category_id is None
    assert stored["h-plain"].balance_after is None
    assert stored["h-rule"].amount == Decimal("-12.50")


def test_import_confirm_route_records_batch_and_is_repeatable(db):
    user = User(username="csv-route", password_hash="x")
    db.add(user)
    db.commit()
    rows = [_csv_row("route-1"), _csv_row("route-2", amount="-3.00"), _csv_row("route-bad", date="geen")]
    form = {
        "tx_data": base64.b64encode(json.dumps(rows).encode()).decode(),
        "bank": "custom", "account_iban": "", "account_name": "CSV rekening",
    }
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))

    first = client.post("/import/confirm", data=form)
    second = client.post("/import/confirm", data=form)

    assert first.status_code == 200
    assert second.status_code == 200
    db.expire_all()
    account = db.query(Account).filter_by(user_id=user.id).one()
    assert account.name == "CSV rekening"
    assert db.query(Transaction).filter_by(account_id=account.id).count() == 2
    batches = db.query(ImportBatch).filter_by(user_id=user.id).order_by(ImportBatch.id).all()
    counts = [(b.total_count, b.imported_count, b.skipped_count, b.rejected_count) for b in batches]
    assert counts == [(3, 2, 0, 1), (3, 0, 2, 1)]
    assert {tx.import_batch_id for tx in db.query(Transaction).filter_by(account_id=account.id)} == {batches[0].id}
