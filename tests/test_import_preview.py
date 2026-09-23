"""Import previews only count duplicates on the user's own target account (ACT-26)."""
import base64
import json
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

from app.auth import create_session_cookie
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, ImportBatch, Transaction, User
from app.parsers import bunq

IBAN = "NL01BUNQ1234567890"
BUNQ_HEADER = '"Date";"Amount";"Account";"Counterparty";"Name";"Description"\n'


def _bunq_row(day, amount, name):
    return f'"2026-09-{day:02d}";"{amount}";"{IBAN}";"NL02RABO9876543210";"{name}";"Betaling"\n'


# Five rows: "Herhaald" appears twice with identical content.
BUNQ_CSV = (BUNQ_HEADER + _bunq_row(1, "-1.00", "Andere gebruiker") + _bunq_row(2, "-2.00", "Andere rekening")
            + _bunq_row(3, "-3.00", "Herhaald") + _bunq_row(3, "-3.00", "Herhaald")
            + _bunq_row(4, "-4.00", "Al op doelrekening")).encode()
HASHES = {p.counterparty: p.import_hash for p in bunq.parse(BUNQ_CSV)[1]}

CUSTOM_CSV = b"Datum,Bedrag,Omschrijving\n2026-09-01,-1.00,Andere gebruiker\n2026-09-02,-2.00,Al op doelrekening\n"


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _client(user):
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


def _user(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.flush()
    return user


def _store(db, account, import_hash, description="Betaling"):
    db.add(Transaction(account_id=account.id, date=date(2026, 9, 1), amount=Decimal("-1.00"),
                       description=description, import_hash=import_hash))


def _preview_counts(response):
    assert response.status_code == 200
    rows = response.context["preview_rows"]
    flags = [row["is_duplicate"] for row in rows]
    return response.context["new_count"], response.context["dup_count"], flags


def test_bank_preview_ignores_other_users_and_accounts_and_matches_confirm(db):
    user, other = _user(db, "preview-user"), _user(db, "preview-other")
    target = Account(user_id=user.id, name="Doel", bank="bunq", iban=IBAN)
    own_other = Account(user_id=user.id, name="Ander", bank="bunq", iban="NL99BUNQ0000000000")
    foreign = Account(user_id=other.id, name="Vreemd", bank="bunq", iban=IBAN)
    db.add_all([target, own_other, foreign])
    db.flush()
    _store(db, foreign, HASHES["Andere gebruiker"])
    _store(db, own_other, HASHES["Andere rekening"])
    _store(db, target, HASHES["Al op doelrekening"])
    db.commit()
    client = _client(user)

    preview = client.post("/import", data={"bank": "bunq", "account_name": ""},
                          files={"file": ("bunq.csv", BUNQ_CSV, "text/csv")})

    new, dup, flags = _preview_counts(preview)
    assert (new, dup) == (3, 2)
    assert flags == [False, False, False, True, True]

    confirm = client.post("/import/confirm", data={
        "tx_data": preview.context["tx_data"], "bank": "bunq",
        "account_iban": IBAN, "account_name": "Doel",
    })
    assert confirm.status_code == 200
    batch = db.query(ImportBatch).filter_by(user_id=user.id).one()
    assert (batch.account_id, batch.imported_count, batch.skipped_count) == (target.id, new, dup)


def test_bank_preview_for_new_account_only_flags_repeats_in_file(db):
    user, other = _user(db, "preview-new"), _user(db, "preview-owner")
    foreign = Account(user_id=other.id, name="Vreemd", bank="bunq", iban=IBAN)
    db.add(foreign)
    db.flush()
    for import_hash in HASHES.values():
        _store(db, foreign, import_hash)
    db.commit()

    preview = _client(user).post("/import", data={"bank": "bunq", "account_name": ""},
                                 files={"file": ("bunq.csv", BUNQ_CSV, "text/csv")})

    assert _preview_counts(preview)[:2] == (4, 1)


def test_custom_csv_preview_only_counts_own_custom_account(db):
    user, other = _user(db, "custom-user"), _user(db, "custom-other")
    target = Account(user_id=user.id, name="Eigen CSV", bank="custom", iban=None)
    foreign = Account(user_id=other.id, name="Vreemde CSV", bank="custom", iban=None)
    db.add_all([target, foreign])
    db.commit()
    client = _client(user)
    form = {
        "csv_data": base64.b64encode(CUSTOM_CSV).decode(), "account_name": "Eigen CSV",
        "col_date": "Datum", "col_amount": "Bedrag", "col_description": "Omschrijving",
    }
    first = client.post("/import/map", data=form)
    assert _preview_counts(first)[:2] == (2, 0)

    # Store one row on the other user's and one on the user's own custom account.
    hashes = [row["import_hash"] for row in json.loads(base64.b64decode(first.context["tx_data"]))]
    _store(db, foreign, hashes[0])
    _store(db, target, hashes[1])
    db.commit()

    second = client.post("/import/map", data=form)
    assert _preview_counts(second) == (1, 1, [False, True])
