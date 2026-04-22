"""Route-tests voor de knowledge base (LIN-38 part 1)."""
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.info_loader import get_category, load_article, load_categories, list_articles
from app.main import app
from app.models import User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def user():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        u = User(username="alice", email="alice@example.com", password_hash=hash_password("pw"))
        db.add(u)
        db.commit()
        db.refresh(u)
        yield u
    finally:
        db.close()


def _login(user_id: int) -> TestClient:
    c = TestClient(app)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ── Loader -----------------------------------------------------------------

def test_loader_reads_manifest():
    cats = load_categories()
    assert any(c.slug == "getting-started" for c in cats)
    cat = get_category("getting-started")
    assert cat is not None
    assert cat.title("nl") == "Aan de slag"
    assert cat.title("en") == "Getting started"


def test_loader_returns_none_for_unknown_article():
    assert load_article("getting-started", "does-not-exist", "nl") is None


def test_loader_renders_article_html():
    art = load_article("getting-started", "welcome", "nl")
    assert art is not None
    assert art.meta.lang == "nl"
    # `toc`-extensie geeft h1 een id; we willen alleen bevestigen dat markdown
    # daadwerkelijk naar HTML is gerendeerd.
    assert "<h1" in art.html
    assert "Welkom bij Check Your Pockets" in art.html
    assert "<p>" in art.html


def test_loader_lists_articles_alphabetically():
    arts = list_articles("getting-started", "nl")
    assert len(arts) >= 1
    assert any(a.slug == "welcome" for a in arts)


# ── Routes -----------------------------------------------------------------

def test_info_index_shows_categories(user):
    client = _login(user.id)
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.text
    assert "Help" in body
    assert "Aan de slag" in body  # Default language = nl


def test_info_index_honours_lang_query_param(user):
    client = _login(user.id)
    resp = client.get("/info?lang=en")
    assert resp.status_code == 200
    assert "Getting started" in resp.text
    assert "Aan de slag" not in resp.text


def test_info_category_lists_articles(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started")
    assert resp.status_code == 200
    assert "Welkom bij Check Your Pockets" in resp.text


def test_info_unknown_category_redirects_home(user):
    client = _login(user.id)
    resp = client.get("/info/no-such-category", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/info"


def test_info_article_renders_markdown(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started/welcome")
    assert resp.status_code == 200
    body = resp.text
    # h1 uit markdown-body is gerenderd (toc-extensie voegt id toe)
    assert "Welkom bij Check Your Pockets" in body
    assert "<h1" in body
    # Breadcrumbs aanwezig
    assert "info-breadcrumbs" in body


def test_info_article_english_variant(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started/welcome?lang=en")
    assert resp.status_code == 200
    assert "Welcome to Check Your Pockets" in resp.text


def test_info_unknown_article_redirects_to_category(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started/no-such-article", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/info/getting-started"


def test_info_help_link_in_topnav(user):
    client = _login(user.id)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert 'href="/info"' in resp.text


def test_info_requires_login():
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/info")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
