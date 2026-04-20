"""Tests voor app.funda_parser (GJA-32).

We testen `parse_funda_html` pure met gemockte HTML — geen netwerk. De
endpoint-integratie testen we via TestClient + monkeypatch op `fetch_funda`.
"""
import os
import tempfile

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app import funda_parser
from app.auth import create_session_cookie, hash_password
from app.database import Base, SessionLocal, engine
from app.funda_parser import (
    FundaParseError,
    is_funda_url,
    parse_funda_html,
)
from app.main import app
from app.models import User


# ── URL helpers ──────────────────────────────────────────────────────────

def test_is_funda_url_true():
    assert is_funda_url("https://www.funda.nl/koop/amsterdam/huis-12345")
    assert is_funda_url("https://funda.nl/koop/utrecht/huis-9000")


def test_is_funda_url_trims_whitespace():
    assert is_funda_url("  https://www.funda.nl/koop/amsterdam/huis-12345  ")


def test_is_funda_url_false():
    assert not is_funda_url("")
    assert not is_funda_url("https://example.com/huis")
    assert not is_funda_url("not-a-url")
    assert not is_funda_url("ftp://www.funda.nl/koop/huis-1")


# ── parse_funda_html: JSON-LD ────────────────────────────────────────────

_JSONLD_HTML = """<!doctype html>
<html><head>
<title>Kerkstraat 12</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Residence",
  "name": "Kerkstraat 12",
  "offers": {"@type": "Offer", "price": 425000, "priceCurrency": "EUR"},
  "energyLabel": "B",
  "floorSize": {"@type": "QuantitativeValue", "value": 120, "unitCode": "MTK"},
  "yearBuilt": "1925"
}
</script>
</head><body></body></html>
"""


def test_parse_jsonld_basic():
    result = parse_funda_html(
        "https://www.funda.nl/koop/utrecht/huis-12345-kerkstraat-12/",
        _JSONLD_HTML,
    )
    assert result["offer"] == 425000
    assert result["energy_label"] == "B"
    assert result["name"] == "Kerkstraat 12, Utrecht"
    assert "Bouwjaar: 1925" in result["notes"]
    assert "Woonoppervlakte: 120" in result["notes"]


def test_parse_jsonld_price_in_price_spec():
    html = """<script type="application/ld+json">
{"@type": "Residence", "offers": {"priceSpecification": {"price": "500000"}}}
</script>"""
    result = parse_funda_html(
        "https://www.funda.nl/koop/amsterdam/huis-1-teststraat-1/",
        html,
    )
    assert result["offer"] == 500000


# ── parse_funda_html: Nuxt payload fallback ──────────────────────────────

_NUXT_HTML = """<!doctype html>
<html><head></head><body>
<script>
window.__NUXT__ = {"data": [{"asking_price": 389000, "energy_label": "C",
"year_built": 1978, "living_area": 95, "plot_area": 140}]};
</script>
</body></html>
"""


def test_parse_nuxt_fallback():
    result = parse_funda_html(
        "https://www.funda.nl/koop/rotterdam/huis-555-zuidplein-3/",
        _NUXT_HTML,
    )
    assert result["offer"] == 389000
    assert result["energy_label"] == "C"
    assert result["name"] == "Zuidplein 3, Rotterdam"
    assert "Bouwjaar: 1978" in result["notes"]
    assert "Woonoppervlakte: 95 m²" in result["notes"]
    assert "Perceel: 140 m²" in result["notes"]


def test_parse_meta_price_fallback():
    html = """<html><head>
<meta property="og:price:amount" content="275000">
</head><body></body></html>"""
    result = parse_funda_html(
        "https://www.funda.nl/koop/eindhoven/huis-9-laan-4/",
        html,
    )
    assert result["offer"] == 275000


def test_parse_koopprijs_with_euro_sign():
    html = '<script>{"koopprijs":"€ 425.000"}</script>'
    result = parse_funda_html(
        "https://www.funda.nl/koop/amsterdam/huis-1-straat-1/",
        html,
    )
    assert result["offer"] == 425000


# ── URL adres-parsing ────────────────────────────────────────────────────

def test_parse_address_with_detail_prefix():
    html = '<script>{"asking_price": 300000}</script>'
    result = parse_funda_html(
        "https://www.funda.nl/detail/koop/amsterdam/huis-42-hoofdstraat-26a/",
        html,
    )
    assert result["name"] == "Hoofdstraat 26a, Amsterdam"


def test_parse_address_strips_appartement_prefix():
    html = '<script>{"asking_price": 200000}</script>'
    result = parse_funda_html(
        "https://www.funda.nl/koop/utrecht/appartement-7-kanaalstraat-10/",
        html,
    )
    assert result["name"].startswith("Kanaalstraat")
    assert "Utrecht" in result["name"]


def test_parse_huisnummer_not_title_cased():
    html = '<script>{"asking_price": 300000}</script>'
    result = parse_funda_html(
        "https://www.funda.nl/koop/amsterdam/huis-1-kerkstraat-26a/",
        html,
    )
    assert "26a" in result["name"]
    assert "26A" not in result["name"]


# ── Error-paden ──────────────────────────────────────────────────────────

def test_parse_raises_when_empty():
    with pytest.raises(FundaParseError):
        parse_funda_html(
            "https://www.funda.nl/",
            "<html><body>Niets bruikbaars</body></html>",
        )


def test_parse_only_name_no_price_still_ok():
    """Alleen adres uit URL is genoeg — prijs mag None."""
    result = parse_funda_html(
        "https://www.funda.nl/koop/haarlem/huis-1-dorpsstraat-5/",
        "<html></html>",
    )
    assert result["name"] == "Dorpsstraat 5, Haarlem"
    assert result["offer"] is None


def test_parse_rejects_non_price_numbers():
    """Garbage digits (bv. postcode) mogen niet als prijs oppakken."""
    html = '<script>{"asking_price": 500}</script>'  # Te klein, < 10k
    result = parse_funda_html(
        "https://www.funda.nl/koop/delft/huis-1-kerkstraat-1/",
        html,
    )
    assert result["offer"] is None


# ── Endpoint integratie ──────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="admin", is_admin=1):
    u = User(
        username=username,
        email=f"{username}@x.nl",
        password_hash=hash_password("pw"),
        is_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


def test_funda_lookup_requires_admin(db_session):
    bob = _make_user(db_session, "bob", is_admin=0)
    resp = _client(bob.id).post(
        "/hypotheek/scenarios/funda-lookup",
        data={"url": "https://www.funda.nl/koop/amsterdam/huis-1-kerkstraat-1/"},
    )
    assert resp.status_code == 404


def test_funda_lookup_returns_json(db_session, monkeypatch):
    admin = _make_user(db_session)

    def fake_fetch(url):
        return {
            "name": "Kerkstraat 12, Utrecht",
            "offer": 425000,
            "energy_label": "B",
            "notes": "Bouwjaar: 1925",
        }

    monkeypatch.setattr("app.routers.mortgage.fetch_funda", fake_fetch)
    resp = _client(admin.id).post(
        "/hypotheek/scenarios/funda-lookup",
        data={"url": "https://www.funda.nl/koop/utrecht/huis-1-kerkstraat-12/"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Kerkstraat 12, Utrecht"
    assert body["offer"] == 425000
    assert body["energy_label"] == "B"


def test_funda_lookup_returns_400_on_parse_error(db_session, monkeypatch):
    admin = _make_user(db_session)

    def fake_fetch(url):
        raise FundaParseError("Geen prijs gevonden.")

    monkeypatch.setattr("app.routers.mortgage.fetch_funda", fake_fetch)
    resp = _client(admin.id).post(
        "/hypotheek/scenarios/funda-lookup",
        data={"url": "https://www.funda.nl/koop/x/huis-1-a-1/"},
    )
    assert resp.status_code == 400
    assert "Geen prijs" in resp.json()["error"]


def test_funda_lookup_rejects_non_funda_url(db_session):
    admin = _make_user(db_session)
    resp = _client(admin.id).post(
        "/hypotheek/scenarios/funda-lookup",
        data={"url": "https://example.com/huis"},
    )
    assert resp.status_code == 400
    assert "funda" in resp.json()["error"].lower()


# ── fetch_funda netwerkgedrag (met monkeypatch op requests.get) ──────────

def test_fetch_funda_handles_network_error(monkeypatch):
    import requests

    def boom(*a, **kw):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(funda_parser.requests, "get", boom)
    with pytest.raises(FundaParseError) as exc:
        funda_parser.fetch_funda("https://www.funda.nl/koop/x/huis-1-a-1/")
    assert "bereiken" in str(exc.value).lower()


def test_fetch_funda_handles_404(monkeypatch):
    class FakeResp:
        status_code = 404
        text = ""

    monkeypatch.setattr(funda_parser.requests, "get", lambda *a, **kw: FakeResp())
    with pytest.raises(FundaParseError) as exc:
        funda_parser.fetch_funda("https://www.funda.nl/koop/x/huis-1-a-1/")
    assert "404" in str(exc.value) or "bestaat niet meer" in str(exc.value).lower()


def test_fetch_funda_happy_path(monkeypatch):
    class FakeResp:
        status_code = 200
        text = _JSONLD_HTML

    monkeypatch.setattr(funda_parser.requests, "get", lambda *a, **kw: FakeResp())
    result = funda_parser.fetch_funda(
        "https://www.funda.nl/koop/utrecht/huis-1-kerkstraat-12/"
    )
    assert result["offer"] == 425000
    assert result["energy_label"] == "B"
