"""ACT-34a: crash- en datafouten uit de codereview (A4, A6, A7, A8, A10, A11, A14)."""
import ast
import logging
import pathlib
import tempfile
from datetime import date, datetime
from decimal import Decimal

import pytest


from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.scheduler as scheduler
from app.auth import create_session_cookie, hash_password
from app.database import Base
from app.main import app
from app.models import (
    Account, Budget, Category, Rule, RuleSuggestion, SavingsLine, SavingsPlan, Transaction, User,
)
from app.routers.categories import delete_category_tree
from app.routers.savings import _get_transaction_totals_by_month, _has_transactions_in_month


def _world(db, name="crash-user"):
    user = User(username=name, password_hash=hash_password("x" * 10), is_admin=1)
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Betaal", bank="abn_amro")
    db.add(account)
    db.flush()
    return user, account


def _tx(account, day, amount, n, month=5, **extra):
    return Transaction(account_id=account.id, date=date(2026, month, day), amount=Decimal(amount),
                       counterparty="x", description="x", import_hash=f"h{n}", **extra)


def _client(user):
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


# ── A4 ─────────────────────────────────────────────────────────────────────

def _fk_engine():
    """Own SQLite engine whose every connection enforces foreign keys, like PostgreSQL does."""
    from sqlalchemy import create_engine, event

    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path.close()
    fk_engine = create_engine(f"sqlite:///{path.name}")

    @event.listens_for(fk_engine, "connect")
    def _pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=fk_engine)
    return fk_engine


def test_delete_category_tree_respects_foreign_keys():
    """Met FK's aan (zoals PostgreSQL) gaf de oude code hier een IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    fk_engine = _fk_engine()
    with Session(bind=fk_engine) as session:
        user, account = _world(session, "fk-user")
        parent = Category(user_id=user.id, name="Wonen")
        session.add(parent)
        session.flush()
        child = Category(user_id=user.id, name="Energie", parent_id=parent.id)
        other = Category(user_id=user.id, name="Blijft")
        session.add_all([child, other])
        session.flush()
        plan = SavingsPlan(user_id=user.id, account_id=account.id, year=2026)
        session.add(plan)
        session.flush()
        session.add_all([
            _tx(account, 1, "-50.00", 1, category_id=child.id),
            _tx(account, 2, "-20.00", 2, category_id=other.id),
            Budget(user_id=user.id, category_id=parent.id, year=2026, month=5, amount=Decimal("100")),
            Budget(user_id=user.id, category_id=child.id, year=2026, month=5, amount=Decimal("40")),
            SavingsLine(plan_id=plan.id, name="Gas", category_id=child.id),
            Rule(user_id=user.id, name="r", match_field="counterparty", match_type="contains",
                 match_value="x", assign_category_id=child.id),
        ])
        session.commit()

        # Bewijs dat deze engine echt FK's afdwingt, en wat de oude aanpak deed.
        with pytest.raises(IntegrityError):
            session.query(Category).filter(Category.parent_id == parent.id).delete()
            session.delete(session.get(Category, child.id))
            session.flush()
        session.rollback()

        delete_category_tree(session, user.id, parent.id)
        session.commit()

        assert session.query(Category).count() == 1                      # alleen "Blijft"
        assert session.query(Budget).count() == 0
        cats = {t.import_hash: t.category_id for t in session.query(Transaction)}
        assert cats["h1"] is None and cats["h2"] == other.id            # transacties blijven, ontkoppeld
        assert session.query(SavingsLine).one().category_id is None
        assert session.query(Rule).one().assign_category_id is None


def test_delete_category_route_works(db):
    user, account = _world(db)
    cat = Category(user_id=user.id, name="Weg")
    db.add(cat)
    db.flush()
    db.add(_tx(account, 1, "-5.00", 1, category_id=cat.id))
    db.commit()
    cat_id = cat.id
    resp = _client(user).post(f"/categories/{cat_id}/delete")
    assert resp.status_code == 302
    db.expire_all()
    assert db.get(Category, cat_id) is None and db.query(Transaction).one().category_id is None


# ── A6 ─────────────────────────────────────────────────────────────────────

def test_weekly_digest_job_returns_a_summary(db, monkeypatch):
    user = User(username="digest", password_hash="x", email="d@x.nl", weekly_digest_enabled=1, is_active=1)
    now_nl = datetime.now(scheduler.NL_TZ)
    user.weekly_digest_weekday = now_nl.weekday()
    user.weekly_digest_hour = now_nl.hour
    db.add(user)
    db.commit()
    monkeypatch.setattr(scheduler, "compute_digest_stats", lambda db, user_id: ([("Betaal", 2)], 1, 2))
    monkeypatch.setattr("app.email_service.send_weekly_digest", lambda **kwargs: True)
    summary = scheduler._run_weekly_digests()
    assert summary == "1 verzonden, 0 mislukt, 0 overgeslagen (1 kandidaten)"


# ── A7 ─────────────────────────────────────────────────────────────────────

def test_every_enable_banking_request_has_a_timeout():
    tree = ast.parse(pathlib.Path("app/enable_banking.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "requests" and n.func.attr in ("get", "post", "put", "delete")]
    assert len(calls) >= 8
    assert all(any(k.arg == "timeout" for k in c.keywords) for c in calls)


# ── A8 ─────────────────────────────────────────────────────────────────────

def test_savings_totals_ignore_excluded_and_projected(db):
    user, account = _world(db)
    db.add_all([
        _tx(account, 1, "-10.00", 1),
        _tx(account, 2, "-90.00", 2, is_excluded=1),
        _tx(account, 3, "-900.00", 3, is_projected=1),
    ])
    db.add(_tx(account, 4, "-7.00", 4, month=6, is_projected=1))
    db.commit()
    assert _get_transaction_totals_by_month(db, account.id, 2026) == {5: Decimal("-10.00")}
    assert _has_transactions_in_month(db, account.id, 2026, 5) is True
    assert _has_transactions_in_month(db, account.id, 2026, 6) is False      # alleen een projectie


# ── A10 ────────────────────────────────────────────────────────────────────

def test_budget_from_average_uses_the_same_definition_as_the_average_column(db):
    user, account = _world(db)
    cat = Category(user_id=user.id, name="Boodschappen")
    db.add(cat)
    db.flush()
    for month in (3, 4, 5):
        db.add(_tx(account, 1, "-30.00", month, month=month, category_id=cat.id))
    db.add_all([                                           # mogen niet meetellen:
        _tx(account, 2, "-500.00", 10, month=5, category_id=cat.id, is_excluded=1),
        _tx(account, 3, "-600.00", 11, month=5, category_id=cat.id, is_projected=1),
        _tx(account, 4, "-700.00", 12, month=5, category_id=cat.id, transfer_id=None),
    ])
    db.query(Transaction)  # (de laatste telt wél mee: gewone uitgave)
    db.commit()
    resp = _client(user).post("/budgets/average", data={"to_year": 2026, "to_month": 6, "num_months": 3})
    assert resp.status_code == 302
    budget = db.query(Budget).filter_by(year=2026, month=6).one()
    # (30 + 30 + 30 + 700) / 3, zonder de uitgesloten en geprojecteerde boekingen
    assert budget.amount == Decimal("263")


# ── A11 ────────────────────────────────────────────────────────────────────

def test_rule_name_is_truncated_to_the_column_length(db):
    user, account = _world(db)
    suggestion = RuleSuggestion(user_id=user.id, match_value="x" * 120, counterparty_clean="y" * 150)
    db.add(suggestion)
    db.commit()
    resp = _client(user).post(f"/rules/suggestion/{suggestion.id}/accept", data={})
    assert resp.status_code == 302
    assert len(db.query(Rule).one().name) <= 100


# ── A14 ────────────────────────────────────────────────────────────────────

def test_admin_run_logs_a_failing_job(db, monkeypatch, caplog):
    user, _ = _world(db)
    db.commit()

    def boom():
        raise RuntimeError("kapotte job")

    monkeypatch.setattr(scheduler, "_run_weekly_digests", boom)
    with caplog.at_level(logging.ERROR):
        resp = _client(user).post("/admin/scheduler/run", data={"job_id": "weekly_digest"})
    assert resp.status_code == 302
    assert "kapotte job" in caplog.text
