"""ACT-43b: routeconventie, instellingenpagina na een import en personen-beheer op één plek."""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Person, User
from app.ownership import get_owned_or_404, get_owned_transaction_or_404


def _user(db, name):
    user = User(username=name, password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    return user


def _client(user):
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


def test_get_owned_or_404_hides_other_users_objects(db):
    mine, theirs = _user(db, "mine"), _user(db, "theirs")
    account = Account(user_id=theirs.id, name="A", bank="x")
    db.add(account)
    db.commit()
    with pytest.raises(HTTPException) as other:
        get_owned_or_404(db, Account, account.id, mine.id)
    assert other.value.status_code == 404                           # niet 403: bestaan niet verraden
    with pytest.raises(HTTPException):
        get_owned_or_404(db, Account, 99999, mine.id)
    with pytest.raises(HTTPException):
        get_owned_or_404(db, Account, None, mine.id)
    assert get_owned_or_404(db, Account, account.id, theirs.id).id == account.id
    with pytest.raises(HTTPException):
        get_owned_transaction_or_404(db, 12345, mine.id)


def test_account_routes_answer_404_for_unknown_or_foreign_accounts(db):
    mine, theirs = _user(db, "mine2"), _user(db, "theirs2")
    foreign = Account(user_id=theirs.id, name="Vreemd", bank="x")
    db.add(foreign)
    db.commit()
    client = _client(mine)
    assert client.post(f"/accounts/{foreign.id}/update", data={"name": "Gekaapt"}).status_code == 404
    assert client.get(f"/accounts/{foreign.id}/merge").status_code == 404
    assert client.get("/accounts/99999/merge").status_code == 404
    db.expire_all()
    assert db.get(Account, foreign.id).name == "Vreemd"


def test_settings_page_keeps_the_start_page_block_after_an_import(db):
    user = _user(db, "importer")
    db.commit()
    payload = {"version": 1, "categories": [{"name": "Nieuw"}], "rules": [], "recurring": [], "budgets": []}
    page = _client(user).post("/settings/import/confirm", data={"raw_json": json.dumps(payload), "strategy": "overwrite"})
    assert page.status_code == 200 and "Import voltooid" in page.text
    assert 'name="start_page"' in page.text                       # ontbrak eerder na een import
    bad = _client(user).post("/settings/import/confirm", data={"raw_json": json.dumps({"version": 1,
              "recurring": [{"name": "x", "amount_expected": "geen-getal", "frequency": "monthly"}]}), "strategy": "overwrite"})
    assert 'name="start_page"' in bad.text


def test_all_settings_routes_live_in_the_settings_router():
    import pathlib
    assert '"/settings' not in pathlib.Path("app/routers/auth.py").read_text()
    from app.routers import settings

    paths = {route.path for route in settings.router.routes}
    assert {"/settings", "/settings/password", "/settings/email", "/settings/digest",
            "/settings/start-page", "/settings/delete-account", "/settings/import/confirm"} <= paths


def test_persons_are_managed_by_the_persons_router_only(db):
    user = _user(db, "persons")
    db.commit()
    client = _client(user)
    created = client.post("/persons", data={"name": "Partner", "redirect_to": "/portfolio"})
    assert created.status_code == 302 and created.headers["location"] == "/portfolio"
    evil = client.post("/persons", data={"name": "Kind", "redirect_to": "//evil.example"})
    assert evil.headers["location"] == "/persons"
    person_id = db.query(Person).filter_by(name="Partner").one().id
    deleted = client.post(f"/persons/{person_id}/delete", data={"redirect_to": "/portfolio"})
    assert deleted.headers["location"] == "/portfolio"
    assert client.post("/portfolio/persons", data={"name": "Oud"}).status_code in (404, 405)   # dubbele CRUD weg
