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


@pytest.fixture
def admin_user():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        u = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("pw"),
            is_admin=1,
        )
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


# ── Part 2: cookie + fallback + switcher -----------------------------------

def test_info_query_sets_lang_cookie(user):
    client = _login(user.id)
    resp = client.get("/info?lang=en", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.cookies.get("info_lang") == "en"


def test_info_cookie_is_used_when_no_query(user):
    client = _login(user.id)
    # Set cookie via een expliciete request
    client.get("/info?lang=en")
    # Zonder query-param → cookie bepaalt de taal
    resp = client.get("/info")
    assert resp.status_code == 200
    assert "Getting started" in resp.text
    assert "Aan de slag" not in resp.text


def test_info_query_overrides_cookie(user):
    client = _login(user.id)
    client.get("/info?lang=en")  # zet cookie op en
    resp = client.get("/info?lang=nl")
    assert resp.status_code == 200
    assert "Aan de slag" in resp.text
    # Cookie is nu geüpdatet naar nl
    assert resp.cookies.get("info_lang") == "nl"


def test_info_invalid_cookie_falls_back_to_default(user):
    client = _login(user.id)
    client.cookies.set("info_lang", "fr")
    resp = client.get("/info")
    assert resp.status_code == 200
    # Default = nl
    assert "Aan de slag" in resp.text


def test_info_fallback_banner_when_translation_missing(user):
    """NL-only artikel opgevraagd met ?lang=en → fallback-banner + NL content."""
    client = _login(user.id)
    resp = client.get("/info/getting-started/first-import?lang=en")
    assert resp.status_code == 200
    body = resp.text
    assert "info-fallback-banner" in body
    assert "not yet available in English" in body
    # De NL-content is zichtbaar
    assert "Je eerste CSV-import" in body


def test_info_no_fallback_banner_when_translation_exists(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started/welcome?lang=en")
    assert resp.status_code == 200
    body = resp.text
    assert "info-fallback-banner" not in body


def test_info_lang_switcher_renders(user):
    client = _login(user.id)
    resp = client.get("/info?lang=nl")
    assert resp.status_code == 200
    body = resp.text
    assert "info-lang-switcher" in body
    # NL is actief, EN niet
    assert 'href="/info?lang=nl"' in body
    assert 'href="/info?lang=en"' in body


def test_info_lang_switcher_preserves_current_path(user):
    client = _login(user.id)
    resp = client.get("/info/getting-started/welcome")
    body = resp.text
    assert 'href="/info/getting-started/welcome?lang=nl"' in body
    assert 'href="/info/getting-started/welcome?lang=en"' in body


# ── Part 3: admin-only filtering ------------------------------------------

def test_admin_category_hidden_for_non_admin(user):
    client = _login(user.id)
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.text
    # Admin-categorie mag niet in de grid verschijnen (Jinja escapet & → &amp;)
    assert "Admin &amp; onderhoud" not in body
    assert "/info/admin" not in body


def test_admin_category_visible_for_admin(admin_user):
    client = _login(admin_user.id)
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.text
    assert "Admin &amp; onderhoud" in body
    assert 'href="/info/admin"' in body


def test_non_admin_gets_redirected_from_admin_category(user):
    client = _login(user.id)
    resp = client.get("/info/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/info"


def test_non_admin_gets_redirected_from_admin_article(user):
    client = _login(user.id)
    resp = client.get("/info/admin/backup-restore", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/info"


def test_admin_can_read_admin_category(admin_user):
    client = _login(admin_user.id)
    resp = client.get("/info/admin")
    assert resp.status_code == 200
    assert "Backup en restore" in resp.text


def test_admin_can_read_admin_article(admin_user):
    client = _login(admin_user.id)
    resp = client.get("/info/admin/backup-restore")
    assert resp.status_code == 200
    body = resp.text
    assert "Backup en restore" in body
    # De pg_dump-instructie uit de issue moet er in staan
    assert "pg_dump" in body
    assert "ctp-backup-" in body


def test_admin_article_english_variant(admin_user):
    client = _login(admin_user.id)
    resp = client.get("/info/admin/backup-restore?lang=en")
    assert resp.status_code == 200
    body = resp.text
    assert "Backup and restore" in body
    assert "pg_dump" in body
    # Geen fallback-banner — EN bestaat
    assert "info-fallback-banner" not in body


def test_admin_sidebar_hides_admin_for_non_admin(user):
    """Sidebar van een niet-admin-pagina mag de admin-categorie niet tonen."""
    client = _login(user.id)
    resp = client.get("/info/getting-started")
    assert resp.status_code == 200
    body = resp.text
    assert "Admin &amp; onderhoud" not in body


# ── Part 4: content backfill per hoofdcategorie ---------------------------

@pytest.mark.parametrize("slug,title_nl", [
    ("transacties", "Transacties"),
    ("budgetten", "Budgetten"),
    ("portfolio", "Portfolio"),
    ("hypotheek", "Hypotheek"),
    ("rekeningen", "Rekeningen"),
])
def test_main_category_visible_on_index(user, slug, title_nl):
    client = _login(user.id)
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.text
    assert f'href="/info/{slug}"' in body
    assert title_nl in body


@pytest.mark.parametrize("cat,art", [
    ("transacties", "categoriseren"),
    ("budgetten", "sparen-snel-toevoegen"),
    ("portfolio", "assets-toevoegen"),
    ("hypotheek", "scenarios"),
    ("rekeningen", "bankkoppeling"),
])
def test_main_category_article_renders_nl_and_en(user, cat, art):
    client = _login(user.id)
    resp_nl = client.get(f"/info/{cat}/{art}")
    assert resp_nl.status_code == 200
    assert "info-fallback-banner" not in resp_nl.text

    resp_en = client.get(f"/info/{cat}/{art}?lang=en")
    assert resp_en.status_code == 200
    assert "info-fallback-banner" not in resp_en.text


# ── Part 5: client-side search ---------------------------------------------

def test_info_index_renders_search_input(user):
    client = _login(user.id)
    body = client.get("/info").text
    assert 'id="info-search-input"' in body
    assert "data-search-index" in body


def test_info_category_page_renders_search_and_indices(user):
    client = _login(user.id)
    body = client.get("/info/getting-started").text
    assert 'id="info-search-input"' in body
    # Article-list items hebben data-search-index met lowercase title
    assert 'data-search-index="welkom bij check your pockets' in body
    assert 'data-search-index="je eerste csv-import' in body


def test_info_article_page_renders_search_and_sidebar_indices(user):
    client = _login(user.id)
    body = client.get("/info/getting-started/welcome").text
    assert 'id="info-search-input"' in body
    # Sidebar-link heeft data-search-index
    assert 'data-search-index="welkom bij check your pockets' in body


def test_search_placeholder_respects_language(user):
    client = _login(user.id)
    resp_nl = client.get("/info?lang=nl")
    assert 'placeholder="Zoek artikelen' in resp_nl.text
    resp_en = client.get("/info?lang=en")
    assert 'placeholder="Search articles' in resp_en.text


def test_search_index_includes_both_languages_on_category_cards(user):
    """Zoeken op EN-title moet werken, ook als UI op NL staat."""
    client = _login(user.id)
    body = client.get("/info?lang=nl").text
    # Engelse titel van "Aan de slag" = "Getting started" — moet in index zitten
    assert "getting started" in body.lower()
    # Concreet: data-search-index bevat "getting started" naast "aan de slag"
    import re
    matches = re.findall(r'data-search-index="([^"]+)"', body)
    gs_idx = next(i for i in matches if "aan de slag" in i)
    assert "getting started" in gs_idx


def test_main_categories_are_ordered_below_getting_started(user):
    """Categorieën moeten in manifest-volgorde verschijnen in de grid.

    De grid staat tussen `info-category-grid` en het eerstvolgende `</div>`;
    we zoeken alleen daarbinnen zodat de top-nav links niet in de weg zitten.
    """
    client = _login(user.id)
    body = client.get("/info").text
    start = body.index("info-category-grid")
    grid = body[start:]
    idx_gs = grid.index("/info/getting-started")
    idx_tx = grid.index("/info/transacties")
    idx_bg = grid.index("/info/budgetten")
    idx_pf = grid.index("/info/portfolio")
    idx_hy = grid.index("/info/hypotheek")
    idx_rk = grid.index("/info/rekeningen")
    assert idx_gs < idx_tx < idx_bg < idx_pf < idx_hy < idx_rk
