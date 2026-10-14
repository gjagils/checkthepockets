"""Rekeningen samenvoegen: preview, dubbelen herkennen en gegevens behouden."""
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

from app.account_merge import merge_accounts, plan_merge
from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, Category, ImportBatch, Transaction, User


@pytest.fixture(autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _setup(db, username="merge-user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.flush()
    source = Account(user_id=user.id, name="ABN Samen Betaal", bank="abn_amro")
    target = Account(user_id=user.id, name="Samen Betaal", bank="abn_amro", iban="NL45ABNA0503737143", external_uid="uid-1")
    db.add_all([source, target])
    db.flush()
    return user, source, target


def _tx(account, day, amount, counterparty, h, description="x", **extra):
    return Transaction(
        account_id=account.id, date=date(2026, 5, day), amount=Decimal(amount),
        counterparty=counterparty, description=description, import_hash=h, **extra,
    )


def test_plan_splits_moves_from_duplicates(db):
    _, source, target = _setup(db)
    db.add_all([
        _tx(source, 1, "-10.00", "Albert Heijn", "csv-1", "AH CSV"),
        _tx(source, 2, "-5.00", "Shell", "csv-2", "Shell CSV"),
        _tx(source, 3, "-7.00", "Alleen CSV", "csv-3", "alleen"),
        _tx(target, 1, "-10.00", "ALBERT HEIJN", "api-1", "AH API"),
        _tx(target, 2, "-5.00", "Andere naam", "api-2", "Shell CSV"),
    ])
    db.flush()
    plan = plan_merge(db, source, target)
    assert len(plan.duplicates) == 2
    assert [t.import_hash for t in plan.move] == ["csv-3"]


def test_same_date_and_amount_with_nothing_else_alike_is_moved(db):
    _, source, target = _setup(db)
    db.add_all([
        _tx(source, 1, "-10.00", "Bakker", "csv-1", "brood"),
        _tx(target, 1, "-10.00", "Slager", "api-1", "vlees"),
    ])
    db.flush()
    plan = plan_merge(db, source, target)
    assert len(plan.move) == 1 and not plan.duplicates


def test_matching_is_one_to_one(db):
    _, source, target = _setup(db)
    db.add_all([
        _tx(source, 1, "-3.00", "Koffie", "csv-1"),
        _tx(source, 1, "-3.00", "Koffie", "csv-2"),
        _tx(target, 1, "-3.00", "Koffie", "api-1"),
    ])
    db.flush()
    plan = plan_merge(db, source, target)
    assert len(plan.duplicates) == 1 and len(plan.move) == 1


def test_merge_keeps_user_work_and_deletes_source(db):
    user, source, target = _setup(db)
    cat = Category(user_id=user.id, name="Boodschappen")
    db.add(cat)
    db.flush()
    src_dup = _tx(source, 1, "-10.00", "Albert Heijn", "csv-1", is_reviewed=1, category_id=cat.id)
    moved = _tx(source, 3, "-7.00", "Alleen CSV", "csv-3")
    tgt_dup = _tx(target, 1, "-10.00", "Albert Heijn", "api-1")
    db.add_all([src_dup, moved, tgt_dup])
    db.add(ImportBatch(user_id=user.id, account_id=source.id, source="csv:abn", total_count=2))
    db.flush()
    child = _tx(source, 1, "-4.00", "Split", "csv-child", parent_id=src_dup.id)
    db.add(child)
    db.flush()
    source_id, target_id, child_id, tgt_id = source.id, target.id, child.id, tgt_dup.id

    result = merge_accounts(db, source, target)
    db.commit()

    assert (result.moved, result.merged_duplicates) == (2, 1)  # one move + the split child
    assert db.query(Account).filter_by(id=source_id).first() is None
    kept = db.get(Transaction, tgt_id)
    assert kept.category_id == cat.id and kept.is_reviewed == 1
    assert db.get(Transaction, child_id).parent_id == tgt_id
    assert db.get(Transaction, child_id).account_id == target_id
    assert db.query(Transaction).filter_by(account_id=target_id).count() == 3
    assert db.query(ImportBatch).one().account_id == target_id


def test_merge_rejects_other_users_accounts(db):
    _, source, _ = _setup(db)
    other = User(username="someone-else", password_hash="x")
    db.add(other)
    db.flush()
    foreign = Account(user_id=other.id, name="Vreemd", bank="abn_amro")
    db.add(foreign)
    db.flush()
    with pytest.raises(ValueError):
        merge_accounts(db, source, foreign)


def test_preview_does_not_change_data_and_post_merges(db):
    user, source, target = _setup(db)
    db.add_all([
        _tx(source, 1, "-10.00", "Albert Heijn", "csv-1"),
        _tx(target, 1, "-10.00", "Albert Heijn", "api-1"),
    ])
    db.commit()
    source_id, target_id = source.id, target.id
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))

    preview = client.get(f"/accounts/{source_id}/merge?target_id={target_id}")
    assert preview.status_code == 200
    assert "<strong>1</strong> transacties bestaan al" in preview.text
    assert db.query(Transaction).count() == 2

    resp = client.post(f"/accounts/{source_id}/merge", data={"target_id": target_id})
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(Account).filter_by(id=source_id).first() is None
    assert db.query(Transaction).count() == 1


def test_other_users_cannot_merge_my_accounts(db):
    _, source, target = _setup(db)
    intruder = User(username="intruder", password_hash="x")
    db.add(intruder)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(intruder.id))
    client.post(f"/accounts/{source.id}/merge", data={"target_id": target.id})
    db.expire_all()
    assert db.query(Account).filter_by(id=source.id).first() is not None


def test_exact_hash_match_is_not_stolen_by_a_fuzzy_match(db):
    """Twee bronregels met dezelfde tegenpartij op één dag, één doelregel met de hash van de tweede.

    Zonder voorrang voor exacte hashes pakt de eerste bronregel de doelregel via de tegenpartij;
    de tweede wordt dan verplaatst en botst op de unieke (rekening, import_hash)-index.
    """
    _, source, target = _setup(db)
    db.add_all([
        _tx(source, 1, "-3.00", "Koffie", "csv-b", "omschrijving B"),
        _tx(source, 1, "-3.00", "Koffie", "csv-a", "omschrijving A"),
        _tx(target, 1, "-3.00", "Koffie", "csv-a", "omschrijving A"),
    ])
    db.flush()
    source_id = source.id

    result = merge_accounts(db, source, target)
    db.commit()

    assert (result.moved, result.merged_duplicates) == (1, 1)
    assert db.query(Transaction).count() == 2
    assert db.query(Account).filter_by(id=source_id).first() is None


def test_failed_merge_shows_an_error_and_keeps_data(db, monkeypatch):
    user, source, target = _setup(db)
    db.add(_tx(source, 1, "-10.00", "Albert Heijn", "csv-1"))
    db.commit()
    source_id, target_id = source.id, target.id

    def boom(*args, **kwargs):
        raise RuntimeError("kapot")

    monkeypatch.setattr("app.routers.accounts.merge_accounts", boom)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    resp = client.post(f"/accounts/{source_id}/merge", data={"target_id": target_id})
    assert resp.status_code == 200
    assert "niet gelukt" in resp.text
    db.expire_all()
    assert db.query(Account).filter_by(id=source_id).first() is not None
    assert db.query(Transaction).count() == 1


def test_same_hash_with_shifted_visible_date_is_a_duplicate_not_a_move(db):
    """Koppelen aan een terugkerende post kan de zichtbare datum verschuiven; de hash blijft."""
    _, source, target = _setup(db)
    db.add_all([
        _tx(source, 31, "-900.00", "Hypotheek", "same-hash", "termijn"),
        Transaction(account_id=target.id, date=date(2026, 6, 1), amount=Decimal("-900.00"),
                    counterparty="Hypotheek", description="termijn", import_hash="same-hash",
                    original_date=date(2026, 5, 31)),
    ])
    db.flush()
    result = merge_accounts(db, source, target)
    db.commit()
    assert (result.moved, result.merged_duplicates) == (0, 1)
    assert db.query(Transaction).count() == 1
