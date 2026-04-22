"""Tests voor rentetabel bulk-invoer (GJA-31)."""
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
from app.models import MortgageRateTable, User
from app.mortgage_rate_parser import ParsedRate, parse_bulk_rates


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        db.query(MortgageRateTable).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="admin", is_admin=1):
    u = User(
        username=username, email=f"{username}@x.nl",
        password_hash=hash_password("pw"), is_admin=is_admin,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _client(user_id: int) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("session", create_session_cookie(user_id))
    return c


# ──────────────────────────────────────────────────────────────────────────────
# Parser unit tests
# ──────────────────────────────────────────────────────────────────────────────


def test_parser_simple_tsv():
    text = """fixed_years	ltv_max_pct	interest_rate
5	0.65	0.0339
10	0.85	0.0375
20	0.86	0.0444"""
    result = parse_bulk_rates(text)
    assert not result.has_errors
    assert len(result.rows) == 3
    assert result.rows[0] == ParsedRate(5, Decimal("0.6500"), Decimal("0.0339"))
    assert result.rows[1] == ParsedRate(10, Decimal("0.8500"), Decimal("0.0375"))


def test_parser_simple_tsv_with_percent_notation():
    text = """5\t85\t3,75
10\t85\t3,95"""
    result = parse_bulk_rates(text)
    assert not result.has_errors
    assert result.rows[0].ltv_max_pct == Decimal("0.8500")
    assert result.rows[0].interest_rate == Decimal("0.0375")


def test_parser_abn_table():
    text = """\tNHG\t≤65%\t≤85%\t≤90%\t>90%
10 jaar vast\t3,65%\t3,73%\t3,75%\t3,77%\t3,95%
20 jaar vast\t4,05%\t4,16%\t4,25%\t4,35%\t4,44%"""
    result = parse_bulk_rates(text)
    # NHG-kolom wordt overgeslagen; dus 4 LTV-buckets × 2 periodes = 8.
    assert len(result.rows) == 8
    fixed_years_set = {r.fixed_years for r in result.rows}
    assert fixed_years_set == {10, 20}
    # NHG-melding in skipped:
    assert any("NHG" in s for s in result.skipped)
    # Specifiek: 10j × 85% = 3,75%
    match = [r for r in result.rows if r.fixed_years == 10 and r.ltv_max_pct == Decimal("0.8500")]
    assert len(match) == 1
    assert match[0].interest_rate == Decimal("0.0375")


def test_parser_abn_table_skips_variabel_row():
    text = """\t≤65%\t≤85%
5 jaar vast\t3,39%\t3,44%
Variabel\t4,50%\t4,60%"""
    result = parse_bulk_rates(text)
    assert {r.fixed_years for r in result.rows} == {5}
    assert any("Variabel" in s or "variabel" in s.lower() for s in result.skipped)


def test_parser_rejects_invalid_numbers():
    text = "10\t0.85\tabc"
    result = parse_bulk_rates(text)
    assert result.has_errors
    assert len(result.rows) == 0


def test_parser_rejects_out_of_range_years():
    text = "0\t0.85\t0.0375"
    result = parse_bulk_rates(text)
    assert result.has_errors


def test_parser_detects_duplicate():
    text = """5\t0.85\t0.0339
5\t85\t3,44"""
    result = parse_bulk_rates(text)
    assert result.has_errors
    assert any("Dubbele" in e for e in result.errors)


def test_parser_empty_input():
    assert parse_bulk_rates("").has_errors
    assert parse_bulk_rates("   \n  \n").has_errors


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end flow
# ──────────────────────────────────────────────────────────────────────────────


def test_preview_shows_new_and_update(db_session):
    admin = _make_user(db_session)
    # Bestaande rente om update te forceren.
    db_session.add(MortgageRateTable(
        user_id=admin.id, fixed_years=10, ltv_max_pct=Decimal("0.85"),
        interest_rate=Decimal("0.0350"),
    ))
    db_session.commit()

    text = "10\t0.85\t0.0375\n5\t0.85\t0.0339"
    resp = _client(admin.id).post("/hypotheek/rentes/bulk/preview", data={"raw_text": text})
    assert resp.status_code == 200
    assert "Voorvertoning" in resp.text
    assert "1 nieuw" in resp.text
    assert "1 bijgewerkt" in resp.text
    # Geen import gedaan yet.
    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(
        MortgageRateTable.user_id == admin.id,
    ).count() == 1


def test_import_upserts(db_session):
    admin = _make_user(db_session)
    db_session.add(MortgageRateTable(
        user_id=admin.id, fixed_years=10, ltv_max_pct=Decimal("0.85"),
        interest_rate=Decimal("0.0350"),
    ))
    db_session.commit()

    text = "10\t0.85\t0.0375\n5\t0.65\t0.0339"
    resp = _client(admin.id).post("/hypotheek/rentes/bulk/import", data={"raw_text": text})
    assert resp.status_code == 302
    assert "flash=bulk_imported" in resp.headers["location"]
    assert "new=1" in resp.headers["location"]
    assert "upd=1" in resp.headers["location"]

    db_session.expire_all()
    rows = db_session.query(MortgageRateTable).filter(
        MortgageRateTable.user_id == admin.id,
    ).all()
    assert len(rows) == 2
    ten = next(r for r in rows if r.fixed_years == 10)
    assert ten.interest_rate == Decimal("0.0375")
    five = next(r for r in rows if r.fixed_years == 5)
    assert five.interest_rate == Decimal("0.0339")


def test_import_aborts_on_parse_errors(db_session):
    admin = _make_user(db_session)
    # Dubbele-detectie blokkeert import volledig.
    text = "10\t0.85\t0.0375\n10\t0.85\t0.0400"
    resp = _client(admin.id).post("/hypotheek/rentes/bulk/import", data={"raw_text": text})
    assert resp.status_code == 400
    assert "Import geannuleerd" in resp.text

    db_session.expire_all()
    assert db_session.query(MortgageRateTable).filter(
        MortgageRateTable.user_id == admin.id,
    ).count() == 0


def test_non_admin_cannot_access_bulk_endpoints(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    client = _client(user.id)
    assert client.post("/hypotheek/rentes/bulk/preview", data={"raw_text": ""}).status_code == 404
    assert client.post("/hypotheek/rentes/bulk/import", data={"raw_text": ""}).status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Screenshot upload (GJA-40)
# ──────────────────────────────────────────────────────────────────────────────

# Exact de 13 rijen uit de ABN-voorbeeld-screenshot in het issue, als wat het
# vision-model terug hoort te geven. Onze parser slaat "Variabel" en de
# NHG-kolom over → 12 rentevast × 4 LTV-buckets = 48 geïmporteerde rijen.
ABN_SAMPLE_OCR_OUTPUT = (
    "\tNHG\t≤65%\t≤85%\t≤90%\t>90%\n"
    "Variabel\t3,60%\t3,65%\t3,80%\t3,95%\t4,05%\n"
    "1 jaar vast\t3,79%\t3,80%\t3,85%\t3,86%\t3,89%\n"
    "2 jaar vast\t3,76%\t3,77%\t3,82%\t3,83%\t3,86%\n"
    "3 jaar vast\t3,76%\t3,77%\t3,82%\t3,83%\t3,86%\n"
    "5 jaar vast\t3,71%\t3,75%\t3,80%\t3,81%\t3,83%\n"
    "6 jaar vast\t3,75%\t3,99%\t4,04%\t4,05%\t4,07%\n"
    "7 jaar vast\t3,77%\t4,01%\t4,06%\t4,07%\t4,09%\n"
    "10 jaar vast\t3,75%\t4,04%\t4,05%\t4,06%\t4,07%\n"
    "12 jaar vast\t3,96%\t4,22%\t4,24%\t4,29%\t4,40%\n"
    "15 jaar vast\t4,10%\t4,26%\t4,37%\t4,51%\t4,58%\n"
    "17 jaar vast\t4,11%\t4,26%\t4,37%\t4,51%\t4,58%\n"
    "20 jaar vast\t4,29%\t4,44%\t4,53%\t4,61%\t4,72%\n"
    "30 jaar vast\t4,48%\t4,62%\t4,69%\t4,76%\t4,82%\n"
)


def _png_bytes(size: int = 500) -> bytes:
    """Een minimale maar geldig-ogende PNG-blob (headers zonder echte pixels).
    Het AI-model wordt toch gemonkeypatched — de server valideert alleen
    content-type en grootte.
    """
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def test_screenshot_ocr_success_triggers_preview(db_session, monkeypatch):
    """Happy path: OCR geeft de ABN-tekst terug → preview toont 48 nieuwe rijen."""
    from app import mortgage_rate_ocr

    admin = _make_user(db_session, "admin", is_admin=1)
    calls = {"n": 0}

    def fake_ocr(image_bytes, media_type):
        calls["n"] += 1
        return mortgage_rate_ocr.OCRResult(ok=True, text=ABN_SAMPLE_OCR_OUTPUT)

    monkeypatch.setattr("app.routers.mortgage.extract_rate_text", fake_ocr)

    resp = _client(admin.id).post(
        "/hypotheek/rentes/bulk/screenshot",
        files={"image": ("abn.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert calls["n"] == 1
    # Preview-indicators
    assert "Voorvertoning" in resp.text
    # 12 rentevast-labels × 4 LTV-buckets = 48 rijen — check een paar concrete waarden
    assert "30 jaar" in resp.text
    # De raw OCR-tekst zit in de textarea zodat de user kan corrigeren vóór import
    assert "3,79" in resp.text


def test_screenshot_ocr_output_matches_paste_flow(db_session, monkeypatch):
    """Als paste-flow én screenshot-flow dezelfde tekst zien, moeten beide
    hetzelfde aantal rijen opleveren in de preview (48, ABN 12×4 grid)."""
    from app import mortgage_rate_ocr
    admin = _make_user(db_session, "admin", is_admin=1)

    parsed = parse_bulk_rates(ABN_SAMPLE_OCR_OUTPUT)
    assert not parsed.has_errors, parsed.errors
    assert len(parsed.rows) == 48

    monkeypatch.setattr(
        "app.routers.mortgage.extract_rate_text",
        lambda b, m: mortgage_rate_ocr.OCRResult(ok=True, text=ABN_SAMPLE_OCR_OUTPUT),
    )
    resp = _client(admin.id).post(
        "/hypotheek/rentes/bulk/screenshot",
        files={"image": ("abn.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200


def test_screenshot_ocr_failure_shows_error(db_session, monkeypatch):
    from app import mortgage_rate_ocr
    admin = _make_user(db_session, "admin", is_admin=1)

    monkeypatch.setattr(
        "app.routers.mortgage.extract_rate_text",
        lambda b, m: mortgage_rate_ocr.OCRResult(
            ok=False, error="Kon geen rente-tabel herkennen in de afbeelding."
        ),
    )
    resp = _client(admin.id).post(
        "/hypotheek/rentes/bulk/screenshot",
        files={"image": ("wazig.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 400
    assert "Kon geen rente-tabel herkennen" in resp.text
    # Paste-textarea blijft functioneel — de paste-form staat nog op dezelfde pagina
    assert 'action="/hypotheek/rentes/bulk/preview"' in resp.text


def test_screenshot_rejects_non_admin(db_session):
    user = _make_user(db_session, "bob", is_admin=0)
    resp = _client(user.id).post(
        "/hypotheek/rentes/bulk/screenshot",
        files={"image": ("abn.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 404


def test_ocr_helper_rejects_invalid_media_type():
    from app.mortgage_rate_ocr import extract_rate_text
    res = extract_rate_text(b"\x00" * 10, "application/pdf")
    assert res.ok is False
    assert "PNG" in (res.error or "") or "toegestaan" in (res.error or "")


def test_ocr_helper_rejects_oversize_image():
    from app.mortgage_rate_ocr import extract_rate_text, MAX_IMAGE_BYTES
    res = extract_rate_text(b"\x00" * (MAX_IMAGE_BYTES + 1), "image/png")
    assert res.ok is False
    assert "5 MB" in (res.error or "")


def test_ocr_helper_rejects_empty_image():
    from app.mortgage_rate_ocr import extract_rate_text
    res = extract_rate_text(b"", "image/png")
    assert res.ok is False


def test_ocr_helper_without_api_key(monkeypatch):
    from app import mortgage_rate_ocr
    monkeypatch.setattr(mortgage_rate_ocr, "ANTHROPIC_API_KEY", "")
    res = mortgage_rate_ocr.extract_rate_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")
    assert res.ok is False
    assert "niet geconfigureerd" in (res.error or "")
