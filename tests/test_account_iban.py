"""IBAN van een rekening toevoegen of wijzigen."""
from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, User
from app.validation import clean_iban

VALID = "NL12ABNA0465543502"


def test_clean_iban_normalizes_and_checks_the_checksum():
    assert clean_iban("nl12 abna 0465 5435 02") == VALID
    assert clean_iban("") == "" and clean_iban(None) is None
    assert clean_iban("NL12ABNA0465543503") is None            # verkeerd controlecijfer
    assert clean_iban("NL12") is None and clean_iban("12ABNA0465543502") is None


def _world(db):
    user = User(username="ib", email="i@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ Betaal", bank="abn_amro")
    other = Account(user_id=user.id, name="Samen", bank="abn_amro", iban="NL45ABNA0503737143")
    db.add_all([gj, other])
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, gj, other, client


def test_iban_is_saved_normalized_and_blank_leaves_it_alone(db):
    user, gj, other, client = _world(db)
    client.post(f"/accounts/{gj.id}/update", data={"name": "GJ Betaal", "kind": "payment", "iban": "nl12 abna 0465 5435 02"})
    db.expire_all()
    assert db.get(Account, gj.id).iban == VALID
    client.post(f"/accounts/{gj.id}/update", data={"name": "GJ Betaal 2", "kind": "payment", "iban": ""})
    db.expire_all()
    assert db.get(Account, gj.id).iban == VALID and db.get(Account, gj.id).name == "GJ Betaal 2"


def test_invalid_or_used_iban_is_refused_with_a_message(db):
    user, gj, other, client = _world(db)
    res = client.post(f"/accounts/{gj.id}/update", data={"name": "GJ Betaal", "iban": "NL12ABNA0465543503"})
    assert "ongeldig" in res.text
    res = client.post(f"/accounts/{gj.id}/update", data={"name": "GJ Betaal", "iban": "NL45 ABNA 0503 7371 43"})
    assert "hoort al bij een andere rekening" in res.text
    db.expire_all()
    assert db.get(Account, gj.id).iban is None
