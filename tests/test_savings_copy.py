"""Tests for "kopieer van vorig jaar" op spaarplannen (GJA-13)."""
import datetime
import os
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    Account,
    Category,
    SavingsEntry,
    SavingsLine,
    SavingsPlan,
    Transaction,
    User,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(SavingsEntry).delete()
        db.query(SavingsLine).delete()
        db.query(SavingsPlan).delete()
        db.query(Transaction).delete()
        db.query(Category).delete()
        db.query(Account).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice"):
    u = User(username=username, email=f"{username}@x.nl", password_hash=hash_password("pw"))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user, name="Spaarrekening"):
    a = Account(user_id=user.id, name=name, bank="abn_amro", iban="NL00ABNA0000000000")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_category(db, user, account, name="Vakantie", is_income=0):
    c = Category(user_id=user.id, account_id=account.id, name=name, is_income=is_income)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_plan(db, user, account, year, starting_balance=Decimal("1000"), source_plan_id=None):
    p = SavingsPlan(
        user_id=user.id,
        account_id=account.id,
        year=year,
        starting_balance=starting_balance,
        source_plan_id=source_plan_id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_line(db, plan, name, frequency="monthly", default_amount=Decimal("100"),
               is_income=0, category_id=None, custom_amounts=None):
    line = SavingsLine(
        plan_id=plan.id,
        name=name,
        frequency=frequency,
        default_amount=default_amount,
        is_income=is_income,
        category_id=category_id,
        annual_budget=default_amount * 12,
        sort_order=0,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    # Create 12 entries
    for m in range(1, 13):
        if custom_amounts is not None:
            amt = custom_amounts.get(m)
        else:
            if frequency == "monthly":
                amt = default_amount
            elif frequency == "yearly":
                amt = default_amount if m == 12 else None
            else:
                amt = default_amount
        db.add(SavingsEntry(line_id=line.id, month=m, amount=amt, status="forecast"))
    db.commit()
    return line


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_create_plan_with_source_copies_lines(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)
    cat = _make_category(db_session, alice, acc, name="Vaste lasten")

    src = _make_plan(db_session, alice, acc, 2025, starting_balance=Decimal("500"))
    _make_line(db_session, src, "Huur", default_amount=Decimal("800"), category_id=cat.id)
    _make_line(db_session, src, "Boodschappen", default_amount=Decimal("350"))

    client = _login_client(alice.id)
    resp = client.post("/savings", data={
        "account_id": str(acc.id),
        "year": "2026",
        "starting_balance": "0",
        "source_plan_id": str(src.id),
    }, follow_redirects=False)
    assert resp.status_code == 302

    new_plan = (
        db_session.query(SavingsPlan)
        .filter(SavingsPlan.account_id == acc.id, SavingsPlan.year == 2026)
        .first()
    )
    assert new_plan is not None
    assert new_plan.source_plan_id == src.id
    names = sorted(l.name for l in new_plan.lines)
    assert names == ["Boodschappen", "Huur"]
    huur = next(l for l in new_plan.lines if l.name == "Huur")
    assert huur.category_id == cat.id
    assert huur.default_amount == Decimal("800")


def test_linked_plan_starting_balance_follows_source_december(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)

    src = _make_plan(db_session, alice, acc, 2025, starting_balance=Decimal("1000"))
    # 12 × €100 income → +€1200; eindsaldo = 1000 + 1200 = 2200
    _make_line(db_session, src, "Salaris", default_amount=Decimal("100"), is_income=1)

    new_plan = _make_plan(
        db_session, alice, acc, 2026,
        starting_balance=Decimal("0"),
        source_plan_id=src.id,
    )

    client = _login_client(alice.id)
    resp = client.get(f"/savings/{new_plan.id}")
    assert resp.status_code == 200
    # Effective starting balance = €2200,00 should appear in the page header
    body = resp.text
    assert "2.200,00" in body or "2200,00" in body
    # Source-link badge
    assert "Volgt 2025" in body


def test_linked_plan_updates_when_source_changes(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)

    src = _make_plan(db_session, alice, acc, 2025, starting_balance=Decimal("500"))
    salary = _make_line(db_session, src, "Salaris", default_amount=Decimal("100"), is_income=1)
    # Initial december balance = 500 + 12*100 = 1700

    new_plan = _make_plan(
        db_session, alice, acc, 2026,
        starting_balance=Decimal("0"),
        source_plan_id=src.id,
    )

    client = _login_client(alice.id)
    resp = client.get(f"/savings/{new_plan.id}")
    assert resp.status_code == 200
    assert "1.700,00" in resp.text

    # Now bump the source: add €50/month → new dec total = 500 + 12*150 = 2300
    for e in salary.entries:
        e.amount = Decimal("150")
    db_session.commit()

    resp = client.get(f"/savings/{new_plan.id}")
    assert resp.status_code == 200
    assert "2.300,00" in resp.text
    # plan.starting_balance stays at 0 (not persisted)
    db_session.refresh(new_plan)
    assert new_plan.starting_balance == Decimal("0")


def test_unlink_freezes_starting_balance(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)

    src = _make_plan(db_session, alice, acc, 2025, starting_balance=Decimal("500"))
    _make_line(db_session, src, "Salaris", default_amount=Decimal("100"), is_income=1)
    # dec balance = 500 + 1200 = 1700

    new_plan = _make_plan(
        db_session, alice, acc, 2026,
        starting_balance=Decimal("0"),
        source_plan_id=src.id,
    )

    client = _login_client(alice.id)
    resp = client.post(f"/savings/{new_plan.id}/unlink", follow_redirects=False)
    assert resp.status_code == 302

    db_session.refresh(new_plan)
    assert new_plan.source_plan_id is None
    assert new_plan.starting_balance == Decimal("1700")


def test_copy_custom_frequency_preserves_monthly_amounts(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice)

    src = _make_plan(db_session, alice, acc, 2025, starting_balance=Decimal("0"))
    custom = {1: Decimal("50"), 6: Decimal("200"), 12: Decimal("75")}
    _make_line(
        db_session, src, "Onregelmatig",
        frequency="custom",
        default_amount=Decimal("0"),
        custom_amounts=custom,
    )

    client = _login_client(alice.id)
    resp = client.post("/savings", data={
        "account_id": str(acc.id),
        "year": "2026",
        "starting_balance": "0",
        "source_plan_id": str(src.id),
    }, follow_redirects=False)
    assert resp.status_code == 302

    new_plan = (
        db_session.query(SavingsPlan)
        .filter(SavingsPlan.account_id == acc.id, SavingsPlan.year == 2026)
        .first()
    )
    assert new_plan is not None
    line = new_plan.lines[0]
    assert line.frequency == "custom"
    by_month = {e.month: e.amount for e in line.entries}
    assert by_month[1] == Decimal("50")
    assert by_month[6] == Decimal("200")
    assert by_month[12] == Decimal("75")
    # months that were None in source stay None
    assert by_month[2] is None
