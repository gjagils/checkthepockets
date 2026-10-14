"""ACT-32: met FIELD_ENCRYPTION_KEY aan (productie) mogen queries niet op versleutelde kolommen groeperen."""
from datetime import date
from decimal import Decimal

import pytest


from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Text, select, type_coerce

import app.crypto as crypto
from app.auth import create_session_cookie
from app.crypto import encrypt_existing_transactions
from app.main import app
from app.models import Account, Category, Transaction, User
from app.rules_engine import suggest_rules


@pytest.fixture
def encryption_on(monkeypatch):
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(crypto, "_encryption_configured", True)


def _world(db):
    user = User(username="enc-user", password_hash="x")
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Betaal", bank="abn_amro")
    db.add(account)
    db.flush()
    return user, account


def _tx(account, day, amount, counterparty, n, **extra):
    return Transaction(account_id=account.id, date=date(2026, 5, day), amount=Decimal(amount),
                       counterparty=counterparty, description="x", import_hash=f"h{n}", **extra)


def test_duplicates_page_finds_groups_with_encryption_on(db, encryption_on):
    user, account = _world(db)
    db.add_all([
        _tx(account, 1, "-10.00", "Albert Heijn", 1),
        _tx(account, 1, "-10.00", "ALBERT HEIJN ", 2),   # zelfde boeking, andere schrijfwijze
        _tx(account, 1, "-10.00", "Shell", 3),           # zelfde datum+bedrag, andere tegenpartij
        _tx(account, 2, "-5.00", "Bakker", 4),
    ])
    db.commit()
    raw = db.execute(select(type_coerce(Transaction.counterparty, Text))).scalars().all()
    assert all(value.startswith("gAAAA") for value in raw)      # echt versleuteld opgeslagen

    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    page = client.get("/transactions/duplicates")
    assert page.status_code == 200
    assert "Albert Heijn" in page.text or "ALBERT HEIJN" in page.text
    assert "Bakker" not in page.text and "Shell" not in page.text


def test_suggest_rules_groups_equal_counterparties_with_encryption_on(db, encryption_on):
    user, account = _world(db)
    cat = Category(user_id=user.id, name="Boodschappen")
    db.add(cat)
    db.flush()
    db.add_all([_tx(account, d, "-3.00", "Jumbo", d, category_id=cat.id) for d in (1, 2, 3)]
               + [_tx(account, 4, "-3.00", "Eenmalig", 9, category_id=cat.id)])
    db.commit()
    suggestions = suggest_rules(db, user.id)
    assert [s["counterparty"] for s in suggestions] == ["Jumbo"]


def test_encrypt_existing_transactions_really_encrypts_plaintext_rows(db, monkeypatch):
    user, account = _world(db)
    db.add(_tx(account, 1, "-10.00", "Albert Heijn", 1, counterparty_iban="NL01BANK0000000001"))
    db.commit()
    raw_before = db.execute(select(type_coerce(Transaction.counterparty, Text))).scalar()
    assert raw_before == "Albert Heijn"                         # sleutel was uit: platte tekst

    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(crypto, "_encryption_configured", True)
    assert encrypt_existing_transactions(db) == 1
    db.expire_all()
    raw_after = db.execute(select(type_coerce(Transaction.counterparty, Text))).scalar()
    assert raw_after.startswith("gAAAA")
    assert db.query(Transaction).one().counterparty == "Albert Heijn"   # leest weer terug
    assert encrypt_existing_transactions(db) == 0                       # idempotent


def test_reading_ciphertext_with_invalid_configured_key_refuses(monkeypatch):
    monkeypatch.setattr(crypto, "_encryption_configured", True)
    monkeypatch.setattr(crypto, "_fernet", None)
    with pytest.raises(RuntimeError, match="refusing to return ciphertext"):
        crypto.EncryptedText().process_result_value("gAAAA-whatever", None)
