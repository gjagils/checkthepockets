"""ACT-52a: ``Flag`` geeft Python-bools en blijft 0/1 in de database."""
from sqlalchemy import text

from app.auth import hash_password
from app.models import User


def _user(db, **kw):
    user = User(username=kw.pop("username", "flag"), password_hash=hash_password("pw"), **kw)
    db.add(user)
    db.commit()
    return user


def test_flags_read_as_bool_and_store_as_integers(db):
    user = _user(db, is_admin=1, can_access_mortgage=0)
    db.expire_all()
    loaded = db.get(User, user.id)
    assert loaded.is_admin is True and loaded.can_access_mortgage is False
    assert loaded.is_active is True and loaded.is_verified is True           # defaults
    raw = db.execute(text("SELECT is_admin, can_access_mortgage, is_active FROM users")).one()
    assert tuple(raw) == (1, 0, 1)


def test_assignments_with_integers_booleans_and_strings(db):
    user = _user(db)
    for value, expected in ((1, 1), (0, 0), (True, 1), (False, 0), ("1", 1), ("0", 0)):
        user.weekly_digest_enabled = value
        db.commit()
        assert db.execute(text("SELECT weekly_digest_enabled FROM users")).scalar() == expected


def test_existing_style_filters_still_work(db):
    _user(db, username="a", is_admin=1)
    _user(db, username="b", is_admin=0)
    assert [u.username for u in db.query(User).filter(User.is_admin == 1).all()] == ["a"]
    assert [u.username for u in db.query(User).filter(User.is_admin == 0).all()] == ["b"]


def test_transaction_flags_are_bools_and_filters_keep_working(db):
    import datetime

    from app.models import Account, Transaction

    user = _user(db, username="tx")
    account = Account(user_id=user.id, name="A", bank="abn_amro")
    db.add(account)
    db.flush()
    db.add_all([
        Transaction(account_id=account.id, date=datetime.date(2026, 1, 1), amount=1, import_hash="a", is_excluded=1),
        Transaction(account_id=account.id, date=datetime.date(2026, 1, 2), amount=1, import_hash="b"),
        Transaction(account_id=account.id, date=datetime.date(2026, 1, 3), amount=1, import_hash="c", is_projected=1),
    ])
    db.commit()
    rows = {t.import_hash: t for t in db.query(Transaction).all()}
    assert rows["a"].is_excluded is True and rows["b"].is_excluded is False and rows["b"].is_reviewed is False
    assert rows["c"].is_projected is True
    assert db.query(Transaction).filter(Transaction.is_excluded == 0, Transaction.is_projected == 0).count() == 1
    db.query(Transaction).filter(Transaction.import_hash == "b").update({"is_reviewed": 1})
    db.commit()
    db.expire_all()
    assert db.query(Transaction).filter_by(import_hash="b").one().is_reviewed is True


def test_category_flags_are_bools_and_backup_export_keeps_integers(db):
    from fastapi.testclient import TestClient

    from app.auth import create_session_cookie
    from app.main import app
    from app.models import Category

    user = _user(db, username="cat")
    db.add_all([Category(user_id=user.id, name="Salaris", is_income=1),
                Category(user_id=user.id, name="Oud", is_archived=1, exclude_from_budget=1)])
    db.commit()
    rows = {c.name: c for c in db.query(Category).all()}
    assert rows["Salaris"].is_income is True and rows["Salaris"].is_archived is False
    assert rows["Oud"].exclude_from_budget is True and rows["Oud"].exclude_from_totals is False
    assert db.query(Category).filter(Category.is_income == 1).count() == 1
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    export = client.get("/settings/export")
    assert export.status_code == 200
    cats = {c["name"]: c for c in export.json()["categories"]}
    assert cats["Salaris"]["is_income"] == 1 and type(cats["Salaris"]["is_income"]) is int
    assert cats["Oud"]["is_archived"] == 1 and cats["Oud"]["exclude_from_totals"] == 0


def test_remaining_flags_are_bools_and_rule_recurring_export_keeps_integers(db):
    import datetime

    from fastapi.testclient import TestClient

    from app.auth import create_session_cookie
    from app.main import app
    from app.models import Category

    user = _user(db, username="cat")
    db.add_all([Category(user_id=user.id, name="Salaris", is_income=1),
                Category(user_id=user.id, name="Oud", is_archived=1, exclude_from_budget=1)])
    db.commit()
    rows = {c.name: c for c in db.query(Category).all()}
    assert rows["Salaris"].is_income is True and rows["Salaris"].is_archived is False
    assert rows["Oud"].exclude_from_budget is True and rows["Oud"].exclude_from_totals is False
    assert db.query(Category).filter(Category.is_income == 1).count() == 1
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    export = client.get("/settings/export")
    assert export.status_code == 200
    cats = {c["name"]: c for c in export.json()["categories"]}
    assert cats["Salaris"]["is_income"] == 1 and type(cats["Salaris"]["is_income"]) is int
    assert cats["Oud"]["is_archived"] == 1 and cats["Oud"]["exclude_from_totals"] == 0

    from app.models import Account, NetWorthAccount, RecurringTransaction, Rule, SavingsLine, SavingsPlan

    user = _user(db, username="rest")
    account = Account(user_id=user.id, name="A", bank="bunq")
    db.add(account)
    db.flush()
    db.add_all([
        Rule(user_id=user.id, name="r", match_field="counterparty", match_type="contains", match_value="x",
             is_active=1, action_set_reviewed=1),
        RecurringTransaction(user_id=user.id, account_id=account.id, name="Huur", amount_expected=-1,
                             frequency="monthly", is_active=0),
        NetWorthAccount(user_id=user.id, name="Spaar", account_type="asset", category="savings"),
    ])
    plan = SavingsPlan(user_id=user.id, account_id=account.id, year=datetime.date.today().year)
    db.add(plan)
    db.flush()
    db.add(SavingsLine(plan_id=plan.id, name="Vakantie", is_income=1))
    db.commit()
    rule = db.query(Rule).one()
    assert rule.is_active is True and rule.action_set_reviewed is True
    assert db.query(RecurringTransaction).one().is_active is False
    assert db.query(NetWorthAccount).one().is_active is True
    assert db.query(SavingsLine).one().is_income is True
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    data = client.get("/settings/export").json()
    assert data["rules"][0]["is_active"] == 1 and type(data["rules"][0]["is_active"]) is int
    assert data["recurring"][0]["is_active"] == 0 and type(data["recurring"][0]["is_active"]) is int
