"""Rekeningen samenvoegen: preview, dubbelen herkennen en gegevens behouden."""
from datetime import date
from decimal import Decimal

import pytest


from fastapi.testclient import TestClient

from app.account_merge import merge_accounts, plan_merge
from app.auth import create_session_cookie
from app.main import app
from app.models import Account, Category, ImportBatch, Transaction, User


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


def test_account_can_be_renamed_and_typed_by_owner_only(db):
    user, source, _ = _setup(db)
    intruder = User(username="renamer", password_hash="x")
    db.add(intruder)
    db.commit()
    account_id = source.id

    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    resp = client.post(f"/accounts/{account_id}/update", data={"name": "  Samen   Betaal  ", "kind": "savings"})
    assert resp.status_code == 302
    db.expire_all()
    renamed = db.get(Account, account_id)
    assert renamed.name == "Samen Betaal" and renamed.kind == "savings"

    client.post(f"/accounts/{account_id}/update", data={"name": "   ", "kind": "payment"})
    db.expire_all()
    assert db.get(Account, account_id).name == "Samen Betaal"  # leeg wordt genegeerd

    other = TestClient(app, follow_redirects=False)
    other.cookies.set("session", create_session_cookie(intruder.id))
    other.post(f"/accounts/{account_id}/update", data={"name": "Gekaapt", "kind": "payment"})
    db.expire_all()
    assert db.get(Account, account_id).name == "Samen Betaal"



def test_same_named_categories_are_folded_instead_of_crashing(db):
    """A12: uq_user_account_category liet het samenvoegen crashen bij gelijknamige categorieën."""
    from app.models import Budget, Rule

    user, source, target = _setup(db)
    src_cat = Category(user_id=user.id, account_id=source.id, name="Boodschappen")
    tgt_cat = Category(user_id=user.id, account_id=target.id, name="Boodschappen")
    only_src = Category(user_id=user.id, account_id=source.id, name="Alleen bron")
    child = Category(user_id=user.id, account_id=source.id, name="Groente")
    db.add_all([src_cat, tgt_cat, only_src])
    db.flush()
    child.parent_id = src_cat.id
    db.add(child)
    db.add_all([
        _tx(source, 1, "-10.00", "AH", "csv-1", category_id=src_cat.id),
        Budget(user_id=user.id, category_id=src_cat.id, year=2026, month=5, amount=Decimal("100")),
        Budget(user_id=user.id, category_id=tgt_cat.id, year=2026, month=5, amount=Decimal("200")),
        Budget(user_id=user.id, category_id=src_cat.id, year=2026, month=6, amount=Decimal("300")),
        Rule(user_id=user.id, name="ah", match_field="counterparty", match_type="contains",
             match_value="AH", assign_category_id=src_cat.id),
    ])
    db.flush()
    plan = plan_merge(db, source, target)
    assert [(c.name) for c, _ in plan.category_merges] == ["Boodschappen"]
    src_cat_id, tgt_cat_id, only_id, child_id = src_cat.id, tgt_cat.id, only_src.id, child.id

    result = merge_accounts(db, source, target)
    db.commit()

    assert result.merged_categories == 1
    assert db.get(Category, src_cat_id) is None
    assert db.query(Transaction).one().category_id == tgt_cat_id
    assert db.get(Category, only_id).account_id == target.id      # niet-conflicterend: verhuisd
    assert db.get(Category, child_id).parent_id == tgt_cat_id      # kind hangt nu onder de blijvende
    budgets = {(b.month): (b.category_id, b.amount) for b in db.query(Budget)}
    assert budgets == {5: (tgt_cat_id, Decimal("200.00")), 6: (tgt_cat_id, Decimal("300.00"))}
    assert db.query(Rule).one().assign_category_id == tgt_cat_id
