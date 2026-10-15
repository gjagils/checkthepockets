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
