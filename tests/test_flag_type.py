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
