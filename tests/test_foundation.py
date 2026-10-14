"""ACT-39: de gedeelde testbasis (tests/conftest.py) doet wat hij belooft."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.models import Account, Transaction, User


def test_foreign_keys_are_enforced_like_in_postgresql(db):
    assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    db.add(Account(user_id=9999, name="Wees", bank="x"))          # bestaat niet
    with pytest.raises(IntegrityError):
        db.flush()


def test_there_is_one_shared_test_database():
    from tests.conftest import _DB_FILE

    assert engine.url.database == _DB_FILE.name


@pytest.mark.parametrize("round_", [1, 2])
def test_every_test_starts_with_empty_tables(db, round_):
    """Twee keer dezelfde test: wat de eerste achterlaat mag de tweede niet zien."""
    assert db.query(User).count() == 0 and db.query(Transaction).count() == 0
    db.add(User(username="blijft-niet", password_hash="x"))
    db.commit()


def test_db_session_is_an_alias_of_db(db, db_session):
    assert db is db_session
