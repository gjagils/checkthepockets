"""ACT-38b (review B12): de inbox-badge-middleware doet alleen werk voor ingelogde paginaverzoeken."""



from fastapi.testclient import TestClient

from app import clock
from app.auth import create_session_cookie, hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Account, Transaction, User


def _user_with_inbox_item():
    db = SessionLocal()
    user = User(username="inbox-user", password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="A", bank="abn_amro")
    db.add(account)
    db.flush()
    db.add(Transaction(account_id=account.id, date=clock.today_nl(), amount=-5, description="x",
                       import_hash="h1", is_reviewed=0))
    db.commit()
    uid = user.id
    db.close()
    return uid


def test_badge_shows_for_a_logged_in_page_load():
    uid = _user_with_inbox_item()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(uid))
    page = client.get("/dashboard")
    assert page.status_code == 200 and "nav-inbox-badge" in page.text


def test_no_badge_query_for_health_static_anonymous_or_mutations(monkeypatch):
    import app.routers.inbox as inbox

    calls = []
    monkeypatch.setattr(inbox, "inbox_count", lambda db, uid: calls.append(uid) or 0)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/login").status_code == 200                     # anoniem: geen cookie
    client.cookies.set("session", "x")
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200
    client.post("/logout")                                              # POST: geen badge nodig
    assert calls == []

    uid = _user_with_inbox_item()
    client.cookies.set("session", create_session_cookie(uid))
    client.get("/dashboard")
    assert calls == [uid]                                               # wel bij een echte paginalading


def test_revoked_cookie_gets_no_badge():
    uid = _user_with_inbox_item()
    cookie = create_session_cookie(uid, 0)
    db = SessionLocal()
    user = db.get(User, uid)
    user.session_version = 5                                           # sessies ingetrokken
    db.commit()
    db.close()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", cookie)
    page = client.get("/login")                                         # publiek, rendert zonder login
    assert "nav-inbox-badge" not in page.text
