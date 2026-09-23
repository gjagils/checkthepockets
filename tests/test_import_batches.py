import os
import tempfile

db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{db_file.name}"

from app.database import Base, SessionLocal, engine
from app.models import Account, ImportBatch, User


def test_import_batch_is_owned_and_tracks_counts():
    Base.metadata.create_all(bind=engine)
    db_session = SessionLocal()
    user = User(username="batch-user", password_hash="x")
    other = User(username="batch-other", password_hash="x")
    db_session.add_all([user, other])
    db_session.flush()
    account = Account(user_id=user.id, name="Test", bank="custom")
    db_session.add(account)
    db_session.flush()
    batch = ImportBatch(
        user_id=user.id, account_id=account.id, source="csv:custom",
        total_count=4, imported_count=2, skipped_count=1, rejected_count=1,
    )
    db_session.add(batch)
    try:
        db_session.commit()
        assert db_session.query(ImportBatch).filter_by(user_id=user.id).count() == 1
        assert db_session.query(ImportBatch).filter_by(user_id=other.id).count() == 0
        saved = db_session.query(ImportBatch).one()
        assert (saved.total_count, saved.imported_count, saved.skipped_count, saved.rejected_count) == (4, 2, 1, 1)
    finally:
        db_session.close()
        Base.metadata.drop_all(bind=engine)
