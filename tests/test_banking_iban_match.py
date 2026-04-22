"""Tests voor GJA-39 fixes: IBAN-normalisatie en orphan-detectie.

Dekken de helpers die in de banking-sync en de admin orphan-detector worden
gebruikt, plus een integration-test voor de admin-route zelf.
"""
import datetime
import os
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, Transaction, User
from app.routers.admin import _iban_bank_hint
from app.routers.banking import _normalize_iban


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        # Clean
        db.query(Transaction).delete()
        db.query(Account).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


# ── _normalize_iban ────────────────────────────────────────────────────

def test_normalize_strips_spaces():
    assert _normalize_iban("NL81 BUNQ 2088 6190 97") == "NL81BUNQ2088619097"


def test_normalize_uppercases():
    assert _normalize_iban("nl81bunq2088619097") == "NL81BUNQ2088619097"


def test_normalize_strips_tabs_and_newlines():
    assert _normalize_iban("  NL81\tBUNQ\n2088  6190 97 ") == "NL81BUNQ2088619097"


def test_normalize_none_returns_none():
    assert _normalize_iban(None) is None


def test_normalize_empty_string_returns_none():
    assert _normalize_iban("") is None
    assert _normalize_iban("   ") is None


def test_normalize_leaves_clean_iban_unchanged():
    iban = "NL91ABNA0417164300"
    assert _normalize_iban(iban) == iban


# ── _iban_bank_hint ────────────────────────────────────────────────────

def test_iban_bank_hint_bunq():
    assert _iban_bank_hint("NL81BUNQ2088619097") == "bunq"
    assert _iban_bank_hint("NL81 BUNQ 2088 6190 97") == "bunq"


def test_iban_bank_hint_abn():
    assert _iban_bank_hint("NL91ABNA0417164300") == "abn_amro"


def test_iban_bank_hint_ing():
    assert _iban_bank_hint("NL11INGB0001234567") == "ing"


def test_iban_bank_hint_rabo():
    assert _iban_bank_hint("NL44RABO0123456789") == "rabo"


def test_iban_bank_hint_unknown_bank():
    # Onbekende BIC-prefix → None (we raden niet)
    assert _iban_bank_hint("NL99XYZA0000000000") is None


def test_iban_bank_hint_non_nl_returns_none():
    assert _iban_bank_hint("DE89370400440532013000") is None


def test_iban_bank_hint_none_or_empty():
    assert _iban_bank_hint(None) is None
    assert _iban_bank_hint("") is None


# ── Admin orphan-detector integratie ───────────────────────────────────

def _make_user(db, admin=True):
    u = User(
        username="admin",
        email="admin@x.nl",
        password_hash=hash_password("pw"),
        is_admin=1 if admin else 0,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user, name, bank, iban=None):
    acc = Account(user_id=user.id, name=name, bank=bank, iban=iban)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _make_tx(
    db, account, date, amount, description="", counterparty="", counterparty_iban=None,
):
    # Unieke hash per test om constraint-issues te voorkomen
    import hashlib
    raw = f"{account.id}-{date}-{amount}-{description}-{counterparty}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    tx = Transaction(
        account_id=account.id,
        date=date,
        amount=Decimal(str(amount)),
        currency="EUR",
        description=description,
        counterparty=counterparty,
        counterparty_iban=counterparty_iban,
        import_hash=h,
        is_excluded=0,
        is_projected=0,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _login_client(user_id):
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


def test_orphan_detects_bunq_tx_on_abn_via_iban_hint(db_session):
    """Klassiek scenario: bunq-Payday (tegenpartij-IBAN = bunq) staat op ABN,
    gebruiker heeft ook een bunq-rekening → moet als verdacht getoond worden."""
    admin = _make_user(db_session)
    abn = _make_account(db_session, admin, "ABN Samen Betaal", "abn_amro", "NL91ABNA0417164300")
    bunq = _make_account(db_session, admin, "Bunq Samen spaar", "bunq", "NL81BUNQ2088619097")
    tx = _make_tx(
        db_session, abn,
        datetime.date(2026, 4, 19),
        Decimal("4.03"),
        description="bunq Payday 2026-04-19 EUR",
        counterparty_iban="NL81BUNQ2088619097",  # bunq-IBAN als tegenpartij
    )

    client = _login_client(admin.id)
    r = client.get("/admin/orphan-transactions")
    assert r.status_code == 200
    body = r.text
    assert "bunq Payday" in body
    # Moet voorstellen om naar Bunq Samen spaar te verplaatsen
    assert "Bunq Samen spaar" in body
    # Reden-tekst moet expliciet zijn
    assert "BUNQ" in body and "ABN_AMRO" in body


def test_orphan_detects_via_text_hint_without_iban(db_session):
    """Als de tegenpartij-IBAN ontbreekt maar de omschrijving 'bunq' bevat,
    detecteer via tekst-hint."""
    admin = _make_user(db_session)
    abn = _make_account(db_session, admin, "ABN", "abn_amro", "NL91ABNA0417164300")
    _make_account(db_session, admin, "Bunq spaar", "bunq", "NL81BUNQ2088619097")
    _make_tx(
        db_session, abn,
        datetime.date(2026, 4, 19),
        Decimal("4.03"),
        description="bunq Payday 2026-04-19 EUR",
        counterparty_iban=None,
    )

    client = _login_client(admin.id)
    r = client.get("/admin/orphan-transactions")
    assert r.status_code == 200
    assert "bunq Payday" in r.text


def test_orphan_ignores_tx_without_matching_other_bank(db_session):
    """Als de gebruiker GEEN bunq-rekening heeft, is een 'bunq Payday' op ABN
    gewoon een betaling aan bunq als externe partij — geen orphan."""
    admin = _make_user(db_session)
    abn = _make_account(db_session, admin, "ABN", "abn_amro", "NL91ABNA0417164300")
    # GEEN bunq-account
    _make_tx(
        db_session, abn,
        datetime.date(2026, 4, 19),
        Decimal("4.03"),
        description="bunq Payday",
        counterparty_iban="NL81BUNQ2088619097",
    )

    client = _login_client(admin.id)
    r = client.get("/admin/orphan-transactions")
    assert r.status_code == 200
    # Leeg resultaat → de alert/tabel met de tx mag er niet staan
    assert "Geen verdachte transacties gevonden" in r.text


def test_orphan_ignores_clean_tx_same_bank(db_session):
    """Normale ABN-tx op ABN-rekening: geen flag."""
    admin = _make_user(db_session)
    abn = _make_account(db_session, admin, "ABN", "abn_amro", "NL91ABNA0417164300")
    _make_account(db_session, admin, "Bunq", "bunq", "NL81BUNQ2088619097")
    _make_tx(
        db_session, abn,
        datetime.date(2026, 4, 19),
        Decimal("-10"),
        description="Albert Heijn",
        counterparty="AH Rijen",
        counterparty_iban="NL91ABNA9999999999",
    )
    client = _login_client(admin.id)
    r = client.get("/admin/orphan-transactions")
    assert r.status_code == 200
    assert "Geen verdachte transacties gevonden" in r.text


def test_orphan_requires_admin(db_session):
    """Non-admin krijgt 403."""
    u = _make_user(db_session, admin=False)
    client = _login_client(u.id)
    r = client.get("/admin/orphan-transactions")
    assert r.status_code == 403
