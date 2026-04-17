"""Tests voor Person-model, /persons CRUD en Account-eigenaarschap (GJA-14)."""
import os
import tempfile

import pytest

# Use an on-disk sqlite DB so the app + test share the same store.
_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Account, Person, PortfolioAsset, PortfolioHolding, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(PortfolioHolding).delete()
        db.query(PortfolioAsset).delete()
        # Verbreek M2M-koppelingen voor we personen verwijderen
        for acc in db.query(Account).all():
            acc.owners = []
        db.commit()
        db.query(Person).delete()
        db.query(Account).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice"):
    u = User(username=username, email=f"{username}@x.nl", password_hash=hash_password("pw"))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user, name="Main"):
    a = Account(user_id=user.id, name=name, bank="custom", iban=f"NL{user.id:02d}ACC{name[:4]:0>4}")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _login_client(user_id: int) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


# ── Person CRUD ────────────────────────────────────────────────────────────

def test_create_and_list_persons(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)

    resp = client.post("/persons", data={"name": "Partner"}, follow_redirects=False)
    assert resp.status_code == 302

    persons = db_session.query(Person).filter(Person.user_id == alice.id).all()
    assert len(persons) == 1
    assert persons[0].name == "Partner"
    assert persons[0].sort_order == 0

    # Tweede persoon krijgt sort_order 1
    client.post("/persons", data={"name": "Ikzelf"}, follow_redirects=False)
    db_session.expire_all()
    persons = (
        db_session.query(Person)
        .filter(Person.user_id == alice.id)
        .order_by(Person.sort_order)
        .all()
    )
    assert [p.name for p in persons] == ["Partner", "Ikzelf"]
    assert [p.sort_order for p in persons] == [0, 1]

    body = client.get("/persons").text
    assert "Partner" in body
    assert "Ikzelf" in body


def test_rename_and_delete_person(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)
    client.post("/persons", data={"name": "Oud"})
    pid = db_session.query(Person).filter(Person.user_id == alice.id).first().id

    client.post(f"/persons/{pid}/rename", data={"name": "Nieuw"})
    db_session.expire_all()
    assert db_session.query(Person).filter(Person.id == pid).one().name == "Nieuw"

    client.post(f"/persons/{pid}/delete")
    db_session.expire_all()
    assert db_session.query(Person).filter(Person.id == pid).first() is None


def test_move_person_up_and_down(db_session):
    alice = _make_user(db_session)
    client = _login_client(alice.id)
    for name in ["A", "B", "C"]:
        client.post("/persons", data={"name": name})

    persons = (
        db_session.query(Person)
        .filter(Person.user_id == alice.id)
        .order_by(Person.sort_order)
        .all()
    )
    second = persons[1]  # "B"

    client.post(f"/persons/{second.id}/move", data={"direction": "up"})
    db_session.expire_all()
    ordered = [
        p.name for p in db_session.query(Person)
        .filter(Person.user_id == alice.id)
        .order_by(Person.sort_order).all()
    ]
    assert ordered == ["B", "A", "C"]

    client.post(f"/persons/{second.id}/move", data={"direction": "down"})
    db_session.expire_all()
    ordered = [
        p.name for p in db_session.query(Person)
        .filter(Person.user_id == alice.id)
        .order_by(Person.sort_order).all()
    ]
    assert ordered == ["A", "B", "C"]


def test_cannot_manage_other_users_persons(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    bob_person = Person(user_id=bob.id, name="Bob's kid", sort_order=0)
    db_session.add(bob_person)
    db_session.commit()
    db_session.refresh(bob_person)

    client = _login_client(alice.id)
    client.post(f"/persons/{bob_person.id}/rename", data={"name": "Hacked"})
    client.post(f"/persons/{bob_person.id}/delete")

    db_session.expire_all()
    refreshed = db_session.query(Person).filter(Person.id == bob_person.id).one()
    assert refreshed.name == "Bob's kid"  # niet gewijzigd, niet verwijderd


# ── Account ↔ Person M2M ───────────────────────────────────────────────────

def test_assign_and_clear_account_owners(db_session):
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice, "Spaar")
    p1 = Person(user_id=alice.id, name="Partner", sort_order=0)
    p2 = Person(user_id=alice.id, name="Ikzelf", sort_order=1)
    db_session.add_all([p1, p2])
    db_session.commit()
    db_session.refresh(p1)
    db_session.refresh(p2)

    p1_id, p2_id, acc_id = p1.id, p2.id, acc.id
    client = _login_client(alice.id)
    # Zet beide als eigenaar ("Samen") — httpx serialiseert list-values als meerdere velden
    client.post(f"/accounts/{acc_id}/owners", data={"owner_id": [str(p1_id), str(p2_id)]})
    db_session.expire_all()
    refreshed = db_session.query(Account).filter(Account.id == acc_id).one()
    assert {o.id for o in refreshed.owners} == {p1_id, p2_id}

    # Zet alleen p1
    client.post(f"/accounts/{acc_id}/owners", data={"owner_id": str(p1_id)})
    db_session.expire_all()
    refreshed = db_session.query(Account).filter(Account.id == acc_id).one()
    assert [o.id for o in refreshed.owners] == [p1_id]

    # Wis alle eigenaren
    client.post(f"/accounts/{acc_id}/owners", data={})
    db_session.expire_all()
    refreshed = db_session.query(Account).filter(Account.id == acc_id).one()
    assert refreshed.owners == []


def test_cannot_assign_other_users_person_as_owner(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    acc = _make_account(db_session, alice, "Spaar")
    bob_person = Person(user_id=bob.id, name="Bob", sort_order=0)
    db_session.add(bob_person)
    db_session.commit()
    db_session.refresh(bob_person)

    client = _login_client(alice.id)
    client.post(f"/accounts/{acc.id}/owners", data={"owner_id": str(bob_person.id)})
    db_session.expire_all()
    refreshed = db_session.query(Account).filter(Account.id == acc.id).one()
    assert refreshed.owners == []


# ── Persons-pagina redirect ────────────────────────────────────────────────

def test_persons_redirects_when_logged_out(db_session):
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/persons")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
