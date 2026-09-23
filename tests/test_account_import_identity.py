"""The same bank transaction may exist on separate user accounts."""
import os
import tempfile
from datetime import date
from decimal import Decimal

db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{db_file.name}"

from sqlalchemy.exc import IntegrityError
from app.database import Base, SessionLocal, engine
from app.models import Account, Transaction, User


def test_import_hash_is_unique_per_account():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(username="import-identity", password_hash="x")
        db.add(user)
        db.flush()
        first = Account(user_id=user.id, name="Current", bank="abn")
        second = Account(user_id=user.id, name="Savings", bank="abn")
        db.add_all([first, second])
        db.flush()
        common = dict(date=date(2026, 1, 1), amount=Decimal("10.00"), description="same", import_hash="same-hash")
        db.add_all([Transaction(account_id=first.id, **common), Transaction(account_id=second.id, **common)])
        db.commit()
        db.add(Transaction(account_id=first.id, **common))
        try:
            db.commit()
            raise AssertionError("duplicate import on one account was accepted")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
